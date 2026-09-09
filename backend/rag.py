"""여행 날짜 파싱. 코스 검색은 retrieval.py 로 옮겼다.

이 파일은 FAISS 인덱스 빌드·임베딩 청크·구간 분할까지 들고 있었다. 그 중
검색에 해당하는 부분은 전부 retrieval.py 에 있고, 여기에는 자유 텍스트 날짜를
시작일과 일수로 바꾸는 코드만 남았다.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path


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


# ---------------------------------------------------------------------------
# Duration parsing
# ---------------------------------------------------------------------------

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


def _parse_num_days(duration: str | None, override: int | None = None) -> int:
    """Parse the number of trip days from a free-text duration/date string.

    Order matters: explicit '4 days'/'1 week' win, then date ranges like
    'June 23 to 24' (→ 2), and only a small bare number is trusted as a day
    count — so '23' from a date never becomes a 23-day trip.

    `override`, when given a positive int, short-circuits all of the above:
    an explicit day count from the caller is authoritative and the free-text
    `duration` (which may be stale, missing, or ambiguous) is never even
    inspected. No caller passes one today -- graph.py's date-picker flow
    instead guarantees `duration` itself always ends in a parseable
    "(N days)" suffix (see graph._describe_trip) -- but this stays available
    as a seam for a future caller that has the count without the text.
    """
    if override is not None and override > 0:
        return override
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
