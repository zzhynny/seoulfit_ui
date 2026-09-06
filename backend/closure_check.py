"""
closure_check.py — Final Route 단계: 확정된 POI들이 실제 방문일에 "임시" 휴관인지
(공지된 리모델링/행사/특별 휴관 등, 정기 요일 휴무가 아닌 것) Google Search
grounding으로 확인한다.

역할 분리: 매주 정기적으로 쉬는 요일(예: "화요일마다 휴무")은 이제 이 모듈의
책임이 아니다 — course_data의 opening_hours.closed_weekday 필드(Google Places
Legacy Place Details에서 구조화된 필드로 가져옴, scripts/google_places_closed_weekday_fill.py
참고)로 직접 조회한다. LLM 웹서칭보다 훨씬 신뢰도가 높고(실측: Places 구조화
조회 151/192 성공 vs 이 모듈의 grounding 인용 첨부율 12.5%) 비용도 훨씬 싸다.
이 모듈은 "이번 주만/이 기간만 특별히 닫는" 임시 휴관처럼 구조화된 API로 잡히지
않는 좁은 케이스만 담당한다.

llm.py(DSPy)는 건드리지 않는다 — DSPy는 raw API 파라미터(특히 grounding tool)를
추상화해버려서 Search grounding을 켤 수 없다. 이 모듈은 lens.py와 같은 방식으로
`google.genai` SDK를 직접 사용한다.

핵심 제약: Gemini API는 Search grounding tool과 강제 JSON 응답 모드
(response_mime_type="application/json")를 동시에 켤 수 없다. 그래서 grounding
호출은 자유 텍스트로 받고, 파싱/검증 레이어가 스키마를 강제한다 (아래
`_parse_and_validate_batch`).

설계 원칙 (전부 요구사항에서 옴):
  - 명확한 근거가 없으면 무조건 unknown. confirmed_* 인데 실제 검색 근거
    (grounding chunk)가 없으면 강제로 unknown으로 덮어쓴다.
  - API 실패/타임아웃/파싱 실패는 절대 예외를 던지지 않고 unknown으로 대체한다.
    이 모듈의 실패가 일정 생성 자체를 막아서는 안 된다.
  - POI+날짜 키로 24~48h 캐싱(확정 결과는 36h, unknown은 6h — 몇 시간 뒤
    재검색하면 답이 바뀔 수 있는 건 unknown 쪽이라 TTL을 짧게 둔다).
    캐시는 인메모리 dict + JSON 파일 스냅샷(프로세스 재시작에도 유지).

Run (no live network — self-check only): python test_closure_check.py
"""

from __future__ import annotations

import atexit
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_HERE, ".env"))

_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
_GEMINI_MODEL = "gemini-2.5-flash"

# ──────────────────────────────────────────
# 튜닝 파라미터
# ──────────────────────────────────────────
BATCH_SIZE = 4                       # 3~5개 권장 범위의 중간값
# 배치 1건당 하드 타임아웃. 실측: 4개짜리 grounding 배치 호출이 ~12.5초 걸림
# (항목마다 1~4개의 웹 검색을 순차로 태우는 것으로 보임) — 12초로 뒀다가 매번
# 타임아웃에 걸려 전부 unknown으로 떨어지는 걸 실측 후 발견해서 여유를 크게 둠.
CALL_TIMEOUT_SECONDS = 30.0
CACHE_TTL_CONFIRMED = 36 * 3600      # confirmed_closed / confirmed_open
CACHE_TTL_UNKNOWN = 6 * 3600         # unknown — 몇 시간 뒤 재검색하면 바뀔 수 있음
CACHE_PATH = Path(_HERE) / "_closure_cache.json"

_STATUSES = {"confirmed_closed", "confirmed_open", "unknown"}

_gemini_client = None  # lazy singleton, api key 없으면 만들지 않음


def _get_client():
    """lens.py와 동일한 패턴의 지연 초기화 싱글턴. 키가 없으면 예외를 던져서
    호출부(check_batch)가 그대로 unknown 폴백으로 흡수하게 한다."""
    global _gemini_client
    if _gemini_client is None:
        if not _GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set")
        from google import genai as _genai

        _gemini_client = _genai.Client(api_key=_GEMINI_API_KEY)
    return _gemini_client


# ──────────────────────────────────────────
# 캐시 — 인메모리 + JSON 스냅샷
# ──────────────────────────────────────────
# key -> (expires_at_epoch, result_dict)
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _normalize_text(s: str) -> str:
    return re.sub(r"[\W_]+", "", (s or "").lower(), flags=re.UNICODE)


def _cache_key(poi_name: str, address: str, visit_date: str) -> str:
    return f"{_normalize_text(poi_name)}|{_normalize_text(address)}|{(visit_date or '').strip()}"


def _load_cache_from_disk() -> None:
    global _CACHE
    try:
        raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        _CACHE = {k: (float(v[0]), v[1]) for k, v in raw.items()}
    except Exception:
        # 파일 없음/손상 — 조용히 빈 캐시로 시작. 캐시 로드 실패가 기능을
        # 막아선 안 된다.
        _CACHE = {}


def _flush_cache_to_disk() -> None:
    try:
        tmp = CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(_CACHE, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(CACHE_PATH)  # atomic rename — 쓰는 도중 죽어도 파일이 안 깨짐
    except Exception:
        pass  # 캐시 저장 실패는 무시 — 다음 요청은 그냥 캐시 미스로 처리됨


_load_cache_from_disk()
atexit.register(_flush_cache_to_disk)


def _cache_get(key: str) -> dict[str, Any] | None:
    entry = _CACHE.get(key)
    if not entry:
        return None
    expires_at, result = entry
    if time.time() >= expires_at:
        _CACHE.pop(key, None)
        return None
    return dict(result)


def _cache_put(key: str, result: dict[str, Any]) -> None:
    ttl = CACHE_TTL_CONFIRMED if result.get("status") != "unknown" else CACHE_TTL_UNKNOWN
    _CACHE[key] = (time.time() + ttl, dict(result))


# ──────────────────────────────────────────
# 결과 팩토리
# ──────────────────────────────────────────
def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _unknown_result(poi_name: str, visit_date: str) -> dict[str, Any]:
    return {
        "poi_name": poi_name,
        "visit_date": visit_date,
        "status": "unknown",
        "source_url": None,
        "source_note": "",
        "checked_at": _utc_now_iso(),
    }


# ──────────────────────────────────────────
# 프롬프트
# ──────────────────────────────────────────
_BATCH_PROMPT_TEMPLATE = """You are a strict fact-checking assistant. For EACH numbered place below, \
search to determine whether it has a CONFIRMED *temporary* closure (e.g. a one-off renovation, \
special event, or announced exception), or is CONFIRMED open as usual, on the given specific date.

Do NOT reason about the place's regular/recurring weekly closure day (e.g. "closed every Tuesday") — \
that is looked up separately from a structured source and is out of scope here. Only answer based on \
something specific to THIS date that would not already be captured by a fixed weekly schedule.

{rows}

Rules — follow exactly, no exceptions:
- If you cannot find a clear, direct source that confirms a temporary closure or an explicit exception \
to normal operation on that SPECIFIC date (or a date range that includes it), you MUST answer "unknown" \
for that item. Do NOT guess from typical opening-hour patterns, general reputation, or the place being \
famous.
- Treat each item independently. One item lacking evidence must not change another item's answer.
- Do not fabricate a source. If you did not actually find one, say unknown.
- Do NOT include citation markers, footnotes, or bracketed references of any kind (no "[1]", no \
"[cite: ...]", nothing like that) anywhere in your output. The source_note must be plain prose only.
- Keep each source_note to one short sentence (under 20 words). Do not explain your search process.

Output format — STRICT, nothing else before/after/between these lines, one per item, in order:
###ITEM<N>### {{"status": "confirmed_closed" | "confirmed_open" | "unknown", "source_note": "<one \
short sentence, empty string if unknown, no citation markers>"}}
"""


def _build_prompt(items: list[tuple[str, str, str]]) -> str:
    rows = "\n".join(
        f"{i + 1}. {name} | {address} | {visit_date}"
        for i, (name, address, visit_date) in enumerate(items)
    )
    return _BATCH_PROMPT_TEMPLATE.format(rows=rows)


# ──────────────────────────────────────────
# Gemini 호출 (grounding ON, JSON 모드 OFF — 동시 사용 불가)
# ──────────────────────────────────────────
def _grounded_lookup_batch_raw(items: list[tuple[str, str, str]]):
    """단일 배치 호출. 실패 시 예외를 그대로 던진다 — 호출부가 흡수."""
    from google.genai import types as _types

    client = _get_client()
    prompt = _build_prompt(items)
    return client.models.generate_content(
        model=_GEMINI_MODEL,
        contents=[prompt],
        config=_types.GenerateContentConfig(
            tools=[_types.Tool(google_search=_types.GoogleSearch())],
            temperature=0,
            # 1024로 뒀다가 grounding 시 모델이 [cite: ...] 스타일 각주를 붙이려다
            # 토큰이 모자라 중간에 끊기고 출력이 깨지는 걸 실측으로 확인 → 여유 확보.
            max_output_tokens=2048,
        ),
    )


def _call_with_timeout(items: list[tuple[str, str, str]], timeout: float):
    """ThreadPoolExecutor로 하드 타임아웃을 강제한다 (SDK 자체 timeout에 기대지 않음)."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_grounded_lookup_batch_raw, items)
        return future.result(timeout=timeout)


def _extract_chunks_safe(response: Any) -> list[Any]:
    try:
        return response.candidates[0].grounding_metadata.grounding_chunks or []
    except Exception:
        return []


MAX_EMPTY_GROUNDING_RETRIES = 1


def _call_with_retry_on_empty_grounding(items: list[tuple[str, str, str]], timeout: float):
    """API 자체의 불안정성 완화용 재시도 — 검증 기준(enum 체크, 근거 URL 필수)은
    전혀 건드리지 않는다.

    관찰된 현상: Gemini가 web_search_queries에는 검색을 했다고 남기면서도
    grounding_chunks를 통째로 빈 채 반환하는 경우가 있다(같은 질의를 다시
    던지면 붙어 오기도 함) — 이건 "근거가 실제로 없음"과는 다른, API 쪽
    메타데이터 첨부 자체의 flakiness다. grounding_chunks가 비어 있을 때만
    동일 쿼리로 딱 1회 재시도하고, 그래도 비어 있으면 그대로 진행한다
    (그 경우 이후 검증 단계가 정상적으로 unknown 처리함 — 완화는 여기까지,
    검증 강도는 절대 낮추지 않음)."""
    response = _call_with_timeout(items, timeout)
    if _extract_chunks_safe(response):
        return response  # 이미 근거가 붙어 있음 — 재시도 불필요

    for _ in range(MAX_EMPTY_GROUNDING_RETRIES):
        try:
            retry_response = _call_with_timeout(items, timeout)
        except Exception:
            break  # 재시도 자체가 실패 — 원래 응답으로 계속 (정상 검증 절차가 unknown 처리)
        response = retry_response
        if _extract_chunks_safe(response):
            break  # 재시도에서 근거가 붙어 옴 — 더 재시도할 필요 없음

    return response


# ──────────────────────────────────────────
# 파싱 + 검증 레이어
# ──────────────────────────────────────────
_ITEM_RE = re.compile(
    r"###ITEM(\d+)###\s*(\{.*?\})(?=\s*###ITEM\d+###|\s*$)",
    re.DOTALL,
)


def _extract_item_spans(raw_text: str) -> dict[int, tuple[int, int, dict[str, Any]]]:
    """###ITEM<N>### 마커로 각 항목의 (본문 시작 인덱스, 끝 인덱스, 파싱된 JSON)을 찾는다.
    JSON이 깨져 있으면 그 항목만 건너뛴다 (다른 항목에 영향 없음)."""
    spans: dict[int, tuple[int, int, dict[str, Any]]] = {}
    for m in _ITEM_RE.finditer(raw_text):
        idx = int(m.group(1))
        body = m.group(2)
        try:
            obj = json.loads(body)
        except Exception:
            continue
        start, end = m.span(2)
        spans[idx] = (start, end, obj)
    return spans


def _grounding_url_for_span(
    start: int, end: int, supports: list[Any], chunks: list[Any]
) -> str | None:
    """이 텍스트 구간(start, end)에 실제로 grounding 근거가 붙어 있는지 확인하고,
    있으면 그 근거의 URL을 반환한다. 없으면 None (호출부가 unknown으로 강등)."""
    for support in supports or []:
        segment = getattr(support, "segment", None)
        if segment is None:
            continue
        # Gemini omits start_index (leaves it None) when a segment starts at
        # position 0 — it does NOT mean "no position info". Only end_index
        # missing means we truly can't place this segment.
        seg_start = getattr(segment, "start_index", None) or 0
        seg_end = getattr(segment, "end_index", None)
        if seg_end is None:
            continue
        # 두 구간이 겹치는지 (완전 포함을 요구하지 않음 — 모델이 조금씩
        # 어긋나게 잘라도 겹치기만 하면 근거로 인정)
        overlaps = seg_start < end and start < seg_end
        if not overlaps:
            continue
        chunk_indices = getattr(support, "grounding_chunk_indices", None) or []
        for ci in chunk_indices:
            if ci is None or ci >= len(chunks):
                continue
            web = getattr(chunks[ci], "web", None)
            uri = getattr(web, "uri", None) if web else None
            if uri:
                return uri
    return None


def _parse_and_validate_batch(
    response: Any, items: list[tuple[str, str, str]]
) -> list[dict[str, Any]]:
    raw_text = getattr(response, "text", None) or ""

    supports: list[Any] = []
    chunks: list[Any] = []
    try:
        gm = response.candidates[0].grounding_metadata
        supports = gm.grounding_supports or []
        chunks = gm.grounding_chunks or []
    except Exception:
        # grounding_metadata가 아예 없음 (예: 이번 응답에서 검색을 안 함)
        # -> 이 배치 전체가 근거 없이 답한 것 -> 전부 unknown 처리 대상
        pass

    spans = _extract_item_spans(raw_text)

    results: list[dict[str, Any]] = []
    for i, (name, _address, visit_date) in enumerate(items, start=1):
        entry = spans.get(i)
        if entry is None:
            results.append(_unknown_result(name, visit_date))
            continue

        start, end, obj = entry
        status = obj.get("status")
        note = str(obj.get("source_note") or "")

        if status not in _STATUSES:
            status = "unknown"

        source_url = None
        if status != "unknown":
            source_url = _grounding_url_for_span(start, end, supports, chunks)
            if not source_url:
                # confirmed_* 라고 했지만 실제 검색 근거가 이 구간에 안 붙어 있음
                # -> 강제로 unknown 강등 (핵심 검증 규칙)
                status = "unknown"
                note = ""

        results.append(
            {
                "poi_name": name,
                "visit_date": visit_date,
                "status": status,
                "source_url": source_url,
                "source_note": note if status != "unknown" else "",
                "checked_at": _utc_now_iso(),
            }
        )
    return results


# ──────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────
def _chunked(seq: list[Any], size: int) -> list[list[Any]]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def check_batch(
    items: list[tuple[str, str, str]],
    *,
    batch_size: int = BATCH_SIZE,
    timeout: float = CALL_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """(poi_name, address, visit_date) 리스트를 받아 POI-날짜별 폐업 확인 결과를 반환한다.

    - 캐시 히트는 API를 호출하지 않는다.
    - 캐시 미스만 batch_size 단위로 묶어 grounding 호출.
    - 어떤 단계든 실패하면 그 항목(들)은 unknown으로 대체될 뿐, 예외를 던지지 않는다.
    - 입력 순서를 그대로 유지해서 반환한다.
    """
    results_by_index: dict[int, dict[str, Any]] = {}
    misses: list[tuple[int, tuple[str, str, str]]] = []

    for i, item in enumerate(items):
        name, address, visit_date = item
        key = _cache_key(name, address, visit_date)
        cached = _cache_get(key)
        if cached is not None:
            results_by_index[i] = cached
        else:
            misses.append((i, item))

    for chunk in _chunked(misses, batch_size):
        chunk_items = [it for _, it in chunk]
        try:
            response = _call_with_retry_on_empty_grounding(chunk_items, timeout)
            chunk_results = _parse_and_validate_batch(response, chunk_items)
        except (FutureTimeoutError, Exception):
            # API 실패/타임아웃/파싱 붕괴 — 이 배치 전체를 unknown으로 폴백.
            # 일정 생성/응답 자체를 막지 않는 게 최우선.
            chunk_results = [_unknown_result(name, date) for name, _addr, date in chunk_items]

        for (orig_idx, (name, address, visit_date)), result in zip(chunk, chunk_results):
            results_by_index[orig_idx] = result
            _cache_put(_cache_key(name, address, visit_date), result)

    return [results_by_index[i] for i in range(len(items))]


if __name__ == "__main__":
    # 가벼운 수동 점검 (실제 네트워크 호출) — 자동 self-check는 test_closure_check.py.
    if not _GEMINI_API_KEY:
        print("GEMINI_API_KEY not set — skipping live smoke test.")
    else:
        demo = [
            ("Gyeongbokgung Palace", "161 Sajik-ro, Jongno-gu, Seoul", "2026-09-01"),
        ]
        print(json.dumps(check_batch(demo), ensure_ascii=False, indent=2))
