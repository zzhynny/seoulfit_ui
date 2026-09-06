"""RAG layer over course_data.json.

Builds (or loads) a FAISS index of Seoul travel courses, embedded with
Google's text-embedding-004. Each course becomes one Document; the full
course dict is stashed in metadata so retrieval hands the planner
ready-to-use POI sequences.

개선사항:
1. 여러 지역 입력 시 (예: "Hongdae and Seongsu") 지역별 분리 검색
2. 목적별 특화 쿼리 생성
3. 중복 제거 후 합치기
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from geo import (
    AREA_ALIASES,
    area_label,
    area_matches_requested,
    extract_requested_areas,
    infer_area_from_fields,
)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_BASE_DIR = Path(__file__).resolve().parent
# v2: course_data.json + POI별 is_area_type / requires_review 플래그
# (거리/구역을 가리키는 POI를 구분하기 위해 추가됨).
# v3: v2 + seoul.json 매칭으로 얻은 opening_hours 필드(93건; 없으면 필드 생략).
# v4: v3 + TourAPI(EngService2) 배치 매칭으로 얻은 opening_hours 추가(99건, source=tourapi).
# v5: v4 + is_generic_activity 플래그(16건) — "Karaoke"/"Jjimjilbang"처럼 특정
#     업체가 아니라 활동 카테고리 라벨인 POI를 표시(126개 코스 전수 검토로 확정).
# v6: v5 + opening_hours.closed_weekday(151건) — Google Places Legacy Place
#     Details(opening_hours.weekday_text)로 얻은 정기 휴무 요일. LLM 웹서칭
#     기반 closure_check.py보다 훨씬 신뢰도가 높아(151/192 vs grounding
#     인용 첨부율 12.5%) 정기 휴무 판정은 이쪽으로 옮김(scripts/
#     google_places_closed_weekday_fill.py).
# 원본 course_data.json은 그대로 두고 별도 파일로 관리한다.
# v1~v6 전부 backend/dataset/ 밑으로 이동(원격의 "move data files under
# dataset/" 구조에 맞춤, 2026-09-02). 안 쓰는 중간 버전 파일도 지우지 않고
# 그대로 dataset/ 안에 둔다.
COURSE_DATA_PATH = _BASE_DIR / "dataset" / "course_data_v6.json"
VECTORSTORE_DIR = _BASE_DIR / "vectorstore"

EMBEDDING_MODEL = "models/gemini-embedding-001"

EMBED_CHUNK_SIZE = 50
EMBED_CHUNK_SLEEP_SECONDS = 60
EMBED_MAX_RETRIES = 5


# ---------------------------------------------------------------------------
# Document construction
# ---------------------------------------------------------------------------

def _course_to_text(course: dict[str, Any]) -> str:
    """Flatten a course into a single searchable string."""
    title = course.get("course_title", "")
    themes = ", ".join(course.get("theme_category", []) or [])
    source = course.get("source", "")

    poi_lines = []
    for poi in course.get("sequence", []) or []:
        name = poi.get("poi_name", "")
        ptype = poi.get("poi_type", "")
        addr = poi.get("address_en") or poi.get("address_ko", "")
        poi_lines.append(f"- ({ptype}) {name} — {addr}")
    pois = "\n".join(poi_lines)

    return (
        f"Title: {title}\n"
        f"Source: {source}\n"
        f"Themes: {themes}\n"
        f"POIs:\n{pois}"
    )


def _course_to_document(course: dict[str, Any]) -> Document:
    sequence = course.get("sequence", []) or []
    try:
        total_min = sum(int(p.get("estimated_stay_time", 0) or 0) for p in sequence)
    except (TypeError, ValueError):
        total_min = 0

    metadata = {
        "course_id": course.get("course_id"),
        "source": course.get("source"),
        "source_url": course.get("source_url"),
        "course_title": course.get("course_title"),
        "themes": course.get("theme_category", []) or [],
        "poi_count": len(sequence),
        "total_estimated_minutes": total_min,
        "course": course,
    }
    return Document(page_content=_course_to_text(course), metadata=metadata)


def _load_courses(path: Path = COURSE_DATA_PATH) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Vector store build / load
# ---------------------------------------------------------------------------

_vectorstore: FAISS | None = None
_vectorstore_api_key: str | None = None


def _get_embeddings(api_key: str) -> GoogleGenerativeAIEmbeddings:
    key = (api_key or "").strip()
    if not key:
        raise ValueError(
            "Empty Gemini API key. Set GOOGLE_API_KEY before launching the server."
        )
    return GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL, google_api_key=key)


_RETRY_DELAY_RE = re.compile(r"retry[_ ]delay[^0-9]*(\d+)", re.IGNORECASE)


def _parse_retry_seconds(err: Exception, default: int = EMBED_CHUNK_SLEEP_SECONDS) -> int:
    """Extract the server-suggested retry_delay from a 429 error string."""
    m = _RETRY_DELAY_RE.search(str(err))
    if m:
        try:
            return int(m.group(1)) + 1
        except ValueError:
            pass
    return default


def _embed_with_retry(
    embeddings: GoogleGenerativeAIEmbeddings,
    texts: list[str],
) -> list[list[float]]:
    """embed_documents with exponential-ish backoff on 429s."""
    for attempt in range(EMBED_MAX_RETRIES):
        try:
            return embeddings.embed_documents(texts)
        except Exception as e:
            msg = str(e)
            is_quota = "429" in msg or "quota" in msg.lower() or "rate" in msg.lower()
            if not is_quota or attempt == EMBED_MAX_RETRIES - 1:
                raise
            wait = _parse_retry_seconds(e)
            print(
                f"   ⚠️  rate-limited (attempt {attempt + 1}/{EMBED_MAX_RETRIES}), "
                f"sleeping {wait}s and retrying..."
            )
            time.sleep(wait)
    raise RuntimeError("unreachable")


def _embed_documents_chunked(
    docs: list[Document],
    embeddings: GoogleGenerativeAIEmbeddings,
    chunk_size: int = EMBED_CHUNK_SIZE,
    chunk_sleep: int = EMBED_CHUNK_SLEEP_SECONDS,
) -> list[tuple[str, list[float]]]:
    """Embed docs in rate-limit-friendly chunks. Returns (text, vector) pairs."""
    texts = [d.page_content for d in docs]
    pairs: list[tuple[str, list[float]]] = []
    total = len(texts)
    for start in range(0, total, chunk_size):
        end = min(start + chunk_size, total)
        chunk = texts[start:end]
        print(f"   embedding {start + 1}–{end} of {total}...")
        vectors = _embed_with_retry(embeddings, chunk)
        pairs.extend(zip(chunk, vectors))
        if end < total:
            print(f"   sleeping {chunk_sleep}s to respect rate limit...")
            time.sleep(chunk_sleep)
    return pairs


def build_or_load_vectorstore(
    api_key: str,
    persist_dir: Path = VECTORSTORE_DIR,
    rebuild: bool = False,
) -> FAISS:
    """Return a FAISS index over course_data.json."""
    global _vectorstore, _vectorstore_api_key

    if _vectorstore is not None and _vectorstore_api_key == api_key and not rebuild:
        return _vectorstore

    embeddings = _get_embeddings(api_key)
    index_file = persist_dir / "index.faiss"

    if index_file.exists() and not rebuild:
        store = FAISS.load_local(
            str(persist_dir),
            embeddings,
            allow_dangerous_deserialization=True,
        )
    else:
        courses = _load_courses()
        docs = [_course_to_document(c) for c in courses]
        metadatas = [d.metadata for d in docs]

        text_embeddings = _embed_documents_chunked(docs, embeddings)
        store = FAISS.from_embeddings(
            text_embeddings=text_embeddings,
            embedding=embeddings,
            metadatas=metadatas,
        )
        persist_dir.mkdir(parents=True, exist_ok=True)
        store.save_local(str(persist_dir))

    _vectorstore = store
    _vectorstore_api_key = api_key
    return store


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def _extract_areas(location: str) -> list[str]:
    # 괄호 제거
    location = re.sub(r'[()]', '', location)
    # "Seoul" 단독 단어 제거
    location = re.sub(r'\bSeoul\b', '', location, flags=re.IGNORECASE)
    # and, &, comma, slash로 분리
    areas = re.split(r"\s+and\s+|\s*&\s*|\s*,\s*|\s*/\s*", location, flags=re.IGNORECASE)
    # 빈 문자열 제거
    return [a.strip() for a in areas if a.strip()]


def build_query(
    purpose: str | None,
    dietary: str | None,
    location: str | None,
    duration: str | None = None,
) -> str:
    """Compose a natural-language query from the user's confirmed fields."""
    parts = []
    if purpose:
        parts.append(f"Travel purpose: {purpose}.")
    if location:
        parts.append(f"Area or neighborhood of interest: {location}.")
    if dietary and dietary.lower() not in {"none", "no", "n/a", "없음"}:
        parts.append(f"Dietary preference: {dietary}.")
    if duration:
        parts.append(f"Trip length: {duration}.")
    if not parts:
        return "Seoul travel itinerary"
    return " ".join(parts)


def retrieve_courses(
    api_key: str,
    query: str,
    k: int = 5,
    location: str | None = None,
    purpose: str | None = None,
) -> list[dict[str, Any]]:
    """
    Return the top-k course dicts (full payloads) for a query.
    location이 여러 지역이면 각각 검색해서 합침.
    """
    store = build_or_load_vectorstore(api_key)

    # 지역 추출
    areas = _extract_areas(location) if location else []

    if len(areas) >= 2:
        # 여러 지역이면 각각 검색 후 합치기
        seen_ids: set[str] = set()
        all_courses: list[dict[str, Any]] = []
        per_area_k = max(2, k // len(areas))

        for area in areas:
            # 지역별 특화 쿼리 생성
            if purpose:
                area_query = f"{area} {purpose} Seoul travel itinerary"
            else:
                area_query = f"{area} Seoul travel itinerary"

            docs = store.similarity_search(area_query, k=per_area_k)
            for d in docs:
                course = d.metadata.get("course", {})
                cid = course.get("course_id")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    all_courses.append(course)

        # 부족하면 전체 쿼리로 보완
        if len(all_courses) < k:
            docs = store.similarity_search(query, k=k)
            for d in docs:
                course = d.metadata.get("course", {})
                cid = course.get("course_id")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    all_courses.append(course)
                    if len(all_courses) >= k:
                        break

        print(f"[RAG] 지역별 검색: {areas} → {len(all_courses)}개 코스 확보")
        return all_courses[:k]

    else:
        # 단일 지역이면 기존 방식
        docs = store.similarity_search(query, k=k)
        courses = [d.metadata.get("course", {}) for d in docs if d.metadata.get("course")]
        print(f"[RAG] 단일 검색 → {len(courses)}개 코스 확보")
        return courses


# ---------------------------------------------------------------------------
# Day-segment planning (dual-index retrieval)
# ---------------------------------------------------------------------------
#
# The dual-index plan splits a multi-area / multi-purpose trip into discrete
# day segments. Each segment is retrieved independently — Index A for whole
# editorial courses, Index B for gap-filling individual POIs — so a request
# like "2 days Hongdae + 1 day historical" no longer blends into a single
# muddled query.


_MONTH_RE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b",
    re.IGNORECASE,
)


def _looks_like_single_date(text: str) -> bool:
    """True if the text reads as one calendar date (e.g. 'June 23', '6/23',
    '2026-06-23') rather than a duration. Used to stop a day-of-month from being
    misread as a day count — a single visit date is one day.
    """
    return bool(
        _MONTH_RE.search(text)
        or re.search(r"\d{4}-\d{1,2}-\d{1,2}", text)
        or re.search(r"\b\d{1,2}\s*/\s*\d{1,2}\b", text)
    )


def _days_from_date_range(text: str) -> int:
    """Compute the inclusive number of days spanned by a date range, or 0 if the
    text isn't a recognizable range.

    Handles ISO ranges ('2026-06-23 to 2026-06-24'), month-name ranges
    ('june 23 to 24', 'june 30 - july 2'), and bare day-of-month ranges
    ('23-24'). Inclusive: June 23→24 is 2 days.
    """
    # ISO dates first — splitting on '-' would otherwise break them apart.
    iso = re.findall(r"\d{4}-\d{1,2}-\d{1,2}", text)
    if len(iso) >= 2:
        try:
            d0 = datetime.strptime(iso[0], "%Y-%m-%d").date()
            d1 = datetime.strptime(iso[-1], "%Y-%m-%d").date()
            span = abs((d1 - d0).days) + 1
            if 1 <= span <= 60:
                return span
        except ValueError:
            pass
    elif len(iso) == 1:
        # A single ISO date is not a range; bail before the '-' split below
        # tears '2026-06-23' into '2026' and '23'.
        return 0

    # Split on range separators: to / through / until / ~ / dashes.
    parts = re.split(r"\s*(?:to|through|until|thru|~|–|—|-)\s*", text)
    if len(parts) < 2:
        return 0
    start_part, end_part = parts[0].strip(), parts[-1].strip()

    # Try real date parsing (carries the start's month into a bare end day).
    try:
        from dateutil import parser as _dp

        base = datetime(2000, 1, 1)
        start = _dp.parse(start_part, fuzzy=True, default=base)
        end = _dp.parse(end_part, fuzzy=True, default=start)
        span = (end.date() - start.date()).days + 1
        if span < 1:
            # Cross-month range: end day-of-month < start (e.g. "June 30 to 2"
            # → July 2). dateutil inferred the same month; advance by one month.
            month = end.month % 12 + 1
            year = end.year + (1 if end.month == 12 else 0)
            end = end.replace(year=year, month=month)
            span = (end.date() - start.date()).days + 1
        if 1 <= span <= 60:
            return span
    except (ValueError, OverflowError, ImportError):
        pass

    # Fallback: two day-of-month numbers in the same month ('june 23 to 24').
    n0 = re.search(r"(\d{1,2})", start_part)
    n1 = re.search(r"(\d{1,2})", end_part)
    if n0 and n1:
        a, b = int(n0.group(1)), int(n1.group(1))
        if 0 <= (b - a) <= 60:
            return (b - a) + 1
    return 0


# ---------------------------------------------------------------------------
# Trip start date — best-effort extraction of an actual calendar date from the
# same free-text travel_dates string _parse_num_days() reads. Separate from
# (and doesn't touch) _days_from_date_range()/_parse_num_days() above: those
# are already relied on for day-count and are left exactly as they were to
# avoid regressing them; this is new, additive, independently-testable logic.
# ---------------------------------------------------------------------------

_ISO_DATE_RE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}")
_KOREAN_MONTH_DAY_RE = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_KOREAN_WEEKDAY_RE = re.compile(r"(다음\s*주|이번\s*주|금주|차주)?\s*([월화수목금토일])\s*요일")
_KOREAN_WEEKDAY_INDEX = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
_ENGLISH_WEEKDAY_RE = re.compile(
    r"\b(next|this)?\s*(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)
_ENGLISH_WEEKDAY_INDEX = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
_RANGE_SEP_RE = re.compile(r"\s*(?:to|through|until|thru|부터|까지|~|–|—|-)\s*")


def _nearest_future(candidate: date, today: date) -> date:
    """연도가 없는 날짜가 이미 지났으면 내년으로 밀어서 '가장 가까운 미래'로 해석."""
    if candidate < today:
        try:
            return candidate.replace(year=candidate.year + 1)
        except ValueError:
            return candidate  # 2/29 같은 극단 케이스는 그냥 그대로 둔다
    return candidate


def _resolve_weekday_phrase(weekday: int, qualifier: str, today: date) -> date:
    """'다음 주 화요일'/'next Tuesday'/'이번 주 화요일'/'this Tuesday'/수식어 없는
    '화요일'을 실제 날짜로 변환. 수식어 없으면 오늘 이후 가장 가까운 그 요일(오늘
    당일은 포함하지 않음 — 여행 계획이 "오늘부터"라면 사용자가 그렇게 말했을 것)."""
    if qualifier in ("다음주", "차주", "next"):
        this_monday = today - timedelta(days=today.weekday())
        return this_monday + timedelta(weeks=1, days=weekday)
    if qualifier in ("이번주", "금주", "this"):
        this_monday = today - timedelta(days=today.weekday())
        return this_monday + timedelta(days=weekday)
    days_ahead = (weekday - today.weekday()) % 7
    days_ahead = days_ahead or 7
    return today + timedelta(days=days_ahead)


def parse_trip_start_date(text: str | None, *, today: date | None = None) -> str | None:
    """자유 텍스트(travel_dates)에서 여행 시작일을 최대한 추출해 ISO
    "YYYY-MM-DD" 문자열로 반환한다.

    - 연도가 명시 안 된 날짜는 '가장 가까운 미래'로 해석한다(예: 지금이 9월인데
      "6월 15일"이면 내년 6월 15일).
    - 앵커할 캘린더 날짜가 전혀 없는 입력("3 days", "3일간", "4박5일"만 있고
      요일/월일 언급이 없는 경우)은 None을 반환한다 — 이건 폴백이지 에러가
      아니다. 호출부는 기존처럼 일수만으로 진행해야 한다.
    """
    if not text:
        return None
    text = text.strip()
    if not text or text.upper() == "MISSING":
        return None

    today = today or date.today()

    # 1. ISO 날짜가 이미 텍스트에 있으면 그대로 신뢰 (가장 확실한 신호).
    iso_match = _ISO_DATE_RE.search(text)
    if iso_match:
        try:
            return datetime.strptime(iso_match.group(), "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass

    # 2. 상대 요일 표현: "다음 주 화요일" / "next Tuesday" / 수식어 없는 요일.
    m = _KOREAN_WEEKDAY_RE.search(text)
    if m:
        qualifier = (m.group(1) or "").replace(" ", "")
        weekday = _KOREAN_WEEKDAY_INDEX[m.group(2)]
        return _resolve_weekday_phrase(weekday, qualifier, today).isoformat()

    m = _ENGLISH_WEEKDAY_RE.search(text)
    if m:
        qualifier = (m.group(1) or "").lower()
        weekday = _ENGLISH_WEEKDAY_INDEX[m.group(2).lower()]
        return _resolve_weekday_phrase(weekday, qualifier, today).isoformat()

    # 3. 한국어 "N월 N일" (연도 없음) — 가장 가까운 미래로 해석.
    m = _KOREAN_MONTH_DAY_RE.search(text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        try:
            candidate = date(today.year, month, day)
        except ValueError:
            return None
        return _nearest_future(candidate, today).isoformat()

    # 4. 순수 기간 표현("3 days", "4박5일", "일주일")뿐이면 앵커할 날짜가 없다 —
    #    dateutil의 fuzzy 모드가 "3"을 날짜로 잘못 해석해버리는 걸 막기 위해,
    #    실제 날짜처럼 보이는 신호(월 이름/ISO/M-D 슬래시)가 전혀 없으면 여기서
    #    바로 포기한다.
    start_part = _RANGE_SEP_RE.split(text, maxsplit=1)[0].strip() or text
    if not _looks_like_single_date(start_part) and not _looks_like_single_date(text):
        return None

    try:
        from dateutil import parser as _dp

        parsed = _dp.parse(start_part, fuzzy=True, default=datetime(today.year, 1, 1))
        candidate = parsed.date()
    except (ValueError, OverflowError, ImportError, TypeError):
        return None

    has_explicit_year = bool(re.search(r"\b(19|20)\d{2}\b", text))
    if not has_explicit_year:
        candidate = _nearest_future(candidate, today)
    return candidate.isoformat()


def _parse_num_days(duration: str | None) -> int:
    """Parse the number of trip days from a free-text duration/date string.

    Order matters: explicit '4 days'/'1 week' win, then date ranges like
    'June 23 to 24' (→ 2), and only a small bare number is trusted as a day
    count — so '23' from a date never becomes a 23-day trip.
    """
    if not duration:
        return 1
    text = duration.lower().strip()

    week_match = re.search(r"(\d+)\s*week", text)
    if week_match:
        return int(week_match.group(1)) * 7

    # Explicit day count (incl. Korean 일) — preferred over a night count so
    # '2박 3일' (2 nights / 3 days) reads as 3.
    day_match = re.search(r"(\d+)\s*(?:days?|일)", text)
    if day_match:
        return max(1, int(day_match.group(1)))
    night_match = re.search(r"(\d+)\s*(?:nights?|박)", text)
    if night_match:
        return max(1, int(night_match.group(1)))

    # Date range → inclusive span.
    span = _days_from_date_range(text)
    if span:
        return span

    # A single calendar date (no range) is a one-day visit — don't let its
    # day-of-month (e.g. '23' in 'June 23') become a 23-day trip.
    if _looks_like_single_date(text):
        return 1

    # Bare number, only if it's a plausible trip length (avoid reading a
    # day-of-month like '23' as a 23-day trip).
    num_match = re.search(r"\b(\d{1,2})\b", text)
    if num_match:
        n = int(num_match.group(1))
        if 1 <= n <= 30:
            return n
    return 1


def _split_purpose_by_area(
    purpose: str,
    areas: list[str],
) -> dict[str, str]:
    """Best-effort match of purpose clauses to areas.

    Splits on 'and' / ',' / 'then' / ';' and tries to attach each clause to an
    area by checking if the area's aliases appear in the clause. If no clause
    mentions a given area, that area falls back to the full purpose string.
    """
    if not purpose:
        return {a: "" for a in areas}

    clauses = re.split(
        r"\s+and\s+|\s+then\s+|\s*[,;]\s*",
        purpose,
        flags=re.IGNORECASE,
    )
    clauses = [c.strip() for c in clauses if c.strip()]

    hints: dict[str, str] = {}
    for area in areas:
        aliases = AREA_ALIASES.get(area, [])
        matched = next(
            (c for c in clauses
             if any(a.lower() in c.lower() for a in aliases)),
            None,
        )
        hints[area] = matched if matched else purpose
    return hints


def parse_day_segments(
    location: str | None,
    purpose: str | None,
    duration: str | None,
) -> list[dict[str, Any]]:
    """Split a trip request into per-area / per-purpose day segments.

    Returns a list of segment dicts with day_numbers + area + purpose_hint and
    an empty anchor_courses slot. Downstream retrieval fills it in.

    If no areas are detected in the user's text, returns a single segment
    covering every day with area=None and purpose_hint=purpose.
    """
    num_days = _parse_num_days(duration)
    areas = extract_requested_areas(location, purpose)

    if not areas:
        return [{
            "day_numbers":     list(range(1, num_days + 1)),
            "area":            None,
            "purpose_hint":    purpose or "",
            "anchor_courses":  [],
        }]

    purpose_hints = _split_purpose_by_area(purpose or "", areas)

    # Distribute days evenly; last area absorbs any remainder so all days are covered.
    days_per_area = max(1, num_days // len(areas))
    segments: list[dict[str, Any]] = []
    cursor = 1
    for i, area in enumerate(areas):
        if i == len(areas) - 1:
            day_range = list(range(cursor, num_days + 1))
        else:
            end = min(cursor + days_per_area, num_days + 1)
            day_range = list(range(cursor, end))
            cursor = end
        if not day_range:
            continue
        segments.append({
            "day_numbers":     day_range,
            "area":            area,
            "purpose_hint":    purpose_hints.get(area, purpose or ""),
            "anchor_courses":  [],
        })
    return segments


def segment_k(day_count: int) -> int:
    """How many anchor courses to fetch for a segment covering `day_count` days.

    Fixed k=3 both starves long single-area segments (5 days off 3 courses ->
    heavy Google padding) and over-fetches 1-day segments. Scale with days,
    +1 for slack, clamped so thin areas don't scrape the barrel and long trips
    don't balloon.
    """
    return max(2, min(6, (day_count or 0) + 1))


def rerank_courses_by_area(
    courses: list[dict[str, Any]],
    area: str | None,
) -> list[dict[str, Any]]:
    """Stable-sort courses whose POIs sit in `area` ahead of those that don't.

    The vector query mixes theme and neighborhood, so a strong theme word (e.g.
    "K-pop") can float in off-neighborhood courses. This re-rank drops them below
    the in-area ones while preserving vector rank within each group. No-op when
    `area` is None (nothing to match against).
    """
    if not area:
        return list(courses)

    def _in_area(course: dict[str, Any]) -> bool:
        for poi in course.get("sequence", []) or []:
            a = infer_area_from_fields(
                name=poi.get("poi_name", ""),
                address=poi.get("address_en") or poi.get("address_ko") or "",
                lat=poi.get("lat"), lng=poi.get("lng"),
            )
            if area_matches_requested(a, area):
                return True
        return False

    return sorted(courses, key=lambda c: 0 if _in_area(c) else 1)


def retrieve_for_segments(
    api_key: str,
    segments: list[dict[str, Any]],
    purpose: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Per-segment Index A retrieval.

    For each segment, pull the top-k whole anchor courses for the (area, purpose)
    pair from Index A. Gaps the courses don't cover (cafes, restaurants, K-POP,
    shopping) are filled later by Google Places in plan_node and by the validator
    / critic-repair.

    Returns (segments_with_data, all_anchor_courses_flat). The flat list is
    deduplicated by course_id and is what TravelState.retrieved_courses should
    be set to for backward compat with critic_repair / _normalize_sources.
    """
    store_a = build_or_load_vectorstore(api_key)

    seen_course_ids: set[str] = set()
    all_courses: list[dict[str, Any]] = []

    for seg in segments:
        area = seg.get("area")
        purpose_hint = seg.get("purpose_hint") or ""
        area_lbl = area_label(area) if area else ""
        k = segment_k(len(seg.get("day_numbers") or []))  # scale breadth to the segment's days

        query_a = f"{area_lbl} {purpose_hint} Seoul travel itinerary".strip()
        docs_a = store_a.similarity_search(query_a, k=k * 3)  # over-fetch buffer to re-rank

        # dedupe candidates by course_id, preserving vector rank
        candidates: list[dict[str, Any]] = []
        seen_cid: set[str] = set()
        for d in docs_a:
            course = d.metadata.get("course") or {}
            cid = course.get("course_id")
            if cid and cid not in seen_cid:
                seen_cid.add(cid)
                candidates.append(course)

        # drop off-neighborhood courses below in-area ones, then keep top k
        anchors = rerank_courses_by_area(candidates, area)[:k]
        for course in anchors:
            cid = course.get("course_id")
            if cid and cid not in seen_course_ids:
                seen_course_ids.add(cid)
                all_courses.append(course)
        seg["anchor_courses"] = anchors

        print(
            f"[RAG] segment days={seg.get('day_numbers')} area={area or '-'} "
            f"anchors={len(anchors)}"
        )

    return segments, all_courses
