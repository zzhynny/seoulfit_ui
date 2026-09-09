"""meal_slots.py — 미쉐린 서울 restaurant.json을 식사 슬롯 후보로 쓰기 위한
순수 함수 로더/필터. 네트워크 호출 없음(2층 Google 폴백은 planner.py를 통해서만
나감). planner.py의 plan_node/_resolve_locked_meals에 연결되어 있다.

지역 판정은 geo.py의 기존 alias/좌표 로직(infer_area, area_matches_requested)을
그대로 재사용한다 — 새 지역 정의를 만들지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NamedTuple

import geo

_HERE = Path(__file__).resolve().parent
RESTAURANT_PATH = _HERE / "dataset" / "restaurant.json"
CUISINE_FAMILY_PATH = _HERE / "dataset" / "cuisine_family.json"

WEEKDAYS: list[str] = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
]

# (start, end) as "HH:MM" — breakfast is optional per spec, excluded from the
# coverage probe but kept here since filter_candidates/is_open take it generically.
MEAL_SLOTS: dict[str, tuple[str, str]] = {
    "breakfast": ("09:00", "10:00"),
    "lunch": ("11:00", "13:30"),
    "dinner": ("18:00", "20:00"),
}

# 식당 전용 지역 중심점. geo.SEOUL_AREA_CENTERS는 관광지 후보 선택과 Google
# Places 검색 좌표에도 쓰이므로 여기서 옮기면 안 된다 — 대신 이 모듈 안에서만
# 쓰는 별도 딕셔너리를 둔다. 기본은 geo.py 값 그대로, 아래 2곳만 실측 무게중심으로
# 덮어쓴다(area_center_check.py 실행 결과, 나머지 18곳은 R=1.5에서 이미 실패율
# 0%라 손대지 않았다).
MEAL_AREA_CENTERS: dict[str, tuple[float, float]] = {
    **geo.SEOUL_AREA_CENTERS,
    # 정의중심 1.5km내 4곳 -> 무게중심(3km내 43곳) 1.5km내 49곳. 이격 2.11km.
    "seongsu": (37.5280, 127.0445),
    # 정의중심 1.5km내 5곳 -> 무게중심(3km내 42곳) 1.5km내 30곳. 이격 1.57km.
    "gangnam": (37.5117, 127.0312),
}

_missing_areas = set(geo.SEOUL_AREA_CENTERS) - set(MEAL_AREA_CENTERS)
if _missing_areas:
    raise ValueError(f"MEAL_AREA_CENTERS missing areas from geo.SEOUL_AREA_CENTERS: {sorted(_missing_areas)}")


# cuisine_family.json's actual categories (see dataset/cuisine_family.json) --
# kept as a literal tuple rather than derived at import time so a bad/edited
# dataset file can't silently change what this module is allowed to exclude.
_KNOWN_FAMILIES: tuple[str, ...] = (
    "korean", "japanese", "chinese", "western", "contemporary", "asian", "other",
)

# This dataset has no per-restaurant vegetarian/vegan flag -- the only signal
# is `cuisine` literally being "Vegan"/"Vegetarian", and both bucket into
# cuisine_family "other" (see dataset/cuisine_family.json). Excluding every
# OTHER family is the closest fill_meal_slot's exclude_families can get to
# "steer toward a vegetarian pick": it does not guarantee the result actually
# is one -- "other" also holds Thai/Mediterranean/Mexican/etc. -- so this is
# best-effort, not a safety guarantee (see fill_meal_slot's own exclude_reason
# guard: this whole mechanism is scoped to cuisine_avoidance, not allergy).
_VEG_KEYWORDS = ("vegetarian", "vegan", "plant-based", "채식", "비건")


def restrictions_to_excluded_families(restrictions: str | None) -> tuple[str, ...]:
    """Best-effort mapping from the free-text `state["restrictions"]` answer to
    the cuisine_family.json categories fill_meal_slot(exclude_families=...)
    understands. Currently recognizes vegetarian/vegan only -- the concrete
    case this was reported missing for. Unrecognized or empty text returns ()
    (no exclusion), same as before this function existed."""
    text = (restrictions or "").strip().lower()
    if not text or text in {"none", "no", "n/a", "없음"}:
        return ()
    if any(k in text for k in _VEG_KEYWORDS):
        return tuple(f for f in _KNOWN_FAMILIES if f != "other")
    return ()


def _to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _parse_range(range_str: str) -> tuple[int, int] | None:
    """"HH:MM-HH:MM" -> (start_min, end_min). 자정을 넘기면(end<=start) end에
    +1440 해서 다음날로 넘어가는 구간으로 취급한다 (예: "17:30-00:00", "18:00-02:00").

    # ponytail: restaurant.json에 "18:00-10:30"(Fuje, Wed), "12:00-09:00"
    # (Gwanghwamun Gukbap, Sat) 같은 비정상적으로 긴(16~21시간) 구간이 2건 있다.
    # 자정-넘김 규칙을 기계적으로 적용하면 "영업 중"으로 잡히는데, 이건 원본
    # 데이터의 스크래핑 오류로 보인다. restaurant.json은 수정하지 않기로 했으므로
    # 그대로 두되, 이 사실은 커버리지 리포트에 명시한다.
    """
    start_s, end_s = range_str.split("-")
    start = _to_minutes(start_s)
    end = _to_minutes(end_s)
    if end <= start:
        end += 24 * 60
    return start, end


def load_restaurants(
    restaurant_path: Path | str = RESTAURANT_PATH,
    cuisine_family_path: Path | str = CUISINE_FAMILY_PATH,
) -> list[dict[str, Any]]:
    """restaurant.json + cuisine_family.json을 읽어 각 레코드에
    `cuisine_family` (str | None), `needs_review` (bool)를 붙여 반환한다.

    cuisine_family.json에 없는 cuisine 값이 하나라도 있으면 예외를 던진다 —
    조용히 "other"로 넘기지 않는다 (요구사항)."""
    restaurants = json.loads(Path(restaurant_path).read_text(encoding="utf-8"))
    family_map: dict[str, dict[str, Any]] = json.loads(
        Path(cuisine_family_path).read_text(encoding="utf-8")
    )

    unmapped = sorted({r["cuisine"] for r in restaurants if r.get("cuisine")} - set(family_map))
    if unmapped:
        raise ValueError(f"unmapped cuisine values in {cuisine_family_path}: {unmapped}")

    out = []
    for r in restaurants:
        entry = dict(r)
        fam_info = family_map.get(entry.get("cuisine"), {})
        entry["cuisine_family"] = fam_info.get("family")  # None for needs_review
        entry["needs_review"] = bool(fam_info.get("needs_review"))
        out.append(entry)
    return out


def is_open(restaurant: dict[str, Any], weekday: str, slot_start: str, slot_end: str) -> bool:
    """restaurant가 주어진 요일에 [slot_start, slot_end] 구간과 겹치는 영업시간을
    갖는지. opening_hours가 아예 없으면(확인 불가) False — "모르면 통과시키지
    않는다" 원칙."""
    opening_hours = restaurant.get("opening_hours")
    if not opening_hours:
        return False

    day_ranges = opening_hours.get(weekday)
    if not day_ranges:
        return False

    slot_start_min = _to_minutes(slot_start)
    slot_end_min = _to_minutes(slot_end)

    for item in day_ranges:
        if item == "closed":
            continue
        parsed = _parse_range(item)
        if parsed is None:
            continue
        o_start, o_end = parsed
        if max(o_start, slot_start_min) < min(o_end, slot_end_min):
            return True
    return False


def matches_area(restaurant: dict[str, Any], area: str) -> bool:
    """geo.py의 기존 alias/좌표 로직을 그대로 재사용 — street 텍스트(구 이름
    포함) 먼저 시도하고, 매칭 안 되면 좌표로 최근접 지역을 찾는다."""
    inferred = geo.infer_area(
        text=restaurant.get("street") or "",
        lat=restaurant.get("lat"),
        lng=restaurant.get("lon"),
    )
    return geo.area_matches_requested(inferred, area)


DEFAULT_AREA_RADIUS_KM = 1.5


def distance_to_area_km(restaurant: dict[str, Any], area: str) -> float | None:
    """레스토랑 좌표 -> MEAL_AREA_CENTERS[area]까지 haversine 거리(km).
    좌표나 area 중심점이 없으면 None."""
    center = MEAL_AREA_CENTERS.get(area)
    if center is None:
        return None
    try:
        lat = float(restaurant.get("lat"))
        lon = float(restaurant.get("lon"))
    except (TypeError, ValueError):
        return None
    return geo.haversine_km(lat, lon, center[0], center[1])


def matches_area_within_radius(restaurant: dict[str, Any], area: str, radius_km: float) -> bool:
    """matches_area의 대안 — alias/인접목록(geo._ADJACENT_AREAS) 대신 순수 좌표
    거리만 쓴다. 목록 기반 인접성은 방향성이 비대칭(gangnam은 sinsa를 인접으로
    인정하지만 그 역은 아님)이라 지역별 실패율이 지역-좌표 매핑 누락과 진짜
    실패를 구분 못 하게 만든다 — 그 문제를 피하기 위한 함수. geo.py는
    건드리지 않고 meal_slots.py 안에서만 쓴다."""
    dist = distance_to_area_km(restaurant, area)
    return dist is not None and dist <= radius_km


class FilterResult(NamedTuple):
    candidates: list[dict[str, Any]]
    step_counts: dict[str, int]


def filter_candidates(
    restaurants: list[dict[str, Any]],
    *,
    area: str,
    weekday: str,
    slot_start: str,
    slot_end: str,
    exclude_families: tuple[str, ...] = (),
    exclude_names: tuple[str, ...] = (),
    area_radius_km: float | None = DEFAULT_AREA_RADIUS_KM,
) -> FilterResult:
    """지역 -> 영업시간 -> family 제외 -> 이름 제외 순서로 적용.

    기본 경로는 area_radius_km(기본 1.5km) 기반 matches_area_within_radius —
    MEAL_AREA_CENTERS 좌표에서 반경 안이면 후보. area_radius_km=None을 명시하면
    옛 alias/인접목록 기반 matches_area로 폴백한다(하위호환용).

    needs_review(family 미확정) 레스토랑은, family 제외 조건이 하나라도 걸려
    있을 때만 후보에서 뺀다 — 실제 family를 모르니 회피 대상인지 보장할 수
    없기 때문. 제약이 없는 조회(exclude_families=())에서는 그대로 남는다."""
    step_counts: dict[str, int] = {"initial": len(restaurants)}

    if area_radius_km is not None:
        candidates = [r for r in restaurants if matches_area_within_radius(r, area, area_radius_km)]
    else:
        candidates = [r for r in restaurants if matches_area(r, area)]
    step_counts["after_area"] = len(candidates)

    candidates = [r for r in candidates if is_open(r, weekday, slot_start, slot_end)]
    step_counts["after_open"] = len(candidates)

    if exclude_families:
        candidates = [
            r for r in candidates
            if r.get("cuisine_family") not in exclude_families and not r.get("needs_review")
        ]
    step_counts["after_family_exclude"] = len(candidates)

    if exclude_names:
        candidates = [r for r in candidates if r.get("name") not in exclude_names]
    step_counts["after_name_exclude"] = len(candidates)

    return FilterResult(candidates=candidates, step_counts=step_counts)


# ──────────────────────────────────────────
# 2층 (Google Places) 폴백
# ──────────────────────────────────────────
_MICHELIN_GRADE_RANK: dict[str, int] = {
    "3스타": 0,
    "2스타": 1,
    "1스타": 2,
    "빕구르망": 3,
    "Selected": 4,
}

# (area, place_type) -> fetch_nearby_places 결과. 같은 여행 계획 안에서 같은
# 지역을 여러 슬롯이 조회하는 게 흔해서, 모듈 레벨에 둬 중복 API 호출을 막는다.
_GOOGLE_PLACES_CACHE: dict[tuple[str, str], list[dict[str, Any]]] = {}


def _fetch_google_restaurants_raw(area: str) -> list[dict[str, Any]]:
    """실제 네트워크 호출 지점 — 테스트는 이 함수만 스텁으로 바꾸면 된다.
    planner.py를 지연 import한다: planner는 dspy/rag(FAISS)까지 끌고 오는
    무거운 의존성이라, 2층을 실제로 쓸 때만(즉 1층이 비었을 때만) 문다."""
    import planner

    return planner.fetch_nearby_places(
        area=area,
        place_type="restaurant",
        api_key=planner.GOOGLE_PLACES_API_KEY,
    )


def _fetch_google_restaurants_cached(area: str) -> list[dict[str, Any]]:
    cache_key = (area, "restaurant")
    if cache_key in _GOOGLE_PLACES_CACHE:
        return _GOOGLE_PLACES_CACHE[cache_key]

    try:
        results = _fetch_google_restaurants_raw(area)
    except Exception as e:
        # 조용히 삼키지 않는다 — 무슨 예외였는지 로그로 남기고 빈 결과로 3층에 넘긴다.
        print(f"[meal_slots] Google Places fallback failed for area={area!r}: {type(e).__name__}: {e}")
        results = []

    _GOOGLE_PLACES_CACHE[cache_key] = results
    return results


def _slot_name_for(slot_start: str, slot_end: str) -> str | None:
    for name, (s, e) in MEAL_SLOTS.items():
        if s == slot_start and e == slot_end:
            return name
    return None


def _unfilled(slot_start: str, slot_end: str, reason: str) -> dict[str, Any]:
    return {
        "name": None,
        "lat": None,
        "lng": None,
        "address": None,
        "meal_slot": _slot_name_for(slot_start, slot_end),
        "slot_time": f"{slot_start}-{slot_end}",
        "source_tier": None,
        "verified": {"opening_hours": False, "cuisine": False},
        "status": "unfilled",
        "reason": reason,
    }


def fill_meal_slot(
    *,
    area: str,
    weekday: str,
    slot_start: str,
    slot_end: str,
    exclude_families: tuple[str, ...] = (),
    exclude_names: tuple[str, ...] = (),
    exclude_reason: str = "cuisine_avoidance",
    allow_google: bool = True,
    restaurants: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """식사 슬롯 하나를 1층(미쉐린) -> 2층(Google Places) -> 3층(unfilled) 순으로 채운다.

    exclude_reason: exclude_families가 무슨 종류의 제약인지 구분해두는 자리다.
    2층(Google)은 cuisine 정보가 아예 없어서 "검증은 못 했지만 후보는 반환한다"는
    판단이 성립하는 건 요리 회피 한정이다(밥을 아예 못 먹는 것보다 낫다는 논리).
    나중에 알레르기 같은 안전 관련 제약이 추가되면 이 관대한 처리를 그대로 쓰면
    안 되므로, 아직 구현하지 않은 reason 값은 추측으로 관대하게 처리하지 않고
    명시적으로 막는다.
    """
    if exclude_families and exclude_reason != "cuisine_avoidance":
        raise NotImplementedError(
            f"fill_meal_slot only implements exclude_reason='cuisine_avoidance' so far, got {exclude_reason!r}"
        )

    if restaurants is None:
        restaurants = load_restaurants()

    slot_name = _slot_name_for(slot_start, slot_end)
    slot_time = f"{slot_start}-{slot_end}"

    # 1층 — 미쉐린
    tier1 = filter_candidates(
        restaurants,
        area=area,
        weekday=weekday,
        slot_start=slot_start,
        slot_end=slot_end,
        exclude_families=exclude_families,
        exclude_names=exclude_names,
    )
    if tier1.candidates:
        best = min(
            tier1.candidates,
            key=lambda r: (_MICHELIN_GRADE_RANK.get(r.get("grade"), 99), r.get("name") or ""),
        )
        return {
            "name": best.get("name"),
            "type": "restaurant",
            "lat": best.get("lat"),
            "lng": best.get("lon"),
            "address": best.get("street"),
            "meal_slot": slot_name,
            "slot_time": slot_time,
            "source_tier": "michelin",
            "verified": {
                # 하드코딩 아님 — 실제 필드 유무에서 계산. Places API (New)로
                # 넘어가서 opening_hours/cuisine을 채워주기 시작하면, 이 두 줄은
                # 안 고쳐도 그 즉시 True가 나온다(2층 쪽 조건).
                "opening_hours": bool(best.get("opening_hours")),
                "cuisine": best.get("cuisine_family") is not None,
            },
            "status": "filled",
        }

    # 2층 — Google Places
    if not allow_google:
        return _unfilled(
            slot_start, slot_end,
            f"no michelin candidates in {area} ({weekday} {slot_time}); google fallback disabled",
        )

    google_results = _fetch_google_restaurants_cached(area)
    if exclude_names:
        google_results = [g for g in google_results if g.get("poi_name") not in exclude_names]

    if google_results:
        best_google = max(google_results, key=lambda g: g.get("rating") or 0)
        return {
            "name": best_google.get("poi_name"),
            "type": "restaurant",
            "lat": best_google.get("lat"),
            "lng": best_google.get("lng"),
            "address": best_google.get("address_en"),
            "meal_slot": slot_name,
            "slot_time": slot_time,
            "source_tier": "google",
            # Legacy Places API 응답엔 opening_hours도 cuisine도 없다 — 하드코딩이
            # 아니라 "이 tier에 애초에 그 데이터가 없다"는 사실을 그대로 반영한
            # False다. exclude_families가 걸려 있어도 후보 자체는 그대로 반환한다
            # (밥을 못 먹는 것보다 검증 안 된 후보가 낫다는 게 요구사항) — 다만
            # verified.cuisine=False로 남아있으니 상위 레이어가 이 사실을 안다.
            "verified": {"opening_hours": False, "cuisine": False},
            "status": "filled",
        }

    # 3층 — 둘 다 빔
    return _unfilled(
        slot_start, slot_end,
        f"no michelin candidates in {area} ({weekday} {slot_time}) and "
        "google places returned no results (missing api key, zero results, or request failure)",
    )
