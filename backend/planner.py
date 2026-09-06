"""Itinerary planning nodes for the LangGraph.

`retrieve_node` runs FAISS retrieval over course_data.json and stashes
the top courses in state. `plan_node` calls a DSPy signature that turns
those courses + the user's confirmed fields into a structured day-by-day
itinerary.

Main improvements:
1. Search RAG by requested areas such as Hongdae and Seongsu.
2. Call Google Places for EACH requested area, not only once.
3. Add real cafes/restaurants/K-POP/shopping places from Google Places.
4. Force itinerary to cover all requested neighborhoods.
5. Remove hallucinated POIs that are not in candidate courses or Google Places.
6. Auto-fill missing meals and under-filled days.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any

import dspy
import requests
from dotenv import load_dotenv
from langchain_core.messages import AIMessage

from geo import (
    AREA_ALIASES,
    DEFAULT_CENTER,
    SEOUL_AREA_CENTERS,
    area_label as _area_label,
    area_matches_requested as _area_matches_requested,
    extract_requested_areas as _extract_requested_areas,
    get_area_center as _get_area_center,
    haversine_km as _haversine_km,
    infer_area_from_fields as _infer_area_from_text_or_coords,
)
# lm_context removed — DSPy replaced with direct Gemini calls
from rag import (
    _parse_num_days,
    build_query,
    parse_day_segments,
    retrieve_for_segments,
)
from state import TravelState

load_dotenv()

# ---------------------------------------------------------------------------
# Gemini key (set by make_retrieve_node via set_planner_api_key)
# ---------------------------------------------------------------------------

_PLANNER_GEMINI_KEY: str = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")


def set_planner_api_key(key: str) -> None:
    global _PLANNER_GEMINI_KEY
    _PLANNER_GEMINI_KEY = key


def _gemini_text(prompt: str) -> str:
    """Call Gemini and return raw text (JSON expected from caller)."""
    from google import genai as _genai
    client = _genai.Client(api_key=_PLANNER_GEMINI_KEY)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config={"response_mime_type": "application/json"},
    )
    return response.text or ""


# ---------------------------------------------------------------------------
# Google Places configuration
# ---------------------------------------------------------------------------

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")

KAKAO_ROUTE_BASE = "https://m.map.kakao.com/scheme/route"
WALK_KMH = 4.0
CAR_KMH = 30.0


# ---------------------------------------------------------------------------
# General string normalization
# ---------------------------------------------------------------------------

def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _kakao_route_url(
    start_lat: float, start_lng: float, end_lat: float, end_lng: float, mode: str
) -> str:
    return (
        f"{KAKAO_ROUTE_BASE}?sp={start_lat},{start_lng}"
        f"&ep={end_lat},{end_lng}&by={mode}"
    )


def compute_transit_legs(pois: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Distance + walk/car ETA + Kakao deep links + ODsay public transit options.

    ODsay 호출은 옵션적임 — 키가 없거나 실패하면 transit_options=[] 로 두고
    Flutter 측에서 렌더 안 함. 좌표 누락된 leg 도 ODsay 안 호출.
    """
    import odsay  # local import to keep planner import cycle clean

    legs: list[dict[str, Any]] = []
    odsay_enabled = odsay.is_enabled()

    for i in range(len(pois) - 1):
        a, b = pois[i], pois[i + 1]
        try:
            lat1 = float(a.get("lat"))
            lng1 = float(a.get("lng"))
            lat2 = float(b.get("lat"))
            lng2 = float(b.get("lng"))
        except (TypeError, ValueError):
            legs.append({
                "from_idx": i,
                "to_idx": i + 1,
                "from_name": a.get("name"),
                "to_name": b.get("name"),
                "distance_km": None,
                "walk_minutes": None,
                "car_minutes": None,
                "kakao_walk_url": None,
                "kakao_car_url": None,
                "transit_options": [],
            })
            continue

        dist = _haversine_km(lat1, lng1, lat2, lng2)

        transit_options: list[dict[str, Any]] = []
        if odsay_enabled:
            transit_options = odsay.fetch_odsay_options(lat1, lng1, lat2, lng2)
            time.sleep(0.2)  # rate-limit 안전 (호출자 책임)

        legs.append({
            "from_idx": i,
            "to_idx": i + 1,
            "from_name": a.get("name"),
            "to_name": b.get("name"),
            "distance_km": round(dist, 2),
            "walk_minutes": max(1, round(dist / WALK_KMH * 60)),
            "car_minutes": max(1, round(dist / CAR_KMH * 60)),
            "kakao_walk_url": _kakao_route_url(lat1, lng1, lat2, lng2, "foot"),
            "kakao_car_url": _kakao_route_url(lat1, lng1, lat2, lng2, "car"),
            "transit_options": transit_options,
        })
    return legs


# ---------------------------------------------------------------------------
# Google Places API
# ---------------------------------------------------------------------------

def _google_get(url: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        resp = requests.get(url, params=params, timeout=12)
        data = resp.json()
        status = data.get("status")
        if status not in {"OK", "ZERO_RESULTS"}:
            print(f"[Google Places] status={status}, error={data.get('error_message')}")
        return data
    except Exception as e:
        print(f"[Google Places] request error: {e}")
        return {}


def fetch_nearby_places(
    *,
    area: str,
    place_type: str,
    api_key: str,
    radius: int = 1700,
    min_rating: float = 4.0,
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """Google Places Nearby Search for one area."""
    if not api_key:
        return []

    lat, lng = SEOUL_AREA_CENTERS.get(area, DEFAULT_CENTER)
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lng}",
        "radius": radius,
        "type": place_type,
        "key": api_key,
        "language": "en",
    }

    data = _google_get(url, params)
    results = data.get("results", []) or []
    # A hotel with a well-known in-house restaurant genuinely carries BOTH
    # "lodging" and "restaurant" in Google's own types[] (confirmed live for
    # "Hotel Prince Seoul": types=[..., "lodging", ..., "restaurant"]), so a
    # `place_type in types` check doesn't filter it out of a restaurant/cafe
    # search -- Google's server-side type filter already passed it through as
    # a legitimate match. That hotel then shows up as a "similar" swap
    # candidate for an actual standalone restaurant, which is misleading even
    # though it's not technically wrong. Explicitly drop anything Google also
    # tags "lodging" from non-lodging searches -- we never want a hotel
    # filling a restaurant/cafe/shopping slot.
    filtered = [
        r for r in results
        if float(r.get("rating") or 0) >= min_rating
        and "lodging" not in (r.get("types") or [])
    ]

    places: list[dict[str, Any]] = []
    for r in filtered[:max_results]:
        loc = (r.get("geometry") or {}).get("location") or {}
        if "lat" not in loc or "lng" not in loc:
            continue

        stay = 60
        if place_type == "cafe":
            stay = 45
        elif place_type == "restaurant":
            stay = 60
        elif place_type == "shopping_mall":
            stay = 75

        places.append({
            "poi_name": r.get("name", ""),
            "poi_type": place_type,
            "address_en": r.get("vicinity") or r.get("formatted_address", ""),
            "address_ko": r.get("vicinity") or r.get("formatted_address", ""),
            "lat": loc["lat"],
            "lng": loc["lng"],
            "rating": r.get("rating"),
            "estimated_stay_time": stay,
            "source": f"Google Places ({_area_label(area)})",
            "area": area,
            "place_id": r.get("place_id", ""),
        })

    return places


def fetch_text_places(
    *,
    area: str,
    query: str,
    api_key: str,
    radius: int = 2500,
    min_rating: float = 0.0,
    max_results: int = 5,
    poi_type: str = "tourist_spot",
) -> list[dict[str, Any]]:
    """Google Places Text Search for one area."""
    if not api_key:
        return []

    lat, lng = SEOUL_AREA_CENTERS.get(area, DEFAULT_CENTER)
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        "query": query,
        "location": f"{lat},{lng}",
        "radius": radius,
        "key": api_key,
        "language": "en",
    }

    data = _google_get(url, params)
    results = data.get("results", []) or []

    places: list[dict[str, Any]] = []
    seen: set[str] = set()

    for r in results:
        name = r.get("name", "")
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())

        if r.get("business_status") and r.get("business_status") != "OPERATIONAL":
            continue

        # Same "hotel with a notable restaurant" issue as fetch_nearby_places
        # -- a text query like "best restaurants in X" can legitimately surface
        # a hotel Google also tags "lodging". Drop it so it never fills a
        # restaurant/cafe/shopping slot as a swap candidate.
        if "lodging" in (r.get("types") or []):
            continue

        rating = float(r.get("rating") or 0)
        if rating < min_rating:
            continue

        loc = (r.get("geometry") or {}).get("location") or {}
        if "lat" not in loc or "lng" not in loc:
            continue

        places.append({
            "poi_name": name,
            "poi_type": poi_type,
            "address_en": r.get("formatted_address", ""),
            "address_ko": r.get("formatted_address", ""),
            "lat": loc["lat"],
            "lng": loc["lng"],
            "rating": r.get("rating"),
            "estimated_stay_time": 60,
            "source": f"Google Places Text ({_area_label(area)})",
            "area": area,
            "place_id": r.get("place_id", ""),
        })

        if len(places) >= max_results:
            break

    return places


# ---------------------------------------------------------------------------
# Google Places — weekly (regular) closure day lookup
#
# Places API (New)'s `regularOpeningHours` field is what the docs recommend
# for this, but that API is NOT enabled on this project's Google Cloud key
# (places.googleapis.com returns 403 SERVICE_DISABLED — see
# backend/scripts/places_api_probe.py). The legacy Place Details endpoint's
# `opening_hours` field is functionally equivalent for our purpose (it has
# `weekday_text` with an explicit "Tuesday: Closed" line when a place has a
# fixed weekly closure day) and already works with the current key, so this
# uses that instead. If Places API (New) is enabled later, swap the two
# functions below for a single `places:searchText`/Place Details (New) call
# with `X-Goog-FieldMask: regularOpeningHours` and read `.specialDays`/the
# per-day `open`/`close` list the same way.
# ---------------------------------------------------------------------------

_WEEKDAY_NAMES = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
]


def find_place_id(
    *, name: str, address: str, lat: float | None, lng: float | None, api_key: str
) -> str | None:
    """Legacy Find Place — resolves a (name, address) pair to a Google place_id.
    Location-biased when lat/lng are available to avoid mismatching a same-named
    place elsewhere. Returns None on any failure (never raises)."""
    if not api_key or not name:
        return None

    url = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
    params = {
        "input": f"{name}, {address}" if address else name,
        "inputtype": "textquery",
        "fields": "place_id,name,formatted_address",
        "key": api_key,
    }
    if lat is not None and lng is not None:
        params["locationbias"] = f"point:{lat},{lng}"

    data = _google_get(url, params)
    candidates = data.get("candidates") or []
    if not candidates:
        return None
    return candidates[0].get("place_id")


def fetch_weekly_closure(*, place_id: str, api_key: str) -> dict[str, Any] | None:
    """Legacy Place Details, Contact Data tier only (fields=opening_hours) —
    returns the raw `opening_hours` object, or None if the place has no
    published hours / the request failed."""
    if not api_key or not place_id:
        return None

    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "fields": "name,opening_hours,business_status",
        "key": api_key,
    }
    data = _google_get(url, params)
    result = data.get("result") or {}
    return result.get("opening_hours")


def derive_closed_weekdays(opening_hours: dict[str, Any] | None) -> list[str] | None:
    """Parses `weekday_text` (e.g. "Tuesday: Closed") into a list of weekday
    names the place is regularly closed. Returns [] if it has hours every day,
    None if there's no usable weekday_text at all (caller should treat that as
    "no data", not "open every day")."""
    if not opening_hours:
        return None
    weekday_text = opening_hours.get("weekday_text") or []
    if not weekday_text:
        return None

    closed = []
    for line in weekday_text:
        day, _, hours = line.partition(":")
        if "closed" in hours.strip().lower():
            day = day.strip()
            if day in _WEEKDAY_NAMES:
                closed.append(day)
    return closed


def fetch_kpop_places_for_area(
    *,
    area: str,
    api_key: str,
    purpose: str,
    max_results: int = 5,
) -> list[dict[str, Any]]:
    if not api_key:
        return []

    purpose_lower = purpose.lower()

    artists = [
        "bts", "blackpink", "aespa", "newjeans", "ive", "stray kids",
        "twice", "exo", "seventeen", "txt", "enhypen", "idol", "kpop", "k-pop",
    ]

    detected = [a for a in artists if a in purpose_lower]
    area_name = _area_label(area)

    queries: list[str] = []

    if detected:
        for artist in detected[:2]:
            artist_clean = artist.replace("k-pop", "kpop")
            queries.append(f"{artist_clean} store {area_name} Seoul")
            queries.append(f"{artist_clean} cafe {area_name} Seoul")

    queries.extend([
        f"kpop store {area_name} Seoul",
        f"kpop merchandise {area_name} Seoul",
        f"kpop popup store {area_name} Seoul",
    ])

    all_places: list[dict[str, Any]] = []
    seen: set[str] = set()

    for q in queries[:4]:
        places = fetch_text_places(
            area=area,
            query=q,
            api_key=api_key,
            radius=3500,
            min_rating=0.0,
            max_results=3,
            poi_type="kpop_landmark",
        )
        for p in places:
            key = _normalize_text(p.get("poi_name"))
            if key and key not in seen:
                seen.add(key)
                all_places.append(p)
        time.sleep(0.2)

    return all_places[:max_results]


def build_google_supplement_for_area(
    *,
    area: str,
    purpose: str,
    api_key: str,
) -> list[dict[str, Any]]:
    """Collect Google Places supplement for one requested area."""
    if not api_key:
        return []

    purpose_lower = purpose.lower()
    supplement: list[dict[str, Any]] = []

    # Cafes are essential for Seoul travel and the current project use case.
    need_cafe = any(k in purpose_lower for k in ["cafe", "coffee", "relax", "카페"])
    if need_cafe:
        cafes = fetch_nearby_places(
            area=area,
            place_type="cafe",
            api_key=api_key,
            radius=1800,
            min_rating=4.1,
            max_results=5,
        )
        if len(cafes) < 3:
            cafes += fetch_text_places(
                area=area,
                query=f"best cafes in {_area_label(area)} Seoul",
                api_key=api_key,
                radius=2500,
                min_rating=4.0,
                max_results=5 - len(cafes),
                poi_type="cafe",
            )
        supplement.extend(cafes)
        print(f"[Google Places][{_area_label(area)}] 카페 {len(cafes)}개 추가")

    restaurants = fetch_nearby_places(
        area=area,
        place_type="restaurant",
        api_key=api_key,
        radius=1800,
        min_rating=4.0,
        max_results=5,
    )
    if len(restaurants) < 3:
        restaurants += fetch_text_places(
            area=area,
            query=f"popular restaurants in {_area_label(area)} Seoul",
            api_key=api_key,
            radius=2500,
            min_rating=4.0,
            max_results=5 - len(restaurants),
            poi_type="restaurant",
        )
    supplement.extend(restaurants)
    print(f"[Google Places][{_area_label(area)}] 식당 {len(restaurants)}개 추가")

    if any(k in purpose_lower for k in ["kpop", "k-pop", "bts", "blackpink", "idol", "아이돌"]):
        kpop_places = fetch_kpop_places_for_area(
            area=area,
            api_key=api_key,
            purpose=purpose,
            max_results=5,
        )
        supplement.extend(kpop_places)
        print(f"[Google Places][{_area_label(area)}] K-POP 장소 {len(kpop_places)}개 추가")

    if any(k in purpose_lower for k in ["shopping", "shop", "fashion", "쇼핑"]):
        shops = fetch_nearby_places(
            area=area,
            place_type="shopping_mall",
            api_key=api_key,
            radius=2200,
            min_rating=4.0,
            max_results=3,
        )
        if len(shops) < 2:
            shops += fetch_text_places(
                area=area,
                query=f"shopping in {_area_label(area)} Seoul",
                api_key=api_key,
                radius=2500,
                min_rating=4.0,
                max_results=3 - len(shops),
                poi_type="shopping",
            )
        supplement.extend(shops)
        print(f"[Google Places][{_area_label(area)}] 쇼핑 {len(shops)}개 추가")

    # Catch-all: the branches above only cover food/cafe/kpop/shopping. Any other
    # purpose (K-beauty, art, nature, nightlife, ...) gets no targeted POIs, so
    # search Google for the purpose itself. Type-based fetches stay the primary
    # path for the common themes; this only fills the long tail.
    if purpose and purpose.strip():
        generic = fetch_text_places(
            area=area,
            query=f"{purpose} in {_area_label(area)} Seoul",
            api_key=api_key,
            radius=2500,
            min_rating=4.0,
            max_results=5,
        )
        # Text Search's radius is only a bias, and fetch_text_places stamps
        # area=requested on every hit. Re-infer each POI's true area from its
        # coords and keep only ones actually in (or adjacent to) this area, so an
        # off-neighborhood result can't be mislabeled and inflate area_coverage.
        kept = []
        for p in generic:
            true_area = _infer_area_from_text_or_coords(
                p.get("poi_name"), p.get("address_en"), p.get("lat"), p.get("lng"))
            if true_area and _area_matches_requested(true_area, area):
                p["area"] = true_area
                kept.append(p)
        if kept:
            supplement.extend(kept)
            print(f"[Google Places][{_area_label(area)}] 목적 기반 {len(kept)}개 추가")

    return _dedupe_places(supplement)


def build_google_supplement_by_areas(
    *,
    requested_areas: list[str],
    location: str,
    purpose: str,
    api_key: str,
) -> list[dict[str, Any]]:
    """Collect Google Places supplement for every requested area."""
    if not api_key:
        return []

    if not requested_areas:
        # Fallback: choose one area from location string or Seoul center.
        fallback_area = None
        text = _normalize_text(location)
        for area, aliases in AREA_ALIASES.items():
            if area in text or any(alias in text for alias in aliases):
                fallback_area = area
                break
        requested_areas = [fallback_area or "myeongdong"]

    print(f"[planner] 요청 지역별 Google Places 보완 시작: {[_area_label(a) for a in requested_areas]}")

    all_places: list[dict[str, Any]] = []
    for area in requested_areas:
        places = build_google_supplement_for_area(
            area=area,
            purpose=purpose,
            api_key=api_key,
        )
        all_places.extend(places)

    all_places = _dedupe_places(all_places)
    print(f"[planner] Google Places 총 {len(all_places)}개 보완 데이터 확보")
    return all_places


def _dedupe_places(places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []

    for p in places:
        name = _normalize_text(p.get("poi_name"))
        lat = p.get("lat")
        lng = p.get("lng")
        key = f"{name}|{round(float(lat), 4) if lat is not None else ''}|{round(float(lng), 4) if lng is not None else ''}"
        if not name or key in seen:
            continue
        seen.add(key)
        deduped.append(p)

    return deduped


# ---------------------------------------------------------------------------
# Formatting prompt context
# ---------------------------------------------------------------------------

def _format_google_supplement(places: list[dict[str, Any]]) -> str:
    if not places:
        return ""

    lines = [
        "",
        "",
        "=== REAL-TIME GOOGLE PLACES DATA ===",
        "These are verified real places. Use them for cafes, restaurants, K-POP spots, and shopping.",
        "Each Google Places POI has an `area` field. If the user requested that area, you MUST use some POIs from that area.",
        "",
    ]

    for p in places:
        rating = f"rating={p.get('rating')}" if p.get("rating") else ""
        lines.append(
            f"  - {p.get('poi_name', '')} "
            f"[{p.get('poi_type', '')}] "
            f"area={p.get('area', '')} "
            f"addr={p.get('address_en') or p.get('address_ko', '')} "
            f"lat={p.get('lat')} lng={p.get('lng')} "
            f"stay={p.get('estimated_stay_time', 60)}min "
            f"{rating} "
            f"source={p.get('source', '')}"
        )

    return "\n".join(lines)


def _format_requested_area_rules(
    requested_areas: list[str], duration: str, num_days: int | None = None,
) -> str:
    if not requested_areas:
        return ""

    labels = [_area_label(a) for a in requested_areas]
    num_days = _parse_num_days(duration, override=num_days)

    lines = [
        "",
        "=== REQUESTED AREA COVERAGE RULES ===",
        f"The user explicitly requested these areas: {', '.join(labels)}.",
        "You MUST include at least 2 POIs from EACH requested area across the full itinerary.",
        "Do NOT omit a requested area.",
        "If candidate course data is weak for an area, use REAL-TIME GOOGLE PLACES DATA for that area.",
    ]

    if len(requested_areas) >= 2:
        # Distribute areas evenly across the actual number of days.
        days_per_area = max(1, num_days // len(requested_areas))
        area_assignments = []
        for i, label in enumerate(labels):
            start_day = i * days_per_area + 1
            end_day = start_day + days_per_area - 1
            if i == len(labels) - 1:
                end_day = num_days  # last area gets any remainder days
            if start_day == end_day:
                area_assignments.append(f"Day {start_day} = {label}")
            else:
                area_assignments.append(f"Days {start_day}–{end_day} = {label}")
        lines.append(
            f"This is a {num_days}-day trip with {len(requested_areas)} requested areas. "
            f"Distribute them across the days as follows: {', '.join(area_assignments)}."
        )

    lines.append(
        "If you cannot find enough sightseeing POIs for an area, use cafes, restaurants, shops, or cultural spaces from Google Places."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DSPy signatures
# ---------------------------------------------------------------------------

class ItineraryPlanner(dspy.Signature):
    """Generate a personalized Seoul travel itinerary for foreign tourists.

    You are given:
    1. the user's trip details,
    2. a shortlist of candidate courses from Visit Seoul / Visit Korea,
    3. real-time Google Places data for requested neighborhoods.

    Build a realistic day-by-day itinerary following ALL rules below.

    STRUCTURE RULES:
    - One day entry per requested trip duration day.
    - Each day MUST have 5–8 POIs. Never fewer than 5.
    - Each day MUST include at least one restaurant or cafe POI.
    - Arrange POIs in chronological visit order starting around 09:00–10:00.
    - Total planned activity + travel time per day should be 7–10 hours.

    REQUESTED AREA RULES:
    - If the user mentions multiple neighborhoods, cover ALL requested neighborhoods.
    - Include at least 2 POIs from EACH requested neighborhood across the itinerary.
    - For a 2-day trip with Hongdae and Seongsu, Day 1 can focus on Hongdae/Mangwon and Day 2 MUST focus on Seongsu.
    - Do not say "no relevant POI data was available" if Google Places data is provided for that area.
    - If candidate course data lacks a requested area, use Google Places supplement for that requested area.

    ANCHOR COURSE RULES:
    - Sections marked `=== DAY M–N CANDIDATES ===` define which days that group belongs to.
    - Sections marked `[ANCHOR COURSE]` are editorially curated sequences from Visit Seoul / Visit Korea.
    - Use the anchor course's POI order as the backbone for that day's itinerary.
    - You may drop POIs from an anchor course if they are irrelevant to the user's purpose.
    - You may insert `[SUPPLEMENT POIs]` or Google Places POIs into the sequence at appropriate positions.
    - Do NOT reorder anchor course POIs unless geography requires it.
    - When a section spans multiple days (e.g. DAY 1–2), distribute its anchor courses across those days; do not put all POIs into one day.

    CONTENT RULES:
    - Prioritize POIs that match the user's purpose.
      * cafe or coffee -> include cafes from Google Places
      * shopping -> include markets, streets, malls, fashion shops
      * K-POP, kpop, BTS, BLACKPINK, idol -> include kpop_landmark POIs and Google Places K-POP spots
      * local culture -> include markets, streets, local neighborhoods, cultural spaces
      * relaxing -> include parks, riverside spots, cafes, healing spaces
    - Honor dietary restrictions strictly.
    - Stay within the user's budget.
    - Notes must explain why the POI fits the user's purpose and include practical/cultural tips when relevant.

    GEOGRAPHY RULES:
    - Each day should stay within 1–2 adjacent neighborhoods.
    - Good pairs: Hongdae+Mangwon, Hongdae+Hapjeong, Seongsu+Wangsimni, Gangnam+Sinsa, Jongno+Insadong.
    - Do NOT mix distant areas in one day unless unavoidable.
    - Order POIs geographically to minimize backtracking.

    DATA INTEGRITY RULES:
    - Use ONLY POIs that appear in candidate_courses or REAL-TIME GOOGLE PLACES DATA.
    - Do NOT invent generic POIs such as "Hongdae Nightlife", "Street Food Stalls", or "Seongsu Cafe Street" unless they appear exactly in the data.
    - Copy name, lat, lng, and address from the provided data.
    - For cafes, restaurants, shopping, and K-POP, prefer Google Places because it provides real current places.
    - Only list a course in sources if you used at least one POI from that course.

    Return ONLY valid JSON with no markdown fences:
    {
      "summary": "<2-3 sentence overview mentioning all requested neighborhoods>",
      "days": [
        {
          "day": 1,
          "theme": "<short day theme>",
          "pois": [
            {
              "name": "<POI name exactly as provided>",
              "type": "<poi_type>",
              "address": "<address from provided data>",
              "lat": <number>,
              "lng": <number>,
              "stay_minutes": <integer>,
              "notes": "<purpose fit + cultural/practical tips>"
            }
          ],
          "estimated_cost": "<realistic day cost>"
        }
      ],
      "sources": [
        {
          "course_id": "<exact course_id>",
          "course_title": "<exact course_title>",
          "source": "<Visit Seoul or Visit Korea>",
          "source_url": "<exact source_url>"
        }
      ]
    }
    """

    duration: str = dspy.InputField(desc="Trip length, e.g. '2 days'.")
    location: str = dspy.InputField(desc="Destination or requested neighborhoods.")
    budget: str = dspy.InputField(desc="Total trip budget.")
    dietary: str = dspy.InputField(desc="Dietary restrictions or preferences.")
    purpose: str = dspy.InputField(desc="Trip purpose, e.g. cafes, shopping, K-POP.")
    candidate_courses: str = dspy.InputField(
        desc="Candidate courses and Google Places supplement as compact text."
    )
    itinerary_json: str = dspy.OutputField(
        desc="Strict JSON itinerary matching the schema."
    )


class FixJSON(dspy.Signature):
    """Repair a JSON document that failed to parse.

    Output ONLY the corrected JSON object. No prose, no markdown fences.
    Preserve all fields and values from the broken input; only fix syntax.
    """
    broken_json: str = dspy.InputField(desc="Malformed JSON text.")
    error_message: str = dspy.InputField(desc="Parser error.")
    fixed_json: str = dspy.OutputField(desc="Strictly valid JSON only.")


_planner: dspy.Predict | None = None
_fixer: dspy.Predict | None = None


def get_planner() -> dspy.Predict:
    global _planner
    if _planner is None:
        _planner = dspy.Predict(ItineraryPlanner)
    return _planner


def get_fixer() -> dspy.Predict:
    global _fixer
    if _fixer is None:
        _fixer = dspy.Predict(FixJSON)
    return _fixer


# ---------------------------------------------------------------------------
# Candidate formatting
# ---------------------------------------------------------------------------

def _format_one_course(
    c: dict[str, Any],
    idx: int,
    restrict_area: str | None = None,
) -> str:
    title = c.get("course_title", "")
    course_id = c.get("course_id", "")
    source = c.get("source", "")
    source_url = c.get("source_url", "")
    themes = c.get("theme_category", [])
    themes_str = ", ".join(themes) if isinstance(themes, list) else str(themes or "")

    poi_lines: list[str] = []
    for p in c.get("sequence", []) or []:
        # Same exclusion as _build_candidate_pool -- don't even show the LLM an
        # activity-category label, a bare subway-station marker, or a venue
        # flagged for naming review as if it were a plannable destination.
        if p.get("is_generic_activity") or p.get("is_transit_marker") or p.get("requires_review"):
            continue

        name = p.get("poi_name", "")
        address = p.get("address_en") or p.get("address_ko", "")
        lat = p.get("lat")
        lng = p.get("lng")
        area = _infer_area_from_text_or_coords(name, address, lat, lng) or ""

        # Anchor courses are whole-city itineraries; when this block belongs to a
        # specific requested area, drop POIs that clearly sit in a different area
        # so the day's candidate list stays area-pure. POIs whose area can't be
        # inferred are kept (benefit of the doubt).
        if restrict_area and area and not _area_matches_requested(area, restrict_area):
            continue

        poi_lines.append(
            f"    - {name} "
            f"[{p.get('poi_type', '')}] "
            f"area={area} "
            f"addr={address} "
            f"lat={lat} lng={lng} "
            f"stay={p.get('estimated_stay_time')}min"
        )

    return (
        f"Course {idx}: {title}\n"
        f"  course_id : {course_id}\n"
        f"  source    : {source}\n"
        f"  source_url: {source_url}\n"
        f"  Themes    : {themes_str}\n"
        f"  POIs:\n" + "\n".join(poi_lines)
    )


def _format_one_poi(poi: dict[str, Any]) -> str:
    # Same exclusion as _build_candidate_pool / _format_one_course -- return
    # "" for anything flagged as not a real plannable destination so it never
    # reaches the LLM prompt. Caller skips empty lines.
    if poi.get("is_generic_activity") or poi.get("is_transit_marker") or poi.get("requires_review"):
        return ""

    name = poi.get("poi_name", "")
    address = poi.get("address_en") or poi.get("address_ko", "")
    lat = poi.get("lat")
    lng = poi.get("lng")
    area = _infer_area_from_text_or_coords(name, address, lat, lng) or ""
    source_str = (
        f" course_id={poi['course_id']} source_url={poi['source_url']}"
        if poi.get("source_url")
        else ""
    )
    return (
        f"  - {name} "
        f"[{poi.get('poi_type', '')}] "
        f"area={area} "
        f"addr={address} "
        f"lat={lat} lng={lng} "
        f"stay={poi.get('estimated_stay_time')}min"
        f"{source_str}"
    )


def _format_segment_block(seg: dict[str, Any]) -> str:
    days = seg.get("day_numbers") or []
    if not days:
        return ""
    day_label = f"DAY {days[0]}" if len(days) == 1 else f"DAY {days[0]}–{days[-1]}"

    area = seg.get("area")
    purpose_hint = (seg.get("purpose_hint") or "").strip()
    if area:
        header = f"{_area_label(area)} - {purpose_hint}" if purpose_hint else _area_label(area)
    else:
        header = purpose_hint or "Seoul"

    lines: list[str] = [f"=== {day_label} CANDIDATES: {header} ==="]

    anchors = seg.get("anchor_courses") or []
    rendered: list[str] = []
    for i, c in enumerate(anchors, start=1):
        block = _format_one_course(c, i, restrict_area=area)
        # Drop a course that has no POIs left in this area after filtering.
        if block.rstrip().endswith("POIs:"):
            continue
        rendered.append(block)

    if rendered:
        lines.append("")
        lines.append("[ANCHOR COURSE — use sequence as the day backbone if relevant]")
        lines.extend(rendered)
    else:
        lines.append("")
        lines.append("[ANCHOR COURSE — none available; rely on supplement POIs + Google Places]")

    suppl = seg.get("supplement_pois") or []
    if suppl:
        rendered_pois = [line for poi in suppl if (line := _format_one_poi(poi))]
        if rendered_pois:
            lines.append("")
            lines.append("[SUPPLEMENT POIs — individual additions for gaps in anchor courses]")
            lines.extend(rendered_pois)

    return "\n".join(lines)


def _format_courses_for_prompt(
    courses: list[dict[str, Any]],
    google_supplement: list[dict[str, Any]] | None = None,
    requested_areas: list[str] | None = None,
    duration: str = "",
    num_days: int | None = None,
    day_segments: list[dict[str, Any]] | None = None,
) -> str:
    requested_areas = requested_areas or []

    if day_segments:
        blocks = [b for b in (_format_segment_block(s) for s in day_segments) if b]
        result = "\n\n".join(blocks)
    else:
        # Legacy flat format — kept so callers without segments still work.
        blocks = [_format_one_course(c, i) for i, c in enumerate(courses, start=1)]
        result = "\n\n".join(blocks)

    result += _format_requested_area_rules(requested_areas, duration, num_days=num_days)

    if google_supplement:
        result += _format_google_supplement(google_supplement)

    return result


# ---------------------------------------------------------------------------
# Candidate pool and validation
# ---------------------------------------------------------------------------

def _poi_from_course_item(p: dict[str, Any]) -> dict[str, Any]:
    name = p.get("poi_name") or p.get("name") or ""
    address = p.get("address_en") or p.get("address_ko") or p.get("address") or ""
    area = _infer_area_from_text_or_coords(name, address, p.get("lat"), p.get("lng"))

    return {
        "name": name,
        "type": p.get("poi_type") or p.get("type") or "tourist_spot",
        "address": address,
        "lat": p.get("lat"),
        "lng": p.get("lng"),
        "stay_minutes": int(float(p.get("estimated_stay_time") or p.get("stay_minutes") or 60)),
        "notes": "",
        "area": area,
        "source_kind": "course",
        # Mirrors critic_repair.candidate_from_course_poi -- these three flags
        # mark POIs that aren't real visitable destinations (activity-category
        # labels like "Karaoke", pure subway-station markers, or venues whose
        # naming needs manual review). _build_candidate_pool excludes anything
        # with one of these set so it can never be planned/auto-filled in.
        "is_generic_activity": bool(p.get("is_generic_activity")),
        "is_transit_marker": bool(p.get("is_transit_marker")),
        "requires_review": bool(p.get("requires_review")),
    }


def _poi_from_google_item(p: dict[str, Any]) -> dict[str, Any]:
    area = p.get("area") or _infer_area_from_text_or_coords(
        p.get("poi_name"),
        p.get("address_en") or p.get("address_ko"),
        p.get("lat"),
        p.get("lng"),
    )

    return {
        "name": p.get("poi_name", ""),
        "type": p.get("poi_type", "tourist_spot"),
        "address": p.get("address_en") or p.get("address_ko") or "",
        "lat": p.get("lat"),
        "lng": p.get("lng"),
        "stay_minutes": int(float(p.get("estimated_stay_time") or 60)),
        "notes": _google_note_for_type(p),
        "area": area,
        "source_kind": "google",
    }


def _google_note_for_type(p: dict[str, Any]) -> str:
    ptype = p.get("poi_type", "")
    area = _area_label(p.get("area", ""))
    rating = p.get("rating")
    rating_text = f" It has a Google rating of {rating}." if rating else ""

    if ptype == "cafe":
        return f"Verified cafe in {area}; good for cafe hopping and a relaxed break.{rating_text}"
    if ptype == "restaurant":
        return f"Verified restaurant in {area}; useful for a clear meal slot in the itinerary.{rating_text}"
    if ptype == "kpop_landmark":
        return f"Verified K-POP related place around {area}; fits the user's interest in idols and Hallyu culture.{rating_text}"
    if ptype in {"shopping_mall", "shopping"}:
        return f"Verified shopping spot in {area}; fits shopping and local trend exploration.{rating_text}"
    return f"Verified Google Places POI in {area}.{rating_text}"


def _build_candidate_pool(
    courses: list[dict[str, Any]],
    google_supplement: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    pool: dict[str, dict[str, Any]] = {}

    for c in courses:
        for raw in c.get("sequence", []) or []:
            item = _poi_from_course_item(raw)
            if (
                item.get("is_generic_activity")
                or item.get("is_transit_marker")
                or item.get("requires_review")
            ):
                # Not a real, plannable destination -- keep it out of both the
                # LLM-picked and the programmatically-filled candidate set.
                continue
            key = _normalize_text(item["name"])
            if key:
                pool[key] = item

    for raw in google_supplement or []:
        item = _poi_from_google_item(raw)
        key = _normalize_text(item["name"])
        if key:
            pool[key] = item

    return pool


def _as_output_poi(item: dict[str, Any], extra_note: str | None = None) -> dict[str, Any]:
    notes = item.get("notes") or ""
    if extra_note:
        notes = f"{notes} {extra_note}".strip()

    return {
        "name": item.get("name", ""),
        "type": item.get("type", "tourist_spot"),
        "address": item.get("address", ""),
        "lat": item.get("lat"),
        "lng": item.get("lng"),
        "stay_minutes": int(float(item.get("stay_minutes") or 60)),
        "notes": notes,
        "area": item.get("area"),
    }


def _poi_area(poi: dict[str, Any]) -> str | None:
    if poi.get("area"):
        return str(poi.get("area")).lower()
    return _infer_area_from_text_or_coords(
        poi.get("name"),
        poi.get("address"),
        poi.get("lat"),
        poi.get("lng"),
    )


def _belongs_to_other_requested_area(
    poi_area: str | None,
    target_area: str | None,
    requested_areas: list[str],
) -> bool:
    """True if the POI clearly belongs to a requested area other than the day's.

    Used to keep the global fallback fillers from dragging (e.g.) Gangnam POIs
    into the Hongdae day when an area-specific candidate runs short.
    """
    if not poi_area:
        return False
    for area in requested_areas:
        if area == target_area:
            continue
        if _area_matches_requested(poi_area, area):
            return True
    return False


def _is_meal_poi(poi: dict[str, Any]) -> bool:
    ptype = _normalize_text(poi.get("type"))
    name = _normalize_text(poi.get("name"))
    return (
        ptype in {"restaurant", "cafe", "market", "food", "meal_takeaway"}
        or "restaurant" in ptype
        or "cafe" in ptype
        or "coffee" in name
    )


def _candidate_items_for_area(
    pool: dict[str, dict[str, Any]],
    area: str,
    *,
    preferred_types: set[str] | None = None,
    exclude_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    exclude_names = exclude_names or set()
    preferred_types = preferred_types or set()

    items: list[dict[str, Any]] = []

    for item in pool.values():
        name_key = _normalize_text(item.get("name"))
        if name_key in exclude_names:
            continue

        item_area = item.get("area")
        if not _area_matches_requested(item_area, area):
            continue

        if preferred_types:
            ptype = _normalize_text(item.get("type"))
            if not any(t in ptype for t in preferred_types):
                continue

        items.append(item)

    # Prefer Google Places and higher relevance.
    def sort_key(x: dict[str, Any]) -> tuple[int, int]:
        source_score = 0 if x.get("source_kind") == "google" else 1
        type_score = 0
        ptype = _normalize_text(x.get("type"))
        if ptype in {"cafe", "restaurant", "kpop_landmark", "shopping_mall", "shopping"}:
            type_score = -1
        return (source_score, type_score)

    return sorted(items, key=sort_key)


def _generate_day_theme(day: dict[str, Any], area: str | None, purpose: str) -> str:
    """Build a short, descriptive day theme from the day's POIs and primary area."""
    pois = day.get("pois") or []
    area_label = _area_label(area) if area else "Seoul"

    # Tally POI types to pick the dominant activity.
    type_counts: dict[str, int] = {}
    for poi in pois:
        ptype = _normalize_text(poi.get("type") or "")
        type_counts[ptype] = type_counts.get(ptype, 0) + 1

    dominant = max(type_counts, key=lambda t: type_counts[t]) if type_counts else ""

    # Map dominant type → evocative descriptor.
    type_descriptors: dict[str, str] = {
        "cafe": "Café Hopping",
        "restaurant": "Food & Flavours",
        "kpop_landmark": "K-POP & Hallyu",
        "shopping_mall": "Shopping & Trends",
        "shopping": "Shopping & Trends",
        "market": "Markets & Local Life",
        "tourist_spot": "Sightseeing",
        "cultural_site": "Culture & Heritage",
        "park": "Parks & Relaxation",
        "museum": "Art & Museums",
        "entertainment": "Entertainment",
    }

    descriptor = type_descriptors.get(dominant, "Exploration")

    # Check for special combos.
    has_cafe = type_counts.get("cafe", 0) > 0
    has_kpop = type_counts.get("kpop_landmark", 0) > 0
    has_shop = type_counts.get("shopping", 0) + type_counts.get("shopping_mall", 0) > 0
    has_food = type_counts.get("restaurant", 0) > 0

    if has_kpop and has_shop:
        descriptor = "K-POP & Shopping"
    elif has_kpop and has_cafe:
        descriptor = "K-POP & Café Culture"
    elif has_cafe and has_shop:
        descriptor = "Cafés & Shopping"
    elif has_cafe and has_food:
        descriptor = "Cafés & Local Eats"

    return f"{area_label}: {descriptor}"


def _validate_and_repair_itinerary(
    itinerary: dict[str, Any],
    *,
    courses: list[dict[str, Any]],
    google_supplement: list[dict[str, Any]],
    requested_areas: list[str],
    duration: str = "",
    num_days: int | None = None,
    pace: str | None = None,
    purpose: str = "",
) -> dict[str, Any]:
    """Remove hallucinations and force requested area coverage."""
    poi_min, poi_max = _pace_bounds({"pace": pace})
    pool = _build_candidate_pool(courses, google_supplement)
    valid_names = set(pool.keys())
    used_names: set[str] = set()

    days = itinerary.get("days") or []
    if not isinstance(days, list):
        days = []
    itinerary["days"] = days

    # 0. Ensure the itinerary has the correct number of days.
    expected_days = _parse_num_days(duration, override=num_days) if (duration or num_days) else 0
    if expected_days > 0 and len(days) < expected_days:
        existing_day_nums = {int(d.get("day") or 0) for d in days}
        for day_num in range(1, expected_days + 1):
            if day_num not in existing_day_nums:
                days.append({"day": day_num, "theme": f"Day {day_num}", "pois": [], "estimated_cost": ""})
                print(f"[Validator] Day {day_num} 누락 -- 빈 일정 추가 (duration={duration})")
        # Keep days sorted by day number.
        days.sort(key=lambda d: int(d.get("day") or 0))

    # 0b. Cap to the requested number of days. The planner LLM sometimes
    # over-produces day entries (e.g. 22 days for a 2-day trip). Keep the first
    # `expected_days` days and fold any overflow POIs back into them.
    #
    # Each overflow POI goes to whichever kept day currently has the fewest
    # POIs (not round-robin by position). Round-robin assumes the kept days
    # started out evenly sized, which isn't true when expected_days is small
    # (or mis-parsed) and/or the kept days were already lopsided going in --
    # in the worst case (expected_days==1) round-robin has no choice but to
    # dump every overflow POI into that single day. Always filling the
    # currently-smallest day makes the final sizes as balanced as the day
    # count allows, no matter how skewed the input was.
    if expected_days > 0 and len(days) > expected_days:
        days.sort(key=lambda d: int(d.get("day") or 0))
        kept = days[:expected_days]
        for d in kept:
            d.setdefault("pois", [])
        overflow_pois = [
            poi for d in days[expected_days:] for poi in (d.get("pois") or [])
        ]
        for poi in overflow_pois:
            target = min(kept, key=lambda d: len(d["pois"]))
            target["pois"].append(poi)
        # Renumber kept days 1..expected_days so day labels stay contiguous.
        for idx, d in enumerate(kept, start=1):
            d["day"] = idx
        print(
            f"[Validator] {len(days)}일 생성됨 -> {expected_days}일로 축소 "
            f"(overflow POI {len(overflow_pois)}개 재배치, duration={duration})"
        )
        days = kept
        itinerary["days"] = days

    # 1. Remove hallucinated POIs.
    for day in days:
        original = day.get("pois") or []
        valid_pois: list[dict[str, Any]] = []
        removed: list[str] = []

        for poi in original:
            name_key = _normalize_text(poi.get("name"))
            if name_key in valid_names:
                # Normalize with canonical candidate data if possible.
                candidate = pool[name_key]
                out = _as_output_poi(candidate)
                # Preserve the model's note if useful.
                if poi.get("notes"):
                    out["notes"] = poi.get("notes")
                valid_pois.append(out)
                used_names.add(name_key)
            else:
                removed.append(str(poi.get("name", "")))

        if removed:
            print(f"[Validator] Day {day.get('day')} hallucinated POI 제거: {removed}")

        day["pois"] = valid_pois

    # 2. Force requested area coverage.
    if requested_areas and days:
        coverage = _area_coverage(days, requested_areas)

        for idx, area in enumerate(requested_areas):
            current_count = coverage.get(area, 0)
            if current_count >= 2:
                continue

            target_day_idx = min(idx, len(days) - 1)
            target_day = days[target_day_idx]

            needed = 2 - current_count
            candidates = _candidate_items_for_area(
                pool,
                area,
                exclude_names=used_names,
            )

            inserted = 0
            for item in candidates:
                if inserted >= needed:
                    break
                out = _as_output_poi(
                    item,
                    extra_note=f"Added to ensure the itinerary covers the requested area: {_area_label(area)}."
                )
                target_day.setdefault("pois", []).append(out)
                used_names.add(_normalize_text(out.get("name")))
                inserted += 1

            if inserted:
                print(f"[Validator] {_area_label(area)} 누락 보완: {inserted}개 POI 추가")

    # 3. Ensure each day has a meal slot.
    for day in days:
        pois = day.setdefault("pois", [])
        if any(_is_meal_poi(p) for p in pois):
            continue

        day_area = _primary_area_for_day(day, requested_areas)
        candidates = _candidate_items_for_area(
            pool,
            day_area,
            preferred_types={"restaurant", "cafe"},
            exclude_names=used_names,
        ) if day_area else []

        if not candidates:
            candidates = [
                item for item in pool.values()
                if _normalize_text(item.get("name")) not in used_names
                and _normalize_text(item.get("type")) in {"restaurant", "cafe"}
                and not _belongs_to_other_requested_area(
                    item.get("area"), day_area, requested_areas
                )
            ]

        if candidates:
            item = candidates[0]
            out = _as_output_poi(item, extra_note="Added as a clear meal or cafe slot.")
            insert_idx = min(2, len(pois))
            pois.insert(insert_idx, out)
            used_names.add(_normalize_text(out.get("name")))
            print(f"[Validator] Day {day.get('day')} 식사 슬롯 추가: {out.get('name')}")

    # 4. Fill under-populated days up to the pace's minimum POI count.
    for idx, day in enumerate(days):
        pois = day.setdefault("pois", [])
        if len(pois) >= poi_min:
            continue

        target_area = None
        if requested_areas:
            target_area = requested_areas[min(idx, len(requested_areas) - 1)]
        target_area = target_area or _primary_area_for_day(day, requested_areas)

        candidates = []
        if target_area:
            candidates = _candidate_items_for_area(
                pool,
                target_area,
                exclude_names=used_names,
            )

        if not candidates:
            candidates = [
                item for item in pool.values()
                if _normalize_text(item.get("name")) not in used_names
                and not _belongs_to_other_requested_area(
                    item.get("area"), target_area, requested_areas
                )
            ]

        while len(pois) < poi_min and candidates:
            item = candidates.pop(0)
            out = _as_output_poi(item, extra_note="Added to make the day sufficiently complete.")
            pois.append(out)
            used_names.add(_normalize_text(out.get("name")))
            print(f"[Validator] Day {day.get('day')} POI 수 보완: {out.get('name')}")

    # 4b. Trim over-populated days down to the pace's maximum POI count. Runs
    # after area coverage (2) and the meal slot (3) so trimming never has to
    # undo what those steps just added, and after the min-fill (4) since
    # trimming first would be pointless when a day is still under min.
    #
    # Always protects: every meal-slot POI (the same _is_meal_poi check step 3
    # uses) and at least one POI per requested area already present in the
    # day (so the day keeps the area coverage step 2 just secured). If the
    # protected set alone is already at or over the max, coverage wins --
    # nothing is cut, only logged.
    #
    # Cut order for the rest: POIs whose area duplicates an area that's
    # already protected go first (they add the least additional coverage);
    # once those are exhausted, remaining excess is cut from the back of the
    # day's POI list.
    for day in days:
        pois = day.get("pois") or []
        if len(pois) <= poi_max:
            continue

        protected_idx: set[int] = {i for i, p in enumerate(pois) if _is_meal_poi(p)}
        protected_areas: set[str] = set()
        for i, p in enumerate(pois):
            area = _poi_area(p)
            if not area:
                continue
            matched_req = next((req for req in requested_areas if _area_matches_requested(area, req)), None)
            if matched_req and matched_req not in protected_areas:
                protected_idx.add(i)
                protected_areas.add(matched_req)

        excess = len(pois) - poi_max
        removable = [i for i in range(len(pois)) if i not in protected_idx]
        if len(removable) < excess:
            print(
                f"[Validator] Day {day.get('day')} POI {len(pois)}개가 상한({poi_max}) 초과지만 "
                f"보존 대상(식사 슬롯/지역 커버리지)만으로 이미 여유가 없어 자르지 않음"
            )
            continue

        protected_area_set = {_poi_area(pois[i]) for i in protected_idx if _poi_area(pois[i])}
        dup_of_protected_area = [i for i in removable if _poi_area(pois[i]) in protected_area_set]
        unique_area = [i for i in removable if i not in dup_of_protected_area]

        to_remove: set[int] = set()
        for i in sorted(dup_of_protected_area, reverse=True):
            if len(to_remove) >= excess:
                break
            to_remove.add(i)
        if len(to_remove) < excess:
            for i in sorted(unique_area, reverse=True):
                if len(to_remove) >= excess:
                    break
                to_remove.add(i)

        removed_names = [pois[i].get("name") for i in sorted(to_remove)]
        day["pois"] = [p for i, p in enumerate(pois) if i not in to_remove]
        print(
            f"[Validator] Day {day.get('day')} POI 상한({poi_max}) 초과 -- "
            f"{len(to_remove)}개 제거: {removed_names}"
        )

    # 5. Reorder each day lightly by area grouping, preserving the LLM order mostly.
    for day in days:
        day["pois"] = day.get("pois") or []

    # 5b. Generate a meaningful theme for any day that still has a placeholder title.
    for idx, day in enumerate(days):
        current_theme = (day.get("theme") or "").strip()
        day_num = int(day.get("day") or idx + 1)
        # Only replace bare "Day N" placeholders — never overwrite LLM-generated titles.
        if current_theme in ("", f"Day {day_num}"):
            area = None
            if requested_areas:
                area = requested_areas[min(idx, len(requested_areas) - 1)]
            area = area or _primary_area_for_day(day, requested_areas)
            day["theme"] = _generate_day_theme(day, area, purpose=purpose)

    # 6. Attach transit legs (Haversine distance + walk/car ETA + Kakao deep links).
    for day in days:
        day["transit_legs"] = compute_transit_legs(day.get("pois") or [])

    itinerary["requested_areas"] = requested_areas
    itinerary["area_coverage"] = _area_coverage(days, requested_areas)

    return itinerary


def _area_coverage(days: list[dict[str, Any]], requested_areas: list[str]) -> dict[str, int]:
    coverage = {area: 0 for area in requested_areas}
    for day in days:
        for poi in day.get("pois", []) or []:
            area = _poi_area(poi)
            for req in requested_areas:
                if _area_matches_requested(area, req):
                    coverage[req] += 1
    return coverage


def _primary_area_for_day(day: dict[str, Any], requested_areas: list[str]) -> str | None:
    if requested_areas:
        day_num = int(day.get("day") or 1)
        idx = min(max(day_num - 1, 0), len(requested_areas) - 1)
        return requested_areas[idx]

    counts: dict[str, int] = {}
    for poi in day.get("pois", []) or []:
        area = _poi_area(poi)
        if area:
            counts[area] = counts.get(area, 0) + 1

    if not counts:
        return None

    return max(counts.items(), key=lambda x: x[1])[0]


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _isolate_json_object(text: str) -> str:
    text = _FENCE_RE.sub("", text or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    return text


def _simple_repair(text: str) -> str:
    text = (
        text.replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
    )
    text = _TRAILING_COMMA_RE.sub(r"\1", text)
    return text


def _parse_itinerary_json(raw: str, *, use_llm_fallback: bool = True) -> dict[str, Any]:
    isolated = _isolate_json_object(raw)

    try:
        return json.loads(isolated)
    except json.JSONDecodeError as first_err:
        repaired = _simple_repair(isolated)

    try:
        return json.loads(repaired)
    except json.JSONDecodeError as second_err:
        if use_llm_fallback:
            try:
                fix_prompt = (
                    "Repair this malformed JSON document. "
                    "Return ONLY the corrected JSON object, no prose, no markdown fences.\n\n"
                    f"Error: {second_err}\n\n"
                    f"Broken JSON:\n{isolated[:8000]}"
                )
                fixed = _gemini_text(fix_prompt)
                return json.loads(_isolate_json_object(fixed))
            except Exception:
                pass

        _dump_debug(raw)
        raise second_err from first_err


def _dump_debug(raw: str) -> None:
    try:
        dbg_path = Path(__file__).resolve().parent / "planner_last_failed.txt"
        dbg_path.write_text(raw or "", encoding="utf-8")
        print(f"[planner] wrote failing output to {dbg_path}")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Sources hygiene
# ---------------------------------------------------------------------------

def _normalize_sources(
    itinerary: dict[str, Any],
    retrieved: list[dict[str, Any]],
) -> dict[str, Any]:
    by_id = {c.get("course_id"): c for c in retrieved if c.get("course_id")}
    by_url = {c.get("source_url"): c for c in retrieved if c.get("source_url")}

    raw_sources = itinerary.get("sources") or []
    cleaned: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for s in raw_sources:
        if not isinstance(s, dict):
            continue

        match = by_id.get(s.get("course_id")) or by_url.get(s.get("source_url"))
        if not match:
            continue

        cid = match.get("course_id")
        if not cid or cid in seen_ids:
            continue

        seen_ids.add(cid)
        cleaned.append({
            "course_id": cid,
            "course_title": match.get("course_title", ""),
            "source": match.get("source", ""),
            "source_url": match.get("source_url", ""),
        })

    if not cleaned and retrieved:
        for c in retrieved:
            if c.get("source_url"):
                cleaned.append({
                    "course_id": c.get("course_id"),
                    "course_title": c.get("course_title", ""),
                    "source": c.get("source", ""),
                    "source_url": c.get("source_url", ""),
                })

    itinerary["sources"] = cleaned
    return itinerary


def _resolve_num_days(state: TravelState) -> int | None:
    """A structured `state["num_days"]`, or None to signal "not set -- fall
    back to parsing state['travel_dates'] text".

    No current caller sets `state["num_days"]`: graph.collect_node's date
    picker flow (see `_describe_trip`) instead bakes the day count as a
    "(N days)" suffix straight into `travel_dates`, which the normal
    `_parse_num_days` text-parsing path already reads correctly -- so this
    resolves to None in practice today, and callers fall through to that
    path. Kept as a seam (not removed) so a future structured day-count
    input can be wired in here without touching every call site again.

    If `state["num_days"]` ever IS set but invalid (0, negative), it does
    NOT fall back to text parsing: a structured field being present at all
    would mean travel_dates text may be absent or stale, so it falls back to
    a safe flat default (3) instead.
    """
    num_days = state.get("num_days")
    if num_days is None:
        return None
    if isinstance(num_days, int) and num_days > 0:
        return num_days
    return 3


def _pace_bounds(state: TravelState) -> tuple[int, int]:
    """Single source of truth for the per-day POI count target driven by
    trip pace (relaxed/packed): both the LLM prompt guidance
    (`_pace_target_line`) and `_validate_and_repair_itinerary`'s fill/trim
    steps read the (min, max) from here, so the prompt and the validator can
    never end up quoting different numbers."""
    pace = (state.get("pace") or "").strip().lower()
    if pace == "relaxed":
        return (5, 6)
    if pace == "packed":
        return (7, 8)
    return (6, 7)  # no pace on record -- a middling default, not a guess at either extreme


_PACE_LABELS: dict[str, str] = {"packed": "packed schedule", "relaxed": "relaxed pace"}


def _pace_target_line(state: TravelState) -> str:
    """Extra prompt line steering the LLM's per-day POI count toward the
    user's trip_style. Kept out of the ItineraryPlanner docstring (which is
    shared/static across every call) since the target varies per request.
    Silent (no line) when pace is unset/unrecognized -- the LLM falls back to
    the docstring's plain 5-8 rule, and the validator's default bounds (6-7,
    see _pace_bounds) still apply underneath it regardless."""
    pace = (state.get("pace") or "").strip().lower()
    if pace not in _PACE_LABELS:
        return ""
    lo, hi = _pace_bounds(state)
    return (
        f"PACE: {_PACE_LABELS[pace]} -- aim for {lo}-{hi} POIs per day "
        f"(never fewer than {lo}, never more than {hi})."
    )


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

def make_retrieve_node(api_key: str):
    set_planner_api_key(api_key)

    def retrieve_node(state: TravelState) -> TravelState:
        segments = parse_day_segments(
            location=state.get("region") or "",
            purpose=state.get("category") or "",
            duration=state.get("travel_dates") or "",
            num_days=_resolve_num_days(state),
        )

        try:
            segments_with_data, all_courses = retrieve_for_segments(
                api_key=api_key,
                segments=segments,
                purpose=state.get("category") or "",
            )
        except Exception as e:
            # ponytail: no **state spread — returning a replacement messages list
            # (not just the new message) would overwrite the checkpoint history.
            return {
                "current_step": "confirm",
                "messages": [AIMessage(content=f"⚠️ Failed to retrieve courses: {e}")],
            }

        return {
            **state,
            "retrieved_courses": all_courses,
            "day_segments": segments_with_data,
            "current_step": "planning",
        }

    return retrieve_node


def plan_node(state: TravelState) -> TravelState:
    courses = state.get("retrieved_courses") or []
    day_segments = state.get("day_segments")
    if not courses:
        return {
            **state,
            "current_step": "done",
            "messages": [AIMessage(content="⚠️ No candidate courses found. Try different details.")],
        }

    location = state.get("region") or ""
    purpose = state.get("category") or ""
    duration = state.get("travel_dates") or ""
    num_days = _resolve_num_days(state)
    pace = state.get("pace")
    budget = ""
    dietary = state.get("restrictions") or "none"

    # Only matters if num_days is ever set (see _resolve_num_days) while
    # travel_dates text is empty/stale -- surfaces the day count to the LLM
    # explicitly instead of letting it guess from blank duration text. In
    # today's flow duration is always the picker's own "... (N days)" string
    # by the time plan_node runs, so this is a no-op fallback, not the
    # common path.
    duration_text = duration or (f"{num_days} days" if num_days else "")

    requested_areas = _extract_requested_areas(location, purpose)
    print(f"[planner] requested_areas = {requested_areas}")

    google_supplement: list[dict[str, Any]] = []
    if GOOGLE_PLACES_API_KEY:
        google_supplement = build_google_supplement_by_areas(
            requested_areas=requested_areas,
            location=location,
            purpose=purpose,
            api_key=GOOGLE_PLACES_API_KEY,
        )
    else:
        print("[planner] GOOGLE_PLACES_API_KEY 없음 -- Google Places 보완 생략")

    prompt_context = _format_courses_for_prompt(
        courses,
        google_supplement=google_supplement,
        requested_areas=requested_areas,
        duration=duration,
        num_days=num_days,
        day_segments=day_segments,
    )

    try:
        system_prompt = ItineraryPlanner.__doc__ or ""
        pace_line = _pace_target_line(state)
        user_prompt = (
            f"{system_prompt}\n\n"
            f"Duration: {duration_text}\n"
            f"Location: {location}\n"
            f"Budget: {budget}\n"
            f"Dietary: {dietary}\n"
            f"Purpose: {purpose}\n"
            + (f"{pace_line}\n" if pace_line else "")
            + f"Candidate Courses:\n{prompt_context}"
        )
        raw_json = _gemini_text(user_prompt)

        itinerary = _parse_itinerary_json(raw_json)

        itinerary = _validate_and_repair_itinerary(
            itinerary,
            courses=courses,
            google_supplement=google_supplement,
            requested_areas=requested_areas,
            duration=duration,
            num_days=num_days,
            pace=pace,
            purpose=purpose,
        )

        itinerary = _normalize_sources(itinerary, courses)

    except json.JSONDecodeError as e:
        return {
            **state,
            "current_step": "done",
            "messages": [AIMessage(content=f"⚠️ Planner returned invalid JSON: {e}")],
        }
    except Exception as e:
        return {
            **state,
            "current_step": "done",
            "messages": [AIMessage(content=f"⚠️ Planning failed: {e}")],
        }

    summary = itinerary.get("summary", "")
    day_count = len(itinerary.get("days", []))
    area_text = ", ".join(_area_label(a) for a in requested_areas) if requested_areas else "Seoul"

    ack = (
        f"✅ Your {day_count}-day itinerary is ready!\n\n"
        f"{summary}\n\n"
        f"Requested area coverage checked: {area_text}.\n\n"
        "See the full plan below."
    )

    return {
        **state,
        "itinerary": itinerary,
        "planning_context": {
            "requested_areas": requested_areas,
            "google_supplement": google_supplement,
        },
        "current_step": "critic",
        "messages": [AIMessage(content=ack)],
    }
