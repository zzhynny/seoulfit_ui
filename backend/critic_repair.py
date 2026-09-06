"""Critic-Repair node for SeoulMate LangGraph.

This module evaluates and repairs generated itineraries.

Main checks:
1. Requested area coverage: e.g. Hongdae + Seongsu must both appear.
2. Per-day POI count: each day should have at least 5 POIs.
3. Meal slot: each day should include cafe/restaurant/market.
4. Duplicate POIs.
5. Basic geographic coherence.
6. Basic foreigner readiness from available labels if present.

The node is intentionally robust:
- It does not crash on NaN.
- It works even if enriched fields are missing.
- It can repair using planning_context["google_supplement"] and retrieved_courses.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage

try:
    from state import TravelState
except Exception:
    TravelState = dict

from planner import compute_transit_legs


# ---------------------------------------------------------------------------
# Area configuration
# ---------------------------------------------------------------------------

SEOUL_AREA_CENTERS: dict[str, tuple[float, float]] = {
    "hongdae": (37.5563, 126.9227),
    "hapjeong": (37.5499, 126.9143),
    "mangwon": (37.5530, 126.9028),
    "yeonnam": (37.5663, 126.9236),
    "seongsu": (37.5447, 127.0558),
    "wangsimni": (37.5612, 127.0371),
    "gangnam": (37.4979, 127.0276),
    "sinsa": (37.5196, 127.0228),
    "garosu-gil": (37.5207, 127.0227),
    "jongno": (37.5729, 126.9794),
    "insadong": (37.5741, 126.9861),
    "myeongdong": (37.5636, 126.9857),
    "itaewon": (37.5347, 126.9946),
    "sinchon": (37.5596, 126.9373),
    "dongdaemun": (37.5666, 127.0097),
    "yeouido": (37.5217, 126.9244),
    "mapo": (37.5479, 126.9130),
    "jamsil": (37.5133, 127.1028),
    "dmc": (37.5770, 126.8902),
}

AREA_ALIASES: dict[str, list[str]] = {
    "hongdae": ["hongdae", "hongik", "hongik univ", "홍대", "hongik university"],
    "hapjeong": ["hapjeong", "합정"],
    "mangwon": ["mangwon", "망원"],
    "yeonnam": ["yeonnam", "연남"],
    "seongsu": ["seongsu", "성수", "seongsu-dong", "성수동"],
    "wangsimni": ["wangsimni", "왕십리"],
    "gangnam": ["gangnam", "강남"],
    "sinsa": ["sinsa", "신사"],
    "garosu-gil": ["garosu", "garosu-gil", "가로수길"],
    "jongno": ["jongno", "종로"],
    "insadong": ["insadong", "인사동"],
    "myeongdong": ["myeongdong", "명동"],
    "itaewon": ["itaewon", "이태원"],
    "sinchon": ["sinchon", "신촌"],
    "dongdaemun": ["dongdaemun", "동대문"],
    "yeouido": ["yeouido", "여의도"],
    "mapo": ["mapo", "마포"],
    "jamsil": ["jamsil", "잠실"],
    "dmc": ["digital media city", "dmc", "상암", "디지털미디어시티"],
}


# ---------------------------------------------------------------------------
# Safe utilities
# ---------------------------------------------------------------------------

def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def safe_str(value: Any, default: str = "") -> str:
    try:
        if value is None:
            return default
        if isinstance(value, float) and math.isnan(value):
            return default
        text = str(value)
        if text.lower() in {"nan", "none", "null", ""}:
            return default
        return text
    except Exception:
        return default


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        if isinstance(value, float) and math.isnan(value):
            return default
        text = str(value).strip()
        if text.lower() in {"nan", "none", "null", ""}:
            return default
        return float(text)
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        if isinstance(value, float) and math.isnan(value):
            return default
        text = str(value).strip()
        if text.lower() in {"nan", "none", "null", ""}:
            return default
        return int(float(text))
    except Exception:
        return default


def area_label(area: str | None) -> str:
    if not area:
        return "Unknown"
    labels = {
        "hongdae": "Hongdae",
        "hapjeong": "Hapjeong",
        "mangwon": "Mangwon",
        "yeonnam": "Yeonnam",
        "seongsu": "Seongsu",
        "wangsimni": "Wangsimni",
        "gangnam": "Gangnam",
        "sinsa": "Sinsa",
        "garosu-gil": "Garosu-gil",
        "jongno": "Jongno",
        "insadong": "Insadong",
        "myeongdong": "Myeongdong",
        "itaewon": "Itaewon",
        "sinchon": "Sinchon",
        "dongdaemun": "Dongdaemun",
        "yeouido": "Yeouido",
        "mapo": "Mapo",
        "jamsil": "Jamsil",
        "dmc": "Digital Media City",
    }
    return labels.get(area, area.title())


def extract_requested_areas(location: str | None, purpose: str | None = None) -> list[str]:
    text = f"{location or ''} {purpose or ''}".lower()
    found: list[str] = []

    for area, aliases in AREA_ALIASES.items():
        if any(alias.lower() in text for alias in aliases):
            if area not in found:
                found.append(area)

    return found


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(d_lam / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def infer_area_from_poi(poi: dict[str, Any]) -> str | None:
    if poi.get("area"):
        area = normalize_text(poi.get("area"))
        if area in SEOUL_AREA_CENTERS:
            return area

    text = f"{poi.get('name', '')} {poi.get('address', '')} {poi.get('poi_name', '')} {poi.get('address_en', '')} {poi.get('address_ko', '')}".lower()

    for area, aliases in AREA_ALIASES.items():
        if area in text or any(alias.lower() in text for alias in aliases):
            return area

    lat = safe_float(poi.get("lat"))
    lng = safe_float(poi.get("lng"))
    if lat is None or lng is None:
        return None

    nearest_area = None
    nearest_dist = 9999.0

    for area, (center_lat, center_lng) in SEOUL_AREA_CENTERS.items():
        dist = haversine_km(lat, lng, center_lat, center_lng)
        if dist < nearest_dist:
            nearest_area = area
            nearest_dist = dist

    if nearest_dist <= 3.2:
        return nearest_area

    return None


def area_matches_requested(area: str | None, requested: str) -> bool:
    if not area:
        return False

    area = normalize_text(area)
    requested = normalize_text(requested)

    if area == requested:
        return True

    adjacent = {
        "hongdae": {"hongdae", "hapjeong", "mangwon", "yeonnam", "mapo"},
        "seongsu": {"seongsu", "wangsimni"},
        "gangnam": {"gangnam", "sinsa", "garosu-gil"},
        "jongno": {"jongno", "insadong", "myeongdong"},
    }

    return area in adjacent.get(requested, {requested})


def belongs_to_other_requested_area(
    poi_area: str | None,
    target_area: str | None,
    requested_areas: list[str],
) -> bool:
    """True if the POI clearly belongs to a requested area other than the day's.

    Keeps the global fallback fillers from dragging another requested area's POIs
    (e.g. Gangnam) into a day that should stay focused on its own area.
    """
    if not poi_area:
        return False
    for area in requested_areas:
        if area == target_area:
            continue
        if area_matches_requested(poi_area, area):
            return True
    return False


def is_meal_poi(poi: dict[str, Any]) -> bool:
    ptype = normalize_text(poi.get("type") or poi.get("poi_type"))
    name = normalize_text(poi.get("name") or poi.get("poi_name"))
    if poi.get("is_area_type"):
        # 특정 업체가 아니라 거리/구역을 가리키는 POI는 "식사 슬롯 있음"으로
        # 카운트하지 않는다 (예: "이태원 세계음식거리" 자체는 예약 가능한 식당이 아님).
        return False
    return (
        ptype in {"restaurant", "cafe", "market", "food", "meal_takeaway"}
        or "restaurant" in ptype
        or "cafe" in ptype
        or "coffee" in name
        or "market" in ptype
    )


def poi_name(poi: dict[str, Any]) -> str:
    return safe_str(poi.get("name") or poi.get("poi_name"))


# ---------------------------------------------------------------------------
# Candidate pool
# ---------------------------------------------------------------------------

def candidate_from_course_poi(raw: dict[str, Any]) -> dict[str, Any]:
    name = raw.get("poi_name") or raw.get("name") or ""
    ptype = raw.get("poi_type") or raw.get("type") or "tourist_spot"
    address = raw.get("address_en") or raw.get("address_ko") or raw.get("address") or ""
    lat = raw.get("lat")
    lng = raw.get("lng")
    opening_hours = raw.get("opening_hours")

    item = {
        "name": name,
        "type": ptype,
        "address": address,
        "lat": lat,
        "lng": lng,
        "stay_minutes": safe_int(raw.get("estimated_stay_time") or raw.get("stay_minutes"), 60),
        "notes": "",
        "area": raw.get("area"),
        "source_kind": "course",
        "is_area_type": bool(raw.get("is_area_type")),
        "is_generic_activity": bool(raw.get("is_generic_activity")),
        # 코스 시퀀스의 첫/마지막 자리에 오는 순수 지하철역명 POI(예: "Anguk
        # Station") — 방문지가 아니라 이동 마커일 뿐이라 is_generic_activity와
        # 같은 방식으로 후보 풀에서 제외한다.
        "is_transit_marker": bool(raw.get("is_transit_marker")),
        "rating": raw.get("rating"),
        "opening_hours": opening_hours,
        # course_data_v6: Google Places Legacy Place Details로 얻은 정기 휴무
        # 요일 리스트(예: ["Tuesday"]), 데이터 없으면 None. opening_hours 안에
        # 중첩되어 있지만 Critic 규칙(CLOSED_ON_ASSIGNED_DAY 등)에서 바로 쓰기
        # 편하도록 is_area_type과 같은 방식으로 최상위 필드로도 꺼내둔다.
        "closed_weekday": (opening_hours or {}).get("closed_weekday"),
    }
    item["area"] = item["area"] or infer_area_from_poi(item)
    return item


def candidate_from_google(raw: dict[str, Any]) -> dict[str, Any]:
    name = raw.get("poi_name") or raw.get("name") or ""
    ptype = raw.get("poi_type") or raw.get("type") or "tourist_spot"
    address = raw.get("address_en") or raw.get("address_ko") or raw.get("address") or ""
    lat = raw.get("lat")
    lng = raw.get("lng")

    item = {
        "name": name,
        "type": ptype,
        "address": address,
        "lat": lat,
        "lng": lng,
        "stay_minutes": safe_int(raw.get("estimated_stay_time") or raw.get("stay_minutes"), 60),
        "notes": google_note(raw),
        "area": raw.get("area"),
        "source_kind": "google",
        "rating": raw.get("rating"),
    }
    item["area"] = item["area"] or infer_area_from_poi(item)
    return item


def google_note(raw: dict[str, Any]) -> str:
    ptype = normalize_text(raw.get("poi_type") or raw.get("type"))
    area = area_label(raw.get("area"))
    rating = raw.get("rating")
    rating_text = f" Google rating: {rating}." if rating else ""

    if ptype == "cafe":
        return f"Verified cafe in {area}; useful for cafe hopping and a relaxed break.{rating_text}"
    if ptype == "restaurant":
        return f"Verified restaurant in {area}; added to make the day executable with a clear meal slot.{rating_text}"
    if ptype == "kpop_landmark":
        return f"Verified K-POP related place in or near {area}; fits Hallyu and idol interests.{rating_text}"
    if ptype in {"shopping", "shopping_mall"}:
        return f"Verified shopping spot in {area}; fits shopping and trend exploration.{rating_text}"

    return f"Verified place in {area}.{rating_text}"


def build_candidate_pool(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    pool: dict[str, dict[str, Any]] = {}

    for course in state.get("retrieved_courses") or []:
        for raw in course.get("sequence", []) or []:
            item = candidate_from_course_poi(raw)
            if item.get("is_generic_activity"):
                # 활동 카테고리 라벨(예: "Karaoke", "Jjimjilbang")일 뿐 특정 업체가
                # 아닌 POI는 후보 풀에서 제외한다 — 예약/방문 가능한 장소로 착각해
                # 일정에 꽂히는 것을 막기 위함.
                continue
            if item.get("is_transit_marker"):
                # 코스 시작/끝에 찍힌 순수 지하철역명(예: "Anguk Station") — 방문
                # 목적지가 아니라 이동 마커일 뿐이라 같은 이유로 제외한다.
                continue
            key = normalize_text(item.get("name"))
            if key:
                pool[key] = item

    planning_context = state.get("planning_context") or {}
    for raw in planning_context.get("google_supplement") or []:
        item = candidate_from_google(raw)
        key = normalize_text(item.get("name"))
        if key:
            pool[key] = item

    return pool


def as_output_poi(item: dict[str, Any], note_suffix: str = "") -> dict[str, Any]:
    notes = safe_str(item.get("notes"))
    if note_suffix:
        notes = f"{notes} {note_suffix}".strip()

    return {
        "name": item.get("name", ""),
        "type": item.get("type", "tourist_spot"),
        "address": item.get("address", ""),
        "lat": item.get("lat"),
        "lng": item.get("lng"),
        "stay_minutes": safe_int(item.get("stay_minutes"), 60),
        "notes": notes,
        "area": item.get("area"),
    }


def used_name_set(itinerary: dict[str, Any]) -> set[str]:
    used = set()
    for day in itinerary.get("days") or []:
        for poi in day.get("pois") or []:
            key = normalize_text(poi_name(poi))
            if key:
                used.add(key)
    return used


def apply_slot_edits(
    itinerary: dict[str, Any],
    edits: dict[str, Any],
    pool: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """User Selection 화면에서 사용자가 건드린 슬롯 상태를 itinerary에 반영한다
    (POST /revalidate). 여기서는 구조만 바꾸고 검증/복구는 안 한다 — 호출부가
    이 결과를 CriticAgent/RepairAgent에 넘긴다.

    POI는 안정적인 id가 없어서(as_output_poi에 id 필드 자체가 없음) 전부
    normalize_text(name) 기준으로 매칭한다 — build_candidate_pool과 동일한 키.

    적용 순서: 제외 -> 교체 -> day 내 재정렬 -> day 번호 이동. 이 순서가
    아니면(예: 재정렬을 먼저 하면) day_order에 적힌 이름이 swap으로 바뀐
    새 이름과 안 맞을 수 있어서 이 순서를 지킨다.
    """
    import copy

    itinerary = copy.deepcopy(itinerary)
    days = itinerary.get("days") or []
    by_day_num = {safe_int(d.get("day"), -1): d for d in days}

    excluded = {normalize_text(x) for x in (edits.get("excluded_ids") or [])}
    swapped = {normalize_text(k): v for k, v in (edits.get("swapped_slots") or {}).items()}
    day_order = edits.get("day_order") or {}          # {"1": [poi_name, ...]}
    day_start_shift = edits.get("day_start_shift") or {}  # {"2": 1}

    # 1. 제외
    if excluded:
        for d in days:
            d["pois"] = [
                p for p in (d.get("pois") or [])
                if normalize_text(poi_name(p)) not in excluded
            ]

    # 2. 교체 — 후보 풀에서 새 POI를 찾아 통째로 갈아끼운다. 풀에 없으면(예:
    # /swap-candidates를 거치지 않고 임의 이름을 보낸 경우) 원본을 그대로 둔다
    # — 조용히 실패해서 슬롯이 사라지는 것보다 낫다.
    if swapped:
        for d in days:
            new_pois = []
            for p in d.get("pois") or []:
                key = normalize_text(poi_name(p))
                new_name = swapped.get(key)
                new_item = pool.get(normalize_text(new_name)) if new_name else None
                if new_item:
                    new_pois.append(as_output_poi(
                        new_item, note_suffix="Swapped via /swap-candidates."
                    ))
                else:
                    new_pois.append(p)
            d["pois"] = new_pois

    # 3. day 내 순서
    for day_str, order in day_order.items():
        d = by_day_num.get(safe_int(day_str, -1))
        if not d:
            continue
        pos = {normalize_text(n): i for i, n in enumerate(order)}
        d["pois"] = sorted(
            d.get("pois") or [],
            key=lambda p: pos.get(normalize_text(poi_name(p)), len(order)),
        )

    # 4. day 번호 이동 — 실제 캘린더 요일이 바뀌므로 CLOSED_ON_ASSIGNED_DAY 같은
    # 요일 기반 규칙이 이후 재평가 단계에서 새 번호로 다시 체크된다.
    if day_start_shift:
        for day_str, shift in day_start_shift.items():
            d = by_day_num.get(safe_int(day_str, -1))
            if d and shift:
                d["day"] = safe_int(d.get("day"), 0) + safe_int(shift, 0)
        days.sort(key=lambda d: safe_int(d.get("day"), 0))

    return itinerary


def candidates_for_area(
    pool: dict[str, dict[str, Any]],
    area: str,
    *,
    exclude: set[str] | None = None,
    preferred_types: set[str] | None = None,
) -> list[dict[str, Any]]:
    exclude = exclude or set()
    preferred_types = preferred_types or set()

    items: list[dict[str, Any]] = []

    for item in pool.values():
        name_key = normalize_text(item.get("name"))
        if name_key in exclude:
            continue

        item_area = item.get("area")
        if not area_matches_requested(item_area, area):
            continue

        if preferred_types:
            ptype = normalize_text(item.get("type"))
            if not any(t in ptype for t in preferred_types):
                continue

        items.append(item)

    def sort_key(x: dict[str, Any]) -> tuple[int, int]:
        # Prefer Google current places, then food/cafe/kpop/shopping.
        source_score = 0 if x.get("source_kind") == "google" else 1
        ptype = normalize_text(x.get("type"))
        type_score = 0
        if ptype in {"cafe", "restaurant", "kpop_landmark", "shopping", "shopping_mall"}:
            type_score = -1
        return (source_score, type_score)

    return sorted(items, key=sort_key)


# ---------------------------------------------------------------------------
# Critic data structures
# ---------------------------------------------------------------------------

@dataclass
class CriticIssue:
    code: str
    severity: str
    message: str
    day: int | None = None
    area: str | None = None


class CriticAgent:
    def evaluate(self, state: dict[str, Any]) -> dict[str, Any]:
        itinerary = state.get("itinerary") or {}
        requested_areas = self._get_requested_areas(state)

        issues: list[CriticIssue] = []

        area_report = self._evaluate_area_coverage(itinerary, requested_areas, issues)
        day_report = self._evaluate_days(itinerary, requested_areas, issues)
        duplicate_report = self._evaluate_duplicates(itinerary, issues)
        foreigner_report = self._evaluate_foreigner_readiness(itinerary, issues)

        feasibility_score = day_report["score"]
        area_score = area_report["score"]
        duplicate_score = duplicate_report["score"]
        foreigner_score = foreigner_report["score"]

        overall = round(
            0.35 * feasibility_score
            + 0.35 * area_score
            + 0.15 * duplicate_score
            + 0.15 * foreigner_score,
            3,
        )

        return {
            "overall_score": overall,
            "feasibility_score": feasibility_score,
            "requested_area_coverage_score": area_score,
            "duplicate_score": duplicate_score,
            "foreigner_readiness_score": foreigner_score,
            "requested_areas": requested_areas,
            "area_coverage": area_report["coverage"],
            "missing_areas": area_report["missing_areas"],
            "issues": [issue.__dict__ for issue in issues],
        }

    def _get_requested_areas(self, state: dict[str, Any]) -> list[str]:
        planning_context = state.get("planning_context") or {}
        requested = planning_context.get("requested_areas")
        if requested:
            return list(requested)

        return extract_requested_areas(
            state.get("region"),
            state.get("category"),
        )

    def _evaluate_area_coverage(
        self,
        itinerary: dict[str, Any],
        requested_areas: list[str],
        issues: list[CriticIssue],
    ) -> dict[str, Any]:
        if not requested_areas:
            return {
                "score": 1.0,
                "coverage": {},
                "missing_areas": [],
            }

        coverage = {area: 0 for area in requested_areas}

        for day in itinerary.get("days") or []:
            for poi in day.get("pois") or []:
                area = infer_area_from_poi(poi)
                for req in requested_areas:
                    if area_matches_requested(area, req):
                        coverage[req] += 1

        missing = [area for area, count in coverage.items() if count < 2]

        for area in missing:
            issues.append(CriticIssue(
                code="REQUESTED_AREA_UNDER_COVERED",
                severity="high",
                message=f"Requested area {area_label(area)} has fewer than 2 POIs.",
                area=area,
            ))

        score = 1.0
        if requested_areas:
            satisfied = sum(1 for area in requested_areas if coverage.get(area, 0) >= 2)
            score = satisfied / len(requested_areas)

        return {
            "score": round(score, 3),
            "coverage": coverage,
            "missing_areas": missing,
        }

    def _evaluate_days(
        self,
        itinerary: dict[str, Any],
        requested_areas: list[str],
        issues: list[CriticIssue],
    ) -> dict[str, Any]:
        days = itinerary.get("days") or []
        if not days:
            issues.append(CriticIssue(
                code="NO_DAYS",
                severity="critical",
                message="No days were generated in the itinerary.",
            ))
            return {"score": 0.0}

        penalties = 0.0
        checks = 0

        for day in days:
            day_num = safe_int(day.get("day"), 0)
            pois = day.get("pois") or []

            checks += 1
            if len(pois) < 5:
                penalties += 0.35
                issues.append(CriticIssue(
                    code="TOO_FEW_POIS",
                    severity="medium",
                    message=f"Day {day_num} has only {len(pois)} POIs; at least 5 are recommended.",
                    day=day_num,
                ))

            checks += 1
            if not any(is_meal_poi(p) for p in pois):
                penalties += 0.25
                issues.append(CriticIssue(
                    code="NO_MEAL_SLOT",
                    severity="medium",
                    message=f"Day {day_num} has no clear cafe/restaurant/market slot.",
                    day=day_num,
                ))

            checks += 1
            if self._day_is_geographically_scattered(pois):
                penalties += 0.20
                issues.append(CriticIssue(
                    code="SCATTERED_DAY_ROUTE",
                    severity="medium",
                    message=f"Day {day_num} appears geographically scattered.",
                    day=day_num,
                ))

        if checks == 0:
            return {"score": 0.0}

        score = max(0.0, 1.0 - penalties / max(len(days), 1))
        return {"score": round(score, 3)}

    def _day_is_geographically_scattered(self, pois: list[dict[str, Any]]) -> bool:
        coords: list[tuple[float, float]] = []

        for p in pois:
            lat = safe_float(p.get("lat"))
            lng = safe_float(p.get("lng"))
            if lat is not None and lng is not None:
                coords.append((lat, lng))

        if len(coords) < 2:
            return False

        max_dist = 0.0
        for i in range(len(coords)):
            for j in range(i + 1, len(coords)):
                dist = haversine_km(coords[i][0], coords[i][1], coords[j][0], coords[j][1])
                max_dist = max(max_dist, dist)

        return max_dist > 8.0

    def _evaluate_duplicates(
        self,
        itinerary: dict[str, Any],
        issues: list[CriticIssue],
    ) -> dict[str, Any]:
        seen: set[str] = set()
        duplicates: list[str] = []

        for day in itinerary.get("days") or []:
            for poi in day.get("pois") or []:
                key = normalize_text(poi_name(poi))
                if not key:
                    continue
                if key in seen:
                    duplicates.append(poi_name(poi))
                seen.add(key)

        if duplicates:
            issues.append(CriticIssue(
                code="DUPLICATE_POIS",
                severity="low",
                message=f"Duplicate POIs found: {', '.join(duplicates)}.",
            ))

        return {"score": 0.85 if duplicates else 1.0}

    def _evaluate_foreigner_readiness(
        self,
        itinerary: dict[str, Any],
        issues: list[CriticIssue],
    ) -> dict[str, Any]:
        total = 0
        risky = 0

        for day in itinerary.get("days") or []:
            for poi in day.get("pois") or []:
                total += 1
                english = safe_int(poi.get("english_support"), 1)
                cash_only = safe_int(poi.get("cash_only"), 0)
                friction = safe_int(poi.get("cultural_friction"), 0)
                confidence = normalize_text(poi.get("label_confidence"))

                if english == 0 or cash_only == 1 or friction == 1:
                    risky += 1

                if confidence == "low":
                    risky += 0.25

        if total == 0:
            return {"score": 0.7}

        ratio = risky / total
        score = max(0.0, 1.0 - ratio * 0.5)

        if ratio >= 0.4:
            issues.append(CriticIssue(
                code="HIGH_FOREIGNER_FRICTION",
                severity="medium",
                message="Many POIs may have language, payment, or cultural friction for foreign visitors.",
            ))

        return {"score": round(score, 3)}


# ---------------------------------------------------------------------------
# Repair Agent
# ---------------------------------------------------------------------------

class RepairAgent:
    def repair(self, state: dict[str, Any], report: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        itinerary = state.get("itinerary") or {}
        pool = build_candidate_pool(state)
        logs: list[str] = []

        if not itinerary.get("days"):
            return itinerary, logs

        requested_areas = report.get("requested_areas") or extract_requested_areas(
            state.get("region"),
            state.get("category"),
        )

        itinerary = self._repair_missing_areas(
            itinerary=itinerary,
            pool=pool,
            requested_areas=requested_areas,
            logs=logs,
        )

        itinerary = self._repair_missing_meals(
            itinerary=itinerary,
            pool=pool,
            requested_areas=requested_areas,
            logs=logs,
        )

        itinerary = self._repair_underfilled_days(
            itinerary=itinerary,
            pool=pool,
            requested_areas=requested_areas,
            logs=logs,
        )

        itinerary = self._remove_duplicates(
            itinerary=itinerary,
            logs=logs,
        )

        itinerary["repair_log"] = logs
        return itinerary, logs

    def _repair_missing_areas(
        self,
        *,
        itinerary: dict[str, Any],
        pool: dict[str, dict[str, Any]],
        requested_areas: list[str],
        logs: list[str],
    ) -> dict[str, Any]:
        if not requested_areas:
            return itinerary

        days = itinerary.get("days") or []
        if not days:
            return itinerary

        coverage = self._coverage(itinerary, requested_areas)
        used = used_name_set(itinerary)

        for idx, area in enumerate(requested_areas):
            current = coverage.get(area, 0)
            if current >= 2:
                continue

            target_day_idx = min(idx, len(days) - 1)
            target_day = days[target_day_idx]
            needed = 2 - current

            candidates = candidates_for_area(
                pool,
                area,
                exclude=used,
            )

            inserted = 0
            for item in candidates:
                if inserted >= needed:
                    break

                poi = as_output_poi(
                    item,
                    note_suffix=f"Added by Repair Agent to cover requested area: {area_label(area)}."
                )
                target_day.setdefault("pois", []).append(poi)
                used.add(normalize_text(poi.get("name")))
                inserted += 1

            if inserted:
                logs.append(f"Added {inserted} POI(s) for requested area {area_label(area)}.")

        return itinerary

    def _repair_missing_meals(
        self,
        *,
        itinerary: dict[str, Any],
        pool: dict[str, dict[str, Any]],
        requested_areas: list[str],
        logs: list[str],
    ) -> dict[str, Any]:
        used = used_name_set(itinerary)

        for idx, day in enumerate(itinerary.get("days") or []):
            pois = day.setdefault("pois", [])
            if any(is_meal_poi(p) for p in pois):
                continue

            target_area = self._target_area_for_day(day, requested_areas, idx)
            candidates = []
            if target_area:
                candidates = candidates_for_area(
                    pool,
                    target_area,
                    exclude=used,
                    preferred_types={"restaurant", "cafe"},
                )

            if not candidates:
                candidates = [
                    item for item in pool.values()
                    if normalize_text(item.get("name")) not in used
                    and normalize_text(item.get("type")) in {"restaurant", "cafe"}
                    and not belongs_to_other_requested_area(
                        item.get("area"), target_area, requested_areas
                    )
                ]

            if candidates:
                item = candidates[0]
                poi = as_output_poi(
                    item,
                    note_suffix="Added by Repair Agent as a required meal/cafe slot."
                )
                insert_idx = min(2, len(pois))
                pois.insert(insert_idx, poi)
                used.add(normalize_text(poi.get("name")))
                logs.append(f"Added meal slot on Day {day.get('day')}: {poi.get('name')}.")

        return itinerary

    def _repair_underfilled_days(
        self,
        *,
        itinerary: dict[str, Any],
        pool: dict[str, dict[str, Any]],
        requested_areas: list[str],
        logs: list[str],
    ) -> dict[str, Any]:
        used = used_name_set(itinerary)

        for idx, day in enumerate(itinerary.get("days") or []):
            pois = day.setdefault("pois", [])
            if len(pois) >= 5:
                continue

            target_area = self._target_area_for_day(day, requested_areas, idx)
            candidates = []

            if target_area:
                candidates = candidates_for_area(
                    pool,
                    target_area,
                    exclude=used,
                )

            if not candidates:
                candidates = [
                    item for item in pool.values()
                    if normalize_text(item.get("name")) not in used
                    and not belongs_to_other_requested_area(
                        item.get("area"), target_area, requested_areas
                    )
                ]

            added = 0
            while len(pois) < 5 and candidates:
                item = candidates.pop(0)
                poi = as_output_poi(
                    item,
                    note_suffix="Added by Repair Agent to make the day sufficiently complete."
                )
                pois.append(poi)
                used.add(normalize_text(poi.get("name")))
                added += 1

            if added:
                logs.append(f"Added {added} POI(s) to Day {day.get('day')} because the day was under-filled.")

        return itinerary

    def _remove_duplicates(
        self,
        *,
        itinerary: dict[str, Any],
        logs: list[str],
    ) -> dict[str, Any]:
        seen: set[str] = set()

        for day in itinerary.get("days") or []:
            cleaned: list[dict[str, Any]] = []

            for poi in day.get("pois") or []:
                key = normalize_text(poi_name(poi))
                if not key:
                    continue

                if key in seen:
                    logs.append(f"Removed duplicate POI: {poi_name(poi)}.")
                    continue

                seen.add(key)
                cleaned.append(poi)

            day["pois"] = cleaned

        return itinerary

    def _coverage(self, itinerary: dict[str, Any], requested_areas: list[str]) -> dict[str, int]:
        coverage = {area: 0 for area in requested_areas}

        for day in itinerary.get("days") or []:
            for poi in day.get("pois") or []:
                area = infer_area_from_poi(poi)
                for req in requested_areas:
                    if area_matches_requested(area, req):
                        coverage[req] += 1

        return coverage

    def _target_area_for_day(
        self,
        day: dict[str, Any],
        requested_areas: list[str],
        day_index: int,
    ) -> str | None:
        if requested_areas:
            return requested_areas[min(day_index, len(requested_areas) - 1)]

        counts: dict[str, int] = {}
        for poi in day.get("pois") or []:
            area = infer_area_from_poi(poi)
            if area:
                counts[area] = counts.get(area, 0) + 1

        if not counts:
            return None

        return max(counts.items(), key=lambda x: x[1])[0]


# ---------------------------------------------------------------------------
# Public graph node
# ---------------------------------------------------------------------------

def _poi_coords(poi: dict[str, Any]) -> tuple[float, float] | None:
    lat, lng = poi.get("lat"), poi.get("lng")
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
        return float(lat), float(lng)
    return None


def _leg_km(a: dict[str, Any] | None, b: dict[str, Any] | None) -> float:
    if a is None or b is None:
        return 0.0
    ca, cb = _poi_coords(a), _poi_coords(b)
    if ca is None or cb is None:
        return 0.0
    return haversine_km(ca[0], ca[1], cb[0], cb[1])


def reorder_supplements(
    pois: list[dict[str, Any]],
    movable_names: set[str],
) -> list[dict[str, Any]]:
    """Place each supplement POI into the gap that adds the least walking, keeping
    the editorial (anchor) POIs in their curated order.

    Supplements are Google-Places / meal inserts, searched from the neighborhood
    *center*, so they often land far from the day's actual cluster while the LLM's
    order is never geographically re-checked. This snaps each to its cheapest-
    insertion slot.

    `movable_names` are the normalized names of google-sourced POIs, taken from
    build_candidate_pool(state). We match by name because both as_output_poi
    functions strip source_kind from the final POIs, so provenance isn't on the
    POI itself — the pool is the only surviving record of which POIs are google.

    ponytail: greedy cheapest-insertion, fine at <=8 POIs/day; swap for full
    2-opt only if transition scores stay bad. Backbone order is left untouched.
    """
    def _movable(p: dict[str, Any]) -> bool:
        return normalize_text(p.get("name")) in movable_names and _poi_coords(p) is not None

    extras = [p for p in pois if _movable(p)]
    if not extras:
        return pois
    extra_ids = {id(p) for p in extras}
    route = [p for p in pois if id(p) not in extra_ids]  # backbone, original order
    for p in extras:
        best_i, best_cost = len(route), float("inf")
        for i in range(len(route) + 1):
            a = route[i - 1] if i > 0 else None
            b = route[i] if i < len(route) else None
            cost = _leg_km(a, p) + _leg_km(p, b) - _leg_km(a, b)
            if cost < best_cost:
                best_cost, best_i = cost, i
        route.insert(best_i, p)
    return route


def make_critic_repair_node(base_dir: Any | None = None):
    critic = CriticAgent()
    repairer = RepairAgent()

    def critic_repair_node(state: TravelState) -> TravelState:
        itinerary = state.get("itinerary")

        if not itinerary:
            return {
                **state,
                "current_step": "done",
                "messages": [
                    AIMessage(content="⚠️ Critic-Repair skipped because no itinerary was found.")
                ],
            }

        try:
            before_report = critic.evaluate(state)

            repaired_itinerary, repair_logs = repairer.repair(
                state={**state, "itinerary": itinerary},
                report=before_report,
            )

            # Google-sourced POIs lose their source_kind by the time they land in
            # a day (both as_output_poi helpers strip it), so recover it from the
            # candidate pool — the only surviving record — and tidy each day's route.
            pool = build_candidate_pool(state)
            movable_names = {n for n, it in pool.items() if it.get("source_kind") == "google"}
            for day in repaired_itinerary.get("days") or []:
                day["pois"] = reorder_supplements(day.get("pois") or [], movable_names)
                day["transit_legs"] = compute_transit_legs(day.get("pois") or [])

            after_state = {**state, "itinerary": repaired_itinerary}
            after_report = critic.evaluate(after_state)

            repaired_itinerary["critic_report"] = {
                "before": before_report,
                "after": after_report,
                "repair_applied": bool(repair_logs),
                "repair_log": repair_logs,
            }

            requested = after_report.get("requested_areas") or []
            coverage = after_report.get("area_coverage") or {}
            coverage_text = ", ".join(
                f"{area_label(area)}={coverage.get(area, 0)}"
                for area in requested
            ) if requested else "No specific requested areas"

            score = after_report.get("overall_score")

            msg = (
                f"✅ Critic-Repair completed.\n"
                f"- Overall score: {score}\n"
                f"- Requested area coverage: {coverage_text}\n"
                f"- Repairs applied: {len(repair_logs)}"
            )

            return {
                **state,
                "itinerary": repaired_itinerary,
                "critic_report": repaired_itinerary["critic_report"],
                "current_step": "done",
                "messages": [AIMessage(content=msg)],
            }

        except Exception as e:
            return {
                **state,
                "current_step": "done",
                "messages": [
                    AIMessage(content=f"⚠️ Critic-Repair 오류: {e}")
                ],
            }

    return critic_repair_node
