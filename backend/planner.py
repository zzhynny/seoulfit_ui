"""Itinerary planning nodes for the LangGraph.

`retrieve_node` runs retrieval.select_anchors over the course dataset and
stashes each day's anchor courses in state. `plan_node` sends those courses +
the user's confirmed fields to Gemini and parses the structured day-by-day
itinerary back out.

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
import os
import random
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from langchain_core.messages import AIMessage
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree, tracing_context

import meal_slots
from date_utils import weekday_for_day
from geo import (
    AREA_ALIASES,
    DEFAULT_CENTER,
    SEOUL_AREA_CENTERS,
    area_label as _area_label,
    area_matches_requested as _area_matches_requested,
    haversine_km as _haversine_km,
    infer_area_from_fields as _infer_area_from_text_or_coords,
)
from rag import _parse_num_days
from retrieval import base_id, load_vectors, select_anchors
from state import TravelState

load_dotenv()

# ---------------------------------------------------------------------------
# Gemini key (set by make_retrieve_node via set_planner_api_key)
# ---------------------------------------------------------------------------

_PLANNER_GEMINI_KEY: str = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")


def set_planner_api_key(key: str) -> None:
    global _PLANNER_GEMINI_KEY
    _PLANNER_GEMINI_KEY = key


# Seconds before each retry of a rate-limited / overloaded Gemini call. With
# several travellers generating at once a 429 is the likeliest failure, and it
# clears in seconds. Jittered so a burst of users doesn't retry in lockstep.
# Worst case adds ~12s -- well inside the app's 180s generation timeout.
_GEMINI_RETRY_DELAYS = (2.0, 6.0)
_GEMINI_RETRYABLE = {429, 500, 503}


def _record_usage(response, model: str) -> None:
    """Hand Gemini's token counts to the enclosing llm span.

    @traceable can't read them off a raw google-genai response, so without this
    every span says 0 tokens and LangSmith can't price a trace.
    """
    rt = get_current_run_tree()
    u = getattr(response, "usage_metadata", None)
    if rt is None or u is None:
        return
    rt.metadata.update(ls_provider="google_genai", ls_model_name=model)
    rt.set(usage_metadata={
        "input_tokens": u.prompt_token_count or 0,
        "output_tokens": u.candidates_token_count or 0,
        "total_tokens": u.total_token_count or 0,
    })


@traceable(run_type="llm", name="itinerary_generation")
def _gemini_text(prompt: str) -> str:
    """Call Gemini and return raw text (JSON expected from caller)."""
    from google import genai as _genai
    from google.genai import errors as _errors
    client = _genai.Client(api_key=_PLANNER_GEMINI_KEY)
    for delay in (*_GEMINI_RETRY_DELAYS, None):
        try:
            response = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            _record_usage(response, "gemini-3.8-flash")
            return response.text or ""
        except _errors.APIError as e:
            if delay is None or e.code not in _GEMINI_RETRYABLE:
                raise
            print(f"[planner] Gemini {e.code}, retrying in ~{delay:.0f}s")
            time.sleep(delay * random.uniform(1.0, 1.5))
    raise AssertionError("unreachable")


# ---------------------------------------------------------------------------
# Google Places configuration
# ---------------------------------------------------------------------------

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")

# How many per-area / per-day fan-outs run at once. Each unit does its own
# short sequential chain of blocking HTTP calls, so this is also the ceiling on
# concurrent Places requests — 6 keeps a 7-day trip to roughly one round-trip's
# wait without leaning on anyone's QPS limit. Threads, not async: every fetcher
# below is blocking `requests`, which releases the GIL while it waits.
_FANOUT_WORKERS = 6

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
                "kakao_transit_url": None,
                "transit_options": [],
            })
            continue

        dist = _haversine_km(lat1, lng1, lat2, lng2)

        transit_options: list[dict[str, Any]] = []
        # A hop this short is a walk; asking ODsay about it only spends quota.
        if odsay_enabled and dist >= odsay.WALKABLE_KM:
            transit_options = odsay.fetch_odsay_options(lat1, lng1, lat2, lng2)

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
            # ODsay gives the lines and the fare but nothing to tap through
            # to, which left the subway/bus chips looking like buttons that
            # did nothing. Kakao's own transit route covers the same pair.
            "kakao_transit_url": _kakao_route_url(lat1, lng1, lat2, lng2, "publictransit"),
            "transit_options": transit_options,
        })
    return legs


# ---------------------------------------------------------------------------
# Google Places API
# ---------------------------------------------------------------------------

@traceable(
    run_type="tool",
    name="google_places",
    # `params` carries "key": api_key -- never let it reach LangSmith.
    process_inputs=lambda i: {
        "url": i.get("url"),
        "params": {k: v for k, v in (i.get("params") or {}).items() if k != "key"},
    },
    # A nearbysearch returns up to 20 results with geometry and photo refs;
    # names are what you actually read when a POI turns up unexpectedly.
    process_outputs=lambda o: {
        "status": o.get("status"),
        "count": len(o.get("results") or []),
        "names": [r.get("name") for r in (o.get("results") or [])],
    },
)
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
        return {"status": "REQUEST_ERROR", "error_message": str(e)}


def _stamp_true_area(
    places: list[dict[str, Any]], requested: str,
) -> list[dict[str, Any]]:
    """Re-derive each POI's area from its coordinates and drop the ones that
    aren't actually in (or adjacent to) `requested`.

    Both fetchers used to stamp `area=requested` on every hit without checking.
    Nearby Search's radius reaches _ANCHOR_RADIUS_MAX_M and Text Search's
    location is only a bias, so either can return a place in the next district
    -- Hongdae sweeps routinely surface Sinchon, which is not in Hongdae's
    adjacency set. The stamp then claimed otherwise, and the two consumers
    disagree about whether to believe it: _candidate_items_for_area trusts the
    stamp when backfilling coverage, while the critic's _evaluate_area_coverage
    re-infers from coordinates. So the validator would insert a "Hongdae" cafe
    that is really in Sinchon to clear REQUESTED_AREA_UNDER_COVERED, the critic
    would not count it, and repair would retry the same move.

    A POI whose area can't be inferred is kept with the requested stamp -- the
    same benefit of the doubt the generic branch has always given them.
    """
    kept: list[dict[str, Any]] = []
    for place in places:
        true_area = _infer_area_from_text_or_coords(
            place.get("poi_name"), place.get("address_en"),
            place.get("lat"), place.get("lng"),
        )
        if not true_area:
            kept.append(place)
            continue
        if not _area_matches_requested(true_area, requested):
            continue
        place["area"] = true_area
        kept.append(place)
    return kept


# Minutes a supplement stop is budgeted for, by poi_type. Cafes are a sit-down
# break, malls take a while to walk; everything else gets the planner's 60.
_STAY_MINUTES = {"cafe": 45, "shopping": 75, "shopping_mall": 75}


def fetch_nearby_places(
    *,
    area: str,
    place_type: str,
    api_key: str,
    radius: int = 1700,
    min_rating: float = 4.0,
    max_results: int = 5,
    center: tuple[float, float] | None = None,
) -> list[dict[str, Any]]:
    """Google Places Nearby Search for one area.

    `center` overrides the neighbourhood's hand-placed point -- see
    `_anchor_search_origin`, which centres the sweep on the day's own courses.
    """
    if not api_key:
        return []

    lat, lng = center or SEOUL_AREA_CENTERS.get(area, DEFAULT_CENTER)
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
    # Capped after _stamp_true_area below, not here: slicing first would let
    # out-of-area hits use up the budget and return short.
    for r in filtered:
        loc = (r.get("geometry") or {}).get("location") or {}
        if "lat" not in loc or "lng" not in loc:
            continue

        places.append({
            "poi_name": r.get("name", ""),
            "poi_type": place_type,
            "address_en": r.get("vicinity") or r.get("formatted_address", ""),
            "address_ko": r.get("vicinity") or r.get("formatted_address", ""),
            "lat": loc["lat"],
            "lng": loc["lng"],
            "rating": r.get("rating"),
            "estimated_stay_time": _STAY_MINUTES.get(place_type, 60),
            "source": f"Google Places ({_area_label(area)})",
            "area": area,
            "place_id": r.get("place_id", ""),
        })

    return _stamp_true_area(places, area)[:max_results]


def fetch_text_places(
    *,
    area: str,
    query: str,
    api_key: str,
    radius: int = 2500,
    min_rating: float = 0.0,
    max_results: int = 5,
    poi_type: str = "tourist_spot",
    center: tuple[float, float] | None = None,
) -> list[dict[str, Any]]:
    """Google Places Text Search for one area.

    `query` keeps naming the requested area: for Text Search the place name in
    the text is the precision mechanism and location/radius only bias it, so
    `center` refines where inside that area to look rather than replacing it.
    """
    if not api_key:
        return []

    lat, lng = center or SEOUL_AREA_CENTERS.get(area, DEFAULT_CENTER)
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
            "estimated_stay_time": _STAY_MINUTES.get(poi_type, 60),
            "source": f"Google Places Text ({_area_label(area)})",
            "area": area,
            "place_id": r.get("place_id", ""),
        })

    return _stamp_true_area(places, area)[:max_results]


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


# Seoul City Hall, 25 km: covers the whole city, so a same-named place
# elsewhere can't win the match.
_SEOUL_BIAS = "circle:25000@37.5665,126.9780"


def find_place_photo_ref(*, name: str, api_key: str) -> str | None:
    """Legacy Find Place — the first Google Maps photo (owner or reviewer
    upload) of a Seoul place, as a photo_reference for the /place-photo proxy.
    None when Google has no match or the match has no photo (never raises)."""
    if not api_key or not name:
        return None

    data = _google_get(
        "https://maps.googleapis.com/maps/api/place/findplacefromtext/json",
        {
            "input": name,
            "inputtype": "textquery",
            "fields": "photos,place_id",
            "locationbias": _SEOUL_BIAS,
            "language": "en",
            "key": api_key,
        },
    )
    candidates = data.get("candidates") or []
    photos = (candidates[0].get("photos") or []) if candidates else []
    return (photos[0].get("photo_reference") or None) if photos else None


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


# Anchor-centred search. SEOUL_AREA_CENTERS holds one hand-placed point per
# neighbourhood, but a day's courses cluster wherever the course actually runs.
# Measured against the current dataset, that fixed point sits a median ~1km --
# and up to 3.7km in Mapo, 3.5km in Gangnam -- from the POIs the day will
# actually visit, so the search circle can miss the very stops it is meant to
# surround (reorder_supplements' docstring notes the same symptom downstream).
# A purpose keyword's rating floor. K-pop pop-up and merch stores are routinely
# unrated, and a 4.0 floor dropped every one of them.
_MIN_RATING = {"kpop_landmark": 0.0}


_ANCHOR_MIN_POINTS = 3          # below this the centroid is one outlier away from nonsense
_ANCHOR_WALK_BUFFER_M = 800     # a stop just outside the cluster is still walkable
_ANCHOR_RADIUS_MAX_M = 3000     # past this, fall back: see _anchor_search_origin


def _anchor_points_for_area(
    area: str, day_segments: list[dict[str, Any]] | None,
) -> list[tuple[float, float]]:
    """Coordinates of the anchor-course POIs planned for `area`.

    Mirrors _format_one_course's restrict_area cut, so a POI dropped from the
    prompt for sitting in the wrong neighbourhood cannot drag the search centre
    toward itself.
    """
    points: list[tuple[float, float]] = []
    for seg in day_segments or []:
        if seg.get("area") != area:
            continue
        for course in seg.get("anchor_courses") or []:
            for p in course.get("sequence") or []:
                lat, lng = p.get("lat"), p.get("lng")
                if lat is None or lng is None:
                    continue
                poi_area = _infer_area_from_text_or_coords(
                    p.get("poi_name", ""),
                    p.get("address_en") or p.get("address_ko") or "",
                    lat, lng,
                )
                if poi_area and not _area_matches_requested(poi_area, area):
                    continue
                points.append((float(lat), float(lng)))
    return points


def _anchor_search_origin(
    area: str, day_segments: list[dict[str, Any]] | None,
) -> tuple[tuple[float, float], int] | None:
    """((lat, lng), radius_m) to search `area` from, or None to use the fixed centre.

    None means "too scattered for a centroid to help". Gangnam's courses straddle
    Sinsa and Apgujeong, so their centroid lands in the low-density gap between
    the two clusters and is measurably worse than the hand-placed point -- the
    same is true of any area whose spread exceeds what one sweep can cover.
    Falling back leaves those areas behaving exactly as they did before.
    """
    points = _anchor_points_for_area(area, day_segments)
    if len(points) < _ANCHOR_MIN_POINTS:
        return None

    lat = sum(p[0] for p in points) / len(points)
    lng = sum(p[1] for p in points) / len(points)

    # Trim the farthest 10% before sizing the sweep: with 3-11 points a single
    # outlier would otherwise set the radius for the whole day.
    spread = sorted(_haversine_km(lat, lng, p[0], p[1]) for p in points)
    kept = spread[:max(_ANCHOR_MIN_POINTS, int(len(spread) * 0.9))]

    radius_m = int(kept[-1] * 1000) + _ANCHOR_WALK_BUFFER_M
    if radius_m > _ANCHOR_RADIUS_MAX_M:
        return None
    return (lat, lng), radius_m


def build_google_supplement_for_area(
    *,
    area: str,
    keywords: list[dict[str, str]],
    api_key: str,
    day_segments: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """One "{phrase} in {area} Seoul" Text Search per purpose keyword.

    The keywords are what the traveller named in their purpose
    (graph._extract_purpose_keywords) or in a day's note. The zone itself is not searched: the
    anchor courses are already filtered by it, so a search for it only paid for
    places the plan already had. No keywords, no calls.
    """
    if not api_key or not keywords:
        return []

    origin = _anchor_search_origin(area, day_segments)
    center = origin[0] if origin else None

    # Widened only when the day's own POIs are spread out enough to need it,
    # never below 2500m. Growing it for its own sake backfires: Google ranks by
    # prominence, so a bigger circle pulls in famous places further away
    # instead of closer ones.
    radius = min(max(2500, origin[1]), _ANCHOR_RADIUS_MAX_M) if origin else 2500

    if origin:
        print(f"[Google Places][{_area_label(area)}] 앵커 중심 검색 "
              f"({origin[0][0]:.4f},{origin[0][1]:.4f}) r={origin[1]}m")

    supplement: list[dict[str, Any]] = []
    for kw in keywords:
        phrase, poi_type = kw["phrase"], kw["poi_type"]
        found = fetch_text_places(
            area=area,
            query=f"{phrase} in {_area_label(area)} Seoul",
            api_key=api_key,
            radius=radius,
            min_rating=_MIN_RATING.get(poi_type, 4.0),
            max_results=5,
            poi_type=poi_type,
            center=center,
        )
        supplement.extend(found)
        print(f"[Google Places][{_area_label(area)}] {phrase}: {len(found)}개 추가")

    return _dedupe_places(supplement)


# Each keyword is one paid Text Search per zone; several days in one zone can
# each bring their own, so the zone's list is capped. Trip keywords go first.
MAX_KEYWORDS_PER_AREA = 4


def _keywords_for_area(
    trip: list[dict[str, str]], extra: list[dict[str, str]] | None,
) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for kw in [*trip, *(extra or [])]:
        key = kw["phrase"].strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(kw)
    return out[:MAX_KEYWORDS_PER_AREA]


def build_google_supplement_by_areas(
    *,
    requested_areas: list[str],
    location: str,
    keywords: list[dict[str, str]],
    api_key: str,
    day_segments: list[dict[str, Any]] | None = None,
    keywords_by_area: dict[str, list[dict[str, str]]] | None = None,
) -> list[dict[str, Any]]:
    """Collect Google Places supplement for every requested area.

    `keywords` (the trip purpose's) are searched in every area;
    `keywords_by_area` (from each day's note) only in that day's area.
    """
    keywords_by_area = keywords_by_area or {}
    if not api_key or not (keywords or any(keywords_by_area.values())):
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
    # Each area's sweep is independent -- one Places call per keyword, no shared
    # state -- so they overlap instead of queueing behind each other. On a 7-day
    # trip that was the single longest wait in generation.
    #
    # .map, not as_completed: it yields in `requested_areas` order, and
    # _dedupe_places keeps the FIRST copy of each duplicate. Completion order
    # would hand the same trip a different winner run to run, so the itinerary
    # would stop being reproducible from the same inputs.
    # langsmith: contextvars do not cross the ThreadPoolExecutor boundary, so
    # each worker's google_places spans would orphan into their own root traces
    # instead of nesting under the plan node. Capture the parent run here and
    # re-enter it inside the worker. Free when tracing is off:
    # get_current_run_tree() returns None and tracing_context(parent=None) is a
    # no-op (parent=False is the explicit detach, None means unchanged).
    _parent_run = get_current_run_tree()

    def _one_area(area: str, _parent=_parent_run) -> list[dict[str, Any]]:
        with tracing_context(parent=_parent):
            return build_google_supplement_for_area(
                area=area,
                keywords=_keywords_for_area(keywords, keywords_by_area.get(area)),
                api_key=api_key,
                day_segments=day_segments,
            )

    with ThreadPoolExecutor(
        max_workers=min(len(requested_areas), _FANOUT_WORKERS)
    ) as pool:
        for places in pool.map(_one_area, requested_areas):
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


# ---------------------------------------------------------------------------
# Generation prompt
# ---------------------------------------------------------------------------

DAY_PROMPT = """Plan ONE day of a Seoul trip for a foreign tourist.

    You are given the traveller's trip details, the day's area and focus, the
    anchor courses for that day (Visit Seoul / Visit Korea), and real-time Google
    Places data for that area. Other days are planned separately.

    STRUCTURE RULES:
    - Aim for the PACE line's stop count if one is given, otherwise 5-8 stops.
      Lunch and dinner are added separately and don't count.
    - Do NOT add a restaurant for lunch or dinner -- the system inserts the
      day's meals itself (see "LOCKED MEAL RESERVATIONS" if present). A cafe
      for a daytime break is fine.
    - Arrange POIs in visit order starting around 09:00-10:00, ordered to
      minimise backtracking. Planned activity + travel should be 7-10 hours.
    - Plan for the weekday given; skip anything you know is closed that day
      (many museums close on Mondays).

    ANCHOR COURSE RULES:
    - `[ANCHOR COURSE]` sections are editorially curated sequences. Use one as
      the backbone of the day, in its order unless geography requires otherwise.
    - You may drop anchor POIs that don't fit the purpose, and insert Google
      Places POIs where they fit.
    - If no anchor course is available, build the day from Google Places data.

    CONTENT RULES:
    - Prioritise POIs that match the traveller's purpose and the day's focus.
    - Honour dietary restrictions strictly.
    - Notes must say why the POI fits the traveller's purpose and add
      practical/cultural tips where relevant.
    - Give each POI a priority for THIS traveller: 1 = core to their purpose,
      2 = good fit, 3 = nice-to-have filler. If the day runs long, 3s are
      dropped first.

    DATA INTEGRITY RULES:
    - Use ONLY POIs that appear in the anchor courses or the Google Places data.
      Do not invent generic POIs ("Street Food Stalls", "Seongsu Cafe Street").
    - Copy name, lat, lng and address exactly from the provided data.
    - List a course in sources only if you used at least one of its POIs.

    Return ONLY valid JSON with no markdown fences:
    {
      "theme": "<short day theme>",
      "summary": "<one sentence describing this day>",
      "pois": [
        {
          "name": "<POI name exactly as provided>",
          "type": "<poi_type>",
          "address": "<address from provided data>",
          "lat": <number>,
          "lng": <number>,
          "stay_minutes": <integer>,
          "notes": "<purpose fit + cultural/practical tips>",
          "priority": <1, 2 or 3>
        }
      ],
      "estimated_cost": "<realistic day cost>",
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


# ---------------------------------------------------------------------------
# Candidate formatting
# ---------------------------------------------------------------------------

def _format_one_course(
    c: dict[str, Any],
    idx: int,
    restrict_area: str | None = None,
    closed_on: str | None = None,
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
        # Closed on this day's weekday: not shown, so it can't be picked. Same
        # field the critic's CLOSED_ON_ASSIGNED_DAY check reads.
        if closed_on and closed_on in ((p.get("opening_hours") or {}).get("closed_weekday") or []):
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


def _format_segment_block(seg: dict[str, Any], weekday: str | None = None) -> str:
    days = seg.get("day_numbers") or []
    if not days:
        return ""
    day_label = f"DAY {days[0]}" if len(days) == 1 else f"DAY {days[0]}–{days[-1]}"

    area = seg.get("area")
    lines: list[str] = [f"=== {day_label} CANDIDATES: {_area_label(area) if area else 'Seoul'} ==="]
    note = (seg.get("note") or "").strip()
    if note:
        lines.append(f"Traveller's note for this day: {note}")

    anchors = seg.get("anchor_courses") or []
    rendered: list[str] = []
    for i, c in enumerate(anchors, start=1):
        block = _format_one_course(c, i, restrict_area=area, closed_on=weekday)
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
        lines.append("[ANCHOR COURSE — none available; rely on Google Places]")

    return "\n".join(lines)


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


def _is_locked_meal(poi: dict[str, Any]) -> bool:
    """True only for a poi that IS a meal_slots.fill_meal_slot() result --
    i.e. the system-supplied, verified (or at least tier-known) pick for a
    meal slot. Says nothing about whether a POI merely looks like a
    restaurant/cafe; see _is_meal_poi() for that."""
    return bool(poi.get("meal_slot"))


def _meal_slot_indices(n: int) -> tuple[int, int]:
    """(lunch, dinner) insertion points for a day holding `n` other stops.

    Both meals used to be inserted at a fixed index 2, which put them side by
    side every single time: dinner went in at 2, then lunch went in at 2 and
    pushed dinner to 3. Spreading them puts lunch around a third of the way
    through the day and dinner around three quarters, leaving at least one stop
    between them whenever the day has one to spare.

    Indices are measured against the pre-insertion list, so the caller must
    insert dinner first -- filling the lunch slot first shifts dinner one place
    right and eats the gap.
    """
    if n < 2:
        return 0, 1
    lunch = min(max(round(n / 3), 1), n - 1)
    dinner = min(max(round(n * 0.75), lunch + 1), n)
    return lunch, dinner


def _pending_meal(
    meal_source: dict[int, dict[str, Any]] | None,
    day_num: int,
    pois: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """The locked pick still needing insertion for this day, else None."""
    meal = (meal_source or {}).get(day_num)
    if not meal:
        return None  # no lock for this day/meal (no trip_start_date/area, or tier 3 unfilled)
    meal_name_key = _normalize_text(meal.get("name"))
    if any(_normalize_text(p.get("name")) == meal_name_key for p in pois):
        return None  # LLM already included this exact locked restaurant
    return meal


def _is_meal_poi(poi: dict[str, Any]) -> bool:
    # A meal_slots.fill_meal_slot() result carries this key -- an explicit
    # "this IS the meal slot" marker beats guessing from type/name, so it's
    # checked first. Type inference below stays as the fallback for POIs
    # that never went through meal_slots.py (course/Google candidates).
    if _is_locked_meal(poi):
        return True

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
        # Meal types go LAST. meal_slots already locks a lunch and a dinner into
        # every day, so a backfill that reaches for a restaurant first spends the
        # day's remaining slots on food the traveller already has -- and step 4's
        # target counts only non-meal POIs, so each one inserted does not move it
        # any closer to the target. Measured before this: a relaxed Hongdae day
        # came out 1 sight / 5 eating stops.
        # kpop/shopping stay boosted -- they are destinations, not duplicate meals.
        if ptype in {"cafe", "restaurant", "market", "food", "meal_takeaway"}:
            type_score = 1
        elif ptype in {"kpop_landmark", "shopping_mall", "shopping"}:
            type_score = -1
        # (type, source), not (source, type): source_score used to lead, so every
        # Google item outranked every course item and the type ordering below
        # could only break ties *within* one source. With the pool's Google half
        # being restaurants and its course half being sights, that meant a
        # sightseeing gap got filled with restaurants no matter what type_score
        # said. Type decides what the day needs; source only picks between two
        # candidates of the same kind. /swap-candidates is unaffected -- it
        # passes preferred_types, so its list is one category and type_score is
        # constant across it.
        return (type_score, source_score)

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


@traceable(
    run_type="chain",
    name="validate_and_repair",
    # Its only record today is 8 print() calls to stdout; diff this against
    # the itinerary_generation span above it to see what the validator changed.
    process_outputs=lambda o: {"days": [
        {"day": d.get("day"), "pois": [p.get("name") for p in (d.get("pois") or [])]}
        for d in (o.get("days") or [])
    ]},
)
def _validate_and_repair_itinerary(
    itinerary: dict[str, Any],
    *,
    courses: list[dict[str, Any]],
    google_supplement: list[dict[str, Any]],
    requested_areas: list[str],
    day_segments: list[dict[str, Any]] | None = None,
    duration: str = "",
    num_days: int | None = None,
    pace: str | None = None,
    purpose: str = "",
    locked_meals: dict[int, dict[str, Any]] | None = None,
    locked_lunch_meals: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Remove hallucinations and force requested area coverage.

    `locked_meals` (dinner) / `locked_lunch_meals` (lunch): {day_num:
    meal_slots.fill_meal_slot() result}, precomputed once by plan_node
    (before the Gemini call, so the same choice can also be told to the LLM
    as "don't change this") -- this function only enforces them, it never
    calls meal_slots.fill_meal_slot() itself. A day missing from one of these
    dicts (no trip_start_date, no requested area, or tier 3/unfilled) is left
    without a guaranteed meal slot for that meal, same as always."""
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
                if poi.get("priority") in (1, 2, 3):
                    out["priority"] = poi["priority"]
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

    # 3. Ensure each day has its locked meal_slots.py picks (Michelin tier 1
    # -> Google Places tier 2) present, not just "some restaurant or other".
    # Runs once per meal (dinner, then lunch) -- same insertion logic reused
    # for both, not a separate branch per meal.
    #
    # The system prompt's own "each day MUST include a restaurant/cafe POI"
    # rule means the LLM (or step 4's generic filler) has almost always
    # already put SOME restaurant-type POI in the day by the time this runs
    # -- so the check here is specifically "is the locked name present",
    # never "is any meal-type POI present". A generic _is_meal_poi() check
    # would short-circuit on that ambient restaurant and the verified locked
    # pick would silently never get inserted at all.
    for day in days:
        pois = day.setdefault("pois", [])
        day_num = int(day.get("day") or 0)

        lunch_idx, dinner_idx = _meal_slot_indices(len(pois))
        # Dinner goes in first despite sitting later in the day: inserting at the
        # earlier lunch index first would shift dinner one place right and close
        # the gap _meal_slot_indices opened.
        for meal, insert_idx in (
            (_pending_meal(locked_meals, day_num, pois), dinner_idx),
            (_pending_meal(locked_lunch_meals, day_num, pois), lunch_idx),
        ):
            if not meal:
                continue

            day_area = _primary_area_for_day(day, day_segments) or meal.get("area")
            out = {
                "name": meal.get("name"),
                "type": meal.get("type", "restaurant"),
                "address": meal.get("address") or "",
                "lat": meal.get("lat"),
                "lng": meal.get("lng"),
                "stay_minutes": 60,
                "notes": "",
                "area": day_area,
                "meal_slot": meal.get("meal_slot"),
                "source_tier": meal.get("source_tier"),
                "verified": meal.get("verified"),
                # Google tier has no cuisine-family/opening-hours verification --
                # surfaced as a warning field (same shape as /swap-candidates'
                # warnings) so the frontend can flag it, rather than silently
                # presenting it as verified as a Michelin pick would be.
                "warnings": (
                    ["From Google, not the Michelin guide — cuisine and opening hours unverified"]
                    if meal.get("source_tier") == "google" and not meal.get("diet_search") else []
                ) + list(meal.get("warnings") or []),
            }
            pois.insert(insert_idx, out)
            used_names.add(_normalize_text(out.get("name")))
            print(
                f"[Validator] Day {day.get('day')} {meal.get('meal_slot')} 슬롯 추가: {out.get('name')} "
                f"(tier={meal.get('source_tier')})"
            )

    # 4. Fill under-populated days up to the pace's minimum stop count.
    # Steps 4 and 4b count the same thing -- every POI except a locked meal
    # slot, cafes included. They used to disagree (4 skipped cafes, 4b counted
    # the meals), so a day that followed the prompt's "5-6" came out over the
    # max and lost its own picks.
    for day in days:
        pois = day.setdefault("pois", [])
        stop_count = sum(1 for p in pois if not _is_locked_meal(p))
        if stop_count >= poi_min:
            continue

        target_area = _primary_area_for_day(day, day_segments)

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

        while stop_count < poi_min and candidates:
            item = candidates.pop(0)
            out = _as_output_poi(item, extra_note="Added to make the day sufficiently complete.")
            pois.append(out)
            used_names.add(_normalize_text(out.get("name")))
            stop_count += 1
            print(f"[Validator] Day {day.get('day')} POI 수 보완: {out.get('name')}")

    # 4b. Trim over-populated days down to the pace's maximum stop count
    # (locked meals not counted, same as step 4). Runs
    # after area coverage (2) and the meal slot (3) so trimming never has to
    # undo what those steps just added, and after the min-fill (4) since
    # trimming first would be pointless when a day is still under min.
    #
    # Always protects: every locked meal-slot POI and at least one POI per
    # requested area already present in the
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
        stop_count = sum(1 for p in pois if not _is_locked_meal(p))
        if stop_count <= poi_max:
            continue

        protected_idx: set[int] = {i for i, p in enumerate(pois) if _is_locked_meal(p)}
        protected_areas: set[str] = set()
        for i, p in enumerate(pois):
            area = _poi_area(p)
            if not area:
                continue
            matched_req = next((req for req in requested_areas if _area_matches_requested(area, req)), None)
            if matched_req and matched_req not in protected_areas:
                protected_idx.add(i)
                protected_areas.add(matched_req)

        excess = stop_count - poi_max
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
            area = _primary_area_for_day(day, day_segments)
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


def _primary_area_for_day(
    day: dict[str, Any], day_segments: list[dict[str, Any]] | None,
) -> str | None:
    """The area the traveller actually picked for this day.

    `day_segments` (one entry per day: `{"day_numbers": [n], "area": ...}`,
    built by retrieve_node from the per-day `day_specs`) is the authoritative
    day->area map. It must be looked up by day number, never by position in
    a deduplicated area list -- a repeated region (Day 1 & 2 = Hongdae, Day
    3 = Gangnam) collapses `requested_areas` to `["hongdae", "gangnam"]`,
    and indexing that by day would hand day 2 Gangnam's meals/theme/fill.
    """
    day_num = int(day.get("day") or 0)
    for seg in day_segments or []:
        if day_num in (seg.get("day_numbers") or []):
            area = seg.get("area")
            if area:
                return area

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
    except json.JSONDecodeError as e:
        first_err = e
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


# A day's end time by pace, in minutes after midnight. Relaxed means done by
# the end of the dinner window. fit_day_to_time drops stops until the day fits.
_DAY_START = 10 * 60
_DAY_END = {"relaxed": 20 * 60, "packed": 22 * 60}
_DAY_END_DEFAULT = 21 * 60
_MIN_STOPS_AFTER_FIT = 3


def _hhmm(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def _leg_minutes(a: dict[str, Any], b: dict[str, Any]) -> int:
    """Travel time between two stops, without calling any API.

    ponytail: straight-line distance -- a short hop is walked, anything longer
    is a ride plus 10 minutes of waiting/transfers. Swap in ODsay durations if
    trims look wrong; compute_transit_legs already fetches them for the final day.
    """
    import odsay
    try:
        dist = _haversine_km(float(a["lat"]), float(a["lng"]), float(b["lat"]), float(b["lng"]))
    except (KeyError, TypeError, ValueError):
        return 15
    if dist < odsay.WALKABLE_KM:
        return round(dist / WALK_KMH * 60)
    return round(dist / CAR_KMH * 60) + 10


def _day_schedule(pois: list[dict[str, Any]]) -> tuple[int, dict[str, int]]:
    """(end minute of the day, {meal_slot: start minute}).

    A locked meal can't start before its window opens -- arriving early waits.
    """
    t, meal_starts = _DAY_START, {}
    for i, p in enumerate(pois):
        if i:
            t += _leg_minutes(pois[i - 1], p)
        if _is_locked_meal(p):
            window = meal_slots.MEAL_SLOTS.get(p["meal_slot"])
            if window:
                t = max(t, _hhmm(window[0]))
            meal_starts[p["meal_slot"]] = t
        t += int(float(p.get("stay_minutes") or 60))
    return t, meal_starts


def _pull_evening_forward(pois: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Move stops from after dinner to before it, while dinner can still start
    an hour before its window closes. Afternoons often idle until 18:00."""
    d = next((i for i, p in enumerate(pois) if p.get("meal_slot") == "dinner"), None)
    if d is None:
        return pois
    latest = _hhmm(meal_slots.MEAL_SLOTS["dinner"][1]) - 60
    while d + 1 < len(pois):
        trial = pois[:d] + [pois[d + 1], pois[d]] + pois[d + 2:]
        if _day_schedule(trial)[1].get("dinner", 0) > latest:
            break
        pois, d = trial, d + 1
    return pois


def _priority(poi: dict[str, Any]) -> int:
    """Gemini's 1 (core to the purpose) .. 3 (filler). Stops the code added
    itself were chosen for nobody, so they count as 3."""
    p = poi.get("priority")
    return p if p in (1, 2, 3) else 3


def fit_day_to_time(
    pois: list[dict[str, Any]],
    pace: str | None,
    requested_areas: list[str] | tuple[str, ...] = (),
) -> tuple[list[dict[str, Any]], list[tuple[str, int]]]:
    """Make a day end by its pace's end time, dropping the least relevant stops.

    First evening stops move into idle time before dinner; then, while still
    late, the lowest-priority stop goes (ties: the later one). Locked meals and
    the first stop covering each requested area are never dropped, and a day
    keeps at least _MIN_STOPS_AFTER_FIT stops even if that leaves it late.
    Returns (pois, [(dropped name, priority), ...]); a day that fits comes
    back as the same list.
    """
    deadline = _DAY_END.get((pace or "").strip().lower(), _DAY_END_DEFAULT)
    if _day_schedule(pois)[0] <= deadline:
        return pois, []

    protected = {id(p) for p in pois if _is_locked_meal(p)}
    covered: set[str] = set()
    for p in pois:
        area = _poi_area(p)
        req = next((r for r in requested_areas if _area_matches_requested(area, r)), None) if area else None
        if req and req not in covered:
            covered.add(req)
            protected.add(id(p))

    out = _pull_evening_forward(list(pois))
    dropped: list[tuple[str, int]] = []
    while _day_schedule(out)[0] > deadline:
        if sum(1 for p in out if not _is_locked_meal(p)) <= _MIN_STOPS_AFTER_FIT:
            print(f"[fit_day] still past {deadline // 60}:00 at {_MIN_STOPS_AFTER_FIT} stops; keeping them")
            break
        candidates = [(i, p) for i, p in enumerate(out) if id(p) not in protected]
        if not candidates:
            break
        i, victim = max(candidates, key=lambda ip: (_priority(ip[1]), ip[0]))
        dropped.append((str(victim.get("name")), _priority(victim)))
        out = _pull_evening_forward(out[:i] + out[i + 1:])
    return out, dropped


_PACE_LABELS: dict[str, str] = {"packed": "packed schedule", "relaxed": "relaxed pace"}


def _pace_target_line(state: TravelState) -> str:
    """Extra prompt line steering the LLM's per-day POI count toward the
    user's trip_style. Kept out of DAY_PROMPT (which is
    shared/static across every call) since the target varies per request.
    Silent (no line) when pace is unset/unrecognized -- the LLM falls back to
    the docstring's plain 5-8 rule, and the validator's default bounds (6-7,
    see _pace_bounds) still apply underneath it regardless."""
    pace = (state.get("pace") or "").strip().lower()
    if pace not in _PACE_LABELS:
        return ""
    lo, hi = _pace_bounds(state)
    return (
        f"PACE: {_PACE_LABELS[pace]} -- aim for {lo}-{hi} stops per day, not "
        f"counting the lunch and dinner the system adds (never fewer than {lo}, "
        f"never more than {hi})."
    )


def _resolve_locked_meals(
    trip_start_date: str | None,
    day_segments: list[dict[str, Any]] | None,
    expected_days: int,
    meal_type: str = "dinner",
    exclude_by_day: dict[int, tuple[str, ...]] | None = None,
    diet: str | None = None,
) -> dict[int, dict[str, Any]]:
    """Resolve one `meal_type` pick per day via meal_slots.fill_meal_slot()
    (Michelin tier 1 -> Google Places tier 2) BEFORE the Gemini call, so the
    same choice can be told to the LLM as locked ("don't change this") and
    later enforced identically by _validate_and_repair_itinerary -- one
    lookup, not two independent ones that could disagree.

    `exclude_by_day`: {day_num: (name, ...)} of restaurants already locked
    for a different meal that day (e.g. dinner's pick, when this call is
    resolving lunch) -- passed straight through to fill_meal_slot's existing
    exclude_names, so the same restaurant can't be locked twice into one day.
    If that leaves tier 1 empty, tier 2/3 kick in exactly as they would for
    any other exclusion -- no separate dedup logic.

    Cuisine-avoidance filtering is out of scope here: exclude_families is
    never passed, so tier 1 is never family-filtered and tier 2 (Google) is
    always accepted unverified rather than left empty.

    A day with no resolvable area, no trip_start_date, or a tier-3/unfilled
    result is simply absent from the returned dict -- same as always having
    no guaranteed meal for that day. Called once per meal_type (dinner, then
    lunch) -- same lookup, not a new one per meal.
    """
    locked: dict[int, dict[str, Any]] = {}
    if not trip_start_date or expected_days <= 0:
        return locked

    slot_start, slot_end = meal_slots.MEAL_SLOTS[meal_type]

    def _fill_one(day_num: int, taken: tuple[str, ...] = ()) -> tuple[int, dict[str, Any] | None]:
        """One day's lookup. None means 'no slot to resolve', not 'unfilled'."""
        day_area = _primary_area_for_day({"day": day_num}, day_segments)
        if not day_area:
            return day_num, None
        try:
            weekday = weekday_for_day(trip_start_date, day_num, lang="en")
        except (ValueError, TypeError):
            return day_num, None
        return day_num, meal_slots.fill_meal_slot(
            area=day_area, weekday=weekday, slot_start=slot_start, slot_end=slot_end,
            exclude_names=(*(exclude_by_day or {}).get(day_num, ()), *taken),
            diet=diet,
        )

    # Days are independent *within* one meal_type: exclude_by_day is computed by
    # the caller before this runs, never from a sibling day. The dinner -> lunch
    # ordering lives in plan_node (lunch excludes dinner's picks) and stays
    # strictly sequential -- only this inner per-day loop fans out.
    # Same thread-boundary fix as build_google_supplement_by_areas above --
    # without it each day's meal_slot span orphans out of the plan node.
    _parent_run = get_current_run_tree()

    def _fill_one_traced(day_num: int, _parent=_parent_run):
        with tracing_context(parent=_parent):
            return _fill_one(day_num)

    with ThreadPoolExecutor(
        max_workers=min(expected_days, _FANOUT_WORKERS)
    ) as pool:
        results = list(pool.map(_fill_one_traced, range(1, expected_days + 1)))

    # Parallel days can't see each other's picks, so two days in one area lock
    # the same restaurant. Re-resolve just the collisions, in day order, with
    # every earlier pick excluded.
    taken: list[str] = []
    for day_num, result in results:
        if result is None:
            continue
        if result["status"] == "filled" and result.get("name") in taken:
            _, result = _fill_one(day_num, tuple(taken))
            if result is None:
                continue
        if result["status"] == "filled":
            locked[day_num] = result
            taken.append(result.get("name"))
        else:
            print(f"[Validator] Day {day_num} {meal_type} 3층(unfilled): {result.get('reason')}")

    return locked


def _locked_meals_prompt_lines(locked_meals: dict[int, dict[str, Any]]) -> str:
    if not locked_meals:
        return ""
    lines = ["", "=== LOCKED MEAL RESERVATIONS (do not change) ==="]
    for day_num in sorted(locked_meals):
        meal = locked_meals[day_num]
        name = meal.get("name")
        slot = meal.get("meal_slot") or "meal"
        lines.append(
            f"Day {day_num} {slot} is already scheduled at '{name}'. The system "
            f"inserts it; do not add another restaurant for that {slot}."
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

def _synth_purpose(state: TravelState) -> str:
    """사용자가 목적을 적었으면 그 문장, 아니면 다른 슬롯으로 한 문장을 만든다.

    목적을 적는 사람은 소수라 이쪽이 다수 경로다. 그리고 이 합성이 companion 과
    pace 를 검색에 처음 쓰이게 한다 — 지금까지 두 슬롯은 수집만 되고 순위에는
    한 번도 영향을 주지 않았다.
    """
    written = (state.get("purpose") or "").strip()
    if written:
        return written[:300]

    days = _parse_num_days(state.get("travel_dates"))
    pace = (state.get("pace") or "").strip().lower()
    companion = (state.get("companion") or "").strip().lower()

    pace_word = {"packed": "packed", "relaxed": "relaxed"}.get(pace, "")
    who = {
        "solo": "a solo traveller", "couple": "a couple",
        "friends": "a group of friends", "family": "a family with children",
    }.get(companion, "a traveller")

    parts = ["A"]
    if pace_word:
        parts.append(pace_word)
    parts.append(f"{days}-day trip for {who}")
    return " ".join(parts) + "."


def make_retrieve_node(api_key: str):
    set_planner_api_key(api_key)

    def retrieve_node(state: TravelState) -> TravelState:
        day_specs = state.get("day_specs") or []
        if not day_specs:
            return {
                "current_step": "confirm",
                "messages": [AIMessage(content="⚠️ No day plan found. Please set each day's area first.")],
            }

        vectors = load_vectors()
        # 날마다 질의가 다르다: 여행 목적에 그날 메모를 붙인다. 메모가 없는 날은
        # 여행 목적 벡터를 같이 쓴다. 서로 다른 문장만 한 번에 임베딩한다.
        trip = _synth_purpose(state)
        queries = [f"{trip} {s['note']}".strip() if s.get("note") else trip for s in day_specs]
        unique = list(dict.fromkeys(queries))
        embedded = _embed_texts(unique) if vectors else None
        vec_of = dict(zip(unique, embedded)) if embedded else {}

        segments, all_courses, used = [], [], set()
        seen_ids: set[str] = set()
        for spec, query in zip(day_specs, queries):
            sel = select_anchors(
                {**spec, "purpose_vec": vec_of.get(query)}, exclude=used, vectors=vectors
            )
            if sel.relaxed:
                print(f"[retrieval] day {spec['day']} {spec['region']}: {sel.relaxed}")
            used |= {base_id(c["course_id"]) for c in sel.courses}
            segments.append({
                "day_numbers": [spec["day"]],
                "area": spec["region"],
                "note": spec.get("note") or "",
                "keywords": spec.get("keywords") or [],
                "anchor_courses": sel.courses,
            })
            for c in sel.courses:
                if c["course_id"] not in seen_ids:
                    seen_ids.add(c["course_id"])
                    all_courses.append(c)

        return {
            **state,
            "retrieved_courses": all_courses,
            "day_segments": segments,
            "current_step": "planning",
        }

    return retrieve_node


def _embed_texts(texts: list[str]):
    """질의 임베딩, 한 번의 배치 호출. 입력 순서대로 정규화된 벡터 목록.

    실패하면 None 을 돌려 유사도 정렬만 건너뛴다. 예전에는 여기서 예외가 나면
    retrieve_node 가 통째로 죽어 대화가 멈췄다.
    """
    from build_vectors import EMBEDDING_MODEL, normalize
    import numpy as np

    try:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        client = GoogleGenerativeAIEmbeddings(
            model=EMBEDDING_MODEL, google_api_key=_PLANNER_GEMINI_KEY
        )
        # embed_documents 의 기본 task 는 문서용이다. 이건 질의라서
        # embed_query 와 같은 RETRIEVAL_QUERY 로 맞춘다.
        rows = client.embed_documents(texts, task_type="RETRIEVAL_QUERY")
        return list(normalize(np.asarray(rows, dtype="float32")))
    except Exception as e:
        print(f"[retrieval] query embedding failed ({type(e).__name__}) — filter-only")
        return None


def _weekday_of(state: TravelState, day_num: int) -> str | None:
    try:
        return weekday_for_day(state.get("trip_start_date"), day_num, lang="en")
    except (ValueError, TypeError):
        return None


def _meal_lines(
    day_num: int,
    locked: dict[int, dict[str, Any]],
    locked_lunch: dict[int, dict[str, Any]],
    diet: str | None,
) -> str:
    """The day's locked meals, and -- for a diet traveller -- any meal left open
    because no restaurant for that diet was found."""
    lines = (_locked_meals_prompt_lines(_meals_for_day(locked, day_num))
             + _locked_meals_prompt_lines(_meals_for_day(locked_lunch, day_num)))
    if diet:
        for slot, meals in (("lunch", locked_lunch), ("dinner", locked)):
            if day_num not in meals:
                lines += (f"Day {day_num} {slot} is open: no verified {diet} restaurant was "
                          f"found nearby. You may add ONE place to eat for it from the "
                          f"candidates, only if it clearly suits a {diet} diet.\n")
    return lines


_NO_RESTRICTION = {"", "none", "no", "nothing", "n/a", "na", "no restrictions", "missing"}


def _restriction_warning(state: TravelState) -> str | None:
    text = (state.get("restrictions") or "").strip()
    if text.lower().rstrip(".!") in _NO_RESTRICTION:
        return None
    return f"You mentioned: {text} — check with the restaurant"


def _day_keywords_by_area(segments: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    for seg in segments:
        if seg.get("area") and seg.get("keywords"):
            out.setdefault(seg["area"], []).extend(seg["keywords"])
    return out


def _day_num(seg: dict[str, Any]) -> int:
    return int((seg.get("day_numbers") or [0])[0])


def _supplement_for_area(
    supplement: list[dict[str, Any]], area: str | None,
) -> list[dict[str, Any]]:
    """The Google Places rows a day in `area` may use (all of them if no area)."""
    if not area:
        return list(supplement)
    return [p for p in supplement if _area_matches_requested(p.get("area"), area)]


def _meals_for_day(locked: dict[int, dict[str, Any]], day_num: int) -> dict[int, dict[str, Any]]:
    return {day_num: locked[day_num]} if day_num in locked else {}


@traceable(run_type="chain", name="day_generation")
def _generate_day(
    seg: dict[str, Any],
    *,
    trip_lines: str,
    supplement: list[dict[str, Any]],
    locked_lines: str,
    weekday: str | None = None,
    extra: str = "",
) -> dict[str, Any]:
    """One Gemini call for one day. Raises on a failed call or unparseable JSON.

    `extra` is appended after the candidates -- revise_days uses it to hand the
    model its previous attempt and the critic's problems with it.
    """
    prompt = (
        f"{DAY_PROMPT}\n\n{trip_lines}{locked_lines}\n"
        + (f"This day is a {weekday}.\n" if weekday else "")
        + f"{_format_segment_block(seg, weekday)}"
        f"{_format_google_supplement(supplement)}\n"
        f"{extra}"
    )
    day = _parse_itinerary_json(_gemini_text(prompt))
    if not isinstance(day, dict):
        raise ValueError(f"day {_day_num(seg)}: expected a JSON object")
    day["day"] = _day_num(seg)
    return day


def _generate_days(
    segments: list[dict[str, Any]],
    make_kwargs,
) -> list[dict[str, Any] | None]:
    """_generate_day for every segment at once, results in segment order.

    A day whose call fails comes back as None -- the caller decides what that
    means. Same thread-boundary tracing fix as build_google_supplement_by_areas.
    """
    _parent_run = get_current_run_tree()

    def _one(seg: dict[str, Any], _parent=_parent_run) -> dict[str, Any] | None:
        with tracing_context(parent=_parent):
            try:
                return _generate_day(seg, **make_kwargs(seg))
            except Exception as e:
                print(f"[planner] day {_day_num(seg)} generation failed: {type(e).__name__}: {e}")
                return None

    if not segments:
        return []
    with ThreadPoolExecutor(max_workers=min(len(segments), _FANOUT_WORKERS)) as pool:
        return list(pool.map(_one, segments))


def _merge_days(days: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-day results -> one itinerary.

    Two days in the same region see the same Google supplement, so the same
    place can come back twice. The earlier day keeps it; the validator's
    min-fill backfills the later one from what's left.
    """
    seen: set[str] = set()
    merged_days, summaries, sources = [], [], []
    for day in sorted(days, key=lambda d: d["day"]):
        pois = []
        for poi in day.get("pois") or []:
            key = _normalize_text(poi.get("name")) if isinstance(poi, dict) else ""
            if key and key not in seen:
                seen.add(key)
                pois.append(poi)
        merged_days.append({
            "day": day["day"],
            "theme": day.get("theme") or f"Day {day['day']}",
            "pois": pois,
            "estimated_cost": day.get("estimated_cost") or "",
        })
        if day.get("summary"):
            summaries.append(str(day["summary"]).strip())
        sources.extend(s for s in day.get("sources") or [] if isinstance(s, dict))
    return {"summary": " ".join(summaries), "days": merged_days, "sources": sources}


def _trip_lines(state: TravelState) -> str:
    """The trip-wide facts every day's prompt carries."""
    duration = state.get("travel_dates") or ""
    num_days = _resolve_num_days(state)
    duration_text = duration or (f"{num_days} days" if num_days else "")
    # The traveller's own sentence when they wrote one; it's what the prompt's
    # "fits the traveller's purpose" rules are about. Each day's focus is in
    # its own candidates header.
    purpose = _synth_purpose(state)
    pace_line = _pace_target_line(state)
    return (
        f"Duration: {duration_text}\n"
        f"Dietary: {state.get('restrictions') or 'none'}\n"
        f"Purpose: {purpose}\n"
        + (f"{pace_line}\n" if pace_line else "")
    )


def plan_node(state: TravelState) -> TravelState:
    courses = state.get("retrieved_courses") or []
    day_segments = state.get("day_segments") or []
    if not courses or not day_segments:
        return {
            **state,
            "current_step": "done",
            "messages": [AIMessage(content="⚠️ No candidate courses found. Try different details.")],
        }

    purpose = _synth_purpose(state)
    duration = state.get("travel_dates") or ""
    num_days = _resolve_num_days(state)
    pace = state.get("pace")

    # 날짜별 지역의 합집합. 예전에는 region 문자열에서 추출했는데, 이제 사용자가
    # 날마다 지정하므로 추측이 없다.
    requested_areas = list(dict.fromkeys(s["region"] for s in (state.get("day_specs") or [])))
    print(f"[planner] requested_areas = {requested_areas}")

    location = ", ".join(_area_label(a) for a in requested_areas)

    expected_days = _parse_num_days(duration, override=num_days) if (duration or num_days) else 0
    diet = state.get("diet")
    locked_meals = _resolve_locked_meals(
        state.get("trip_start_date"), day_segments, expected_days, meal_type="dinner",
        diet=diet,
    )
    # Lunch excludes every dinner on the trip, so no restaurant is locked twice
    # anywhere -- reuses fill_meal_slot's existing exclude_names.
    dinner_names = tuple(m["name"] for m in locked_meals.values() if m.get("name"))
    dinner_names_by_day = {day_num: dinner_names for day_num in range(1, expected_days + 1)}
    locked_lunch_meals = _resolve_locked_meals(
        state.get("trip_start_date"), day_segments, expected_days, meal_type="lunch",
        exclude_by_day=dinner_names_by_day, diet=diet,
    )
    # A restriction the meal lookup doesn't handle (an allergy, "no pork") rides
    # on every locked meal as a warning the app already knows how to show. A
    # diet it does handle already carries its own warning where one is needed.
    warning = None if diet else _restriction_warning(state)
    if warning:
        for meal in (*locked_meals.values(), *locked_lunch_meals.values()):
            meal.setdefault("warnings", []).append(warning)

    google_supplement: list[dict[str, Any]] = []
    if GOOGLE_PLACES_API_KEY:
        google_supplement = build_google_supplement_by_areas(
            requested_areas=requested_areas,
            location=location,
            keywords=state.get("purpose_keywords") or [],
            api_key=GOOGLE_PLACES_API_KEY,
            day_segments=day_segments,
            # A day's note keywords are searched only in that day's zone.
            keywords_by_area=_day_keywords_by_area(day_segments),
        )
    else:
        print("[planner] GOOGLE_PLACES_API_KEY 없음 -- Google Places 보완 생략")

    trip_lines = _trip_lines(state)

    def day_inputs(seg: dict[str, Any]) -> dict[str, Any]:
        n = _day_num(seg)
        return {
            "trip_lines": trip_lines,
            "supplement": _supplement_for_area(google_supplement, seg.get("area")),
            "locked_lines": _meal_lines(n, locked_meals, locked_lunch_meals, diet),
            "weekday": _weekday_of(state, n),
        }

    try:
        generated = [d for d in _generate_days(day_segments, day_inputs) if d]
        if not generated:
            raise RuntimeError("every day's generation failed")

        # A day that failed is simply absent here: the validator's step 0 adds
        # it back empty and step 4 fills it from that day's area candidates.
        itinerary = _merge_days(generated)

        itinerary = _validate_and_repair_itinerary(
            itinerary,
            courses=courses,
            google_supplement=google_supplement,
            requested_areas=requested_areas,
            day_segments=day_segments,
            duration=duration,
            num_days=num_days,
            pace=pace,
            purpose=purpose,
            locked_meals=locked_meals,
            locked_lunch_meals=locked_lunch_meals,
        )

        itinerary = _normalize_sources(itinerary, courses)

    except Exception:
        # Back to "confirm", not "done": a failure with no itinerary on "done"
        # fell through route_entry to collect -> day_plan, where the app's
        # "confirm" does nothing, so every "Try again" failed the same way.
        # From "confirm" the next "confirm" regenerates. The exception text
        # is logged, never sent -- same rule as api._INTERNAL_ERROR.
        traceback.print_exc()
        return {
            **state,
            "current_step": "confirm",
            "messages": [AIMessage(content=(
                "Sorry, something went wrong while building your itinerary. "
                "Please try again."
            ))],
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
            # revise_days rebuilds a single day's prompt from these.
            "locked_meals": locked_meals,
            "locked_lunch_meals": locked_lunch_meals,
        },
        "current_step": "critic",
        "messages": [AIMessage(content=ack)],
    }


def _revision_note(day: dict[str, Any], problems: list[str], used_elsewhere: set[str]) -> str:
    previous = [{"name": p.get("name"), "type": p.get("type")} for p in day.get("pois") or []]
    return (
        "=== REVISION ===\n"
        f"Your previous plan for this day was:\n{json.dumps(previous, ensure_ascii=False)}\n"
        "A reviewer found these problems with it:\n"
        + "".join(f"- {p}\n" for p in problems)
        + (f"Already used on other days, do not reuse: {', '.join(sorted(used_elsewhere))}\n"
           if used_elsewhere else "")
        + "Return the whole day again with these problems fixed, changing as little "
          "else as possible. Use only the candidates above.\n"
    )


@traceable(run_type="chain", name="revise_days")
def revise_days(
    state: TravelState,
    itinerary: dict[str, Any],
    issues_by_day: dict[int, list[str]],
) -> dict[str, Any]:
    """Regenerate the flagged days once, with the critic's problems as feedback.

    Called by critic_repair_node when a high-severity issue survives the code
    repairer. Mutates and returns `itinerary` -- the caller passes a copy, and
    keeps it only if the critic scores it no worse. A day whose revision call
    fails keeps its previous version.
    """
    ctx = state.get("planning_context") or {}
    supplement = ctx.get("google_supplement") or []
    locked = ctx.get("locked_meals") or {}
    locked_lunch = ctx.get("locked_lunch_meals") or {}
    segments = [s for s in state.get("day_segments") or [] if _day_num(s) in issues_by_day]
    days = itinerary.get("days") or []
    by_num = {int(d.get("day") or 0): d for d in days}

    def names_outside(n: int) -> set[str]:
        return {_normalize_text(p.get("name")) for d in days if int(d.get("day") or 0) != n
                for p in d.get("pois") or []} - {""}

    trip_lines = _trip_lines(state)

    def day_inputs(seg: dict[str, Any]) -> dict[str, Any]:
        n = _day_num(seg)
        used = names_outside(n)
        return {
            "trip_lines": trip_lines,
            "supplement": [p for p in _supplement_for_area(supplement, seg.get("area"))
                           if _normalize_text(p.get("poi_name")) not in used],
            "locked_lines": _meal_lines(n, locked, locked_lunch, state.get("diet")),
            "weekday": _weekday_of(state, n),
            "extra": _revision_note(by_num.get(n, {}), issues_by_day[n], used),
        }

    for seg, day in zip(segments, _generate_days(segments, day_inputs)):
        n = _day_num(seg)
        if not day or n not in by_num:
            continue
        used = names_outside(n)
        # Same validator as a first-time day, over a pool without the other
        # days' places, so neither the model nor the min-fill can reuse one.
        courses = [
            {**c, "sequence": [p for p in c.get("sequence") or []
                               if _normalize_text(p.get("poi_name")) not in used]}
            for c in seg.get("anchor_courses") or []
        ]
        fixed = _validate_and_repair_itinerary(
            _merge_days([day]),
            courses=courses,
            google_supplement=[p for p in supplement
                               if _normalize_text(p.get("poi_name")) not in used],
            requested_areas=[seg["area"]] if seg.get("area") else [],
            day_segments=[seg],
            pace=state.get("pace"),
            purpose=_synth_purpose(state),
            locked_meals=_meals_for_day(locked, n),
            locked_lunch_meals=_meals_for_day(locked_lunch, n),
        )["days"][0]
        by_num[n].clear()
        by_num[n].update(fixed)

    return itinerary


@traceable(run_type="chain", name="describe_itinerary")
def describe_itinerary(state: TravelState, itinerary: dict[str, Any]) -> None:
    """Rewrite the trip summary and day themes from the stops that actually ship.

    Both are first written by the per-day generation calls, before validation,
    critic repair and revision add, drop or swap stops -- so they can name a
    place that's gone. One call over the final days fixes both. On any failure
    the generated text stays: stale-but-present beats blank.
    """
    days = itinerary.get("days") or []
    if not days:
        return
    area_by_day = {int(s["day"]): s.get("region") for s in state.get("day_specs") or []}

    lines = []
    for d in days:
        n = int(d.get("day") or 0)
        stops = [p.get("name") for p in d.get("pois") or [] if not _is_locked_meal(p)]
        meals = [f"{p.get('meal_slot')}: {p.get('name')}"
                 for p in d.get("pois") or [] if _is_locked_meal(p)]
        area = _area_label(area_by_day[n]) if area_by_day.get(n) else "Seoul"
        lines.append(f"Day {n} ({area}): {', '.join(stops)}"
                     + (f" ({'; '.join(meals)})" if meals else ""))

    prompt = (
        "Write the overview for this finished Seoul itinerary.\n\n"
        f"Traveller: {state.get('companion') or 'unknown'}, "
        f"{state.get('pace') or 'unspecified'} pace\n"
        f"Purpose: {_synth_purpose(state)}\n\n"
        + "\n".join(lines)
        + "\n\nMention only places listed above. Return ONLY JSON:\n"
        '{"summary": "<2-3 sentences for the whole trip>", '
        '"themes": {"<day number>": "<short day theme, under 60 characters>"}}'
    )
    try:
        out = _parse_itinerary_json(_gemini_text(prompt))
    except Exception as e:
        print(f"[planner] describe_itinerary failed, keeping generated text: {type(e).__name__}: {e}")
        return

    summary = str(out.get("summary") or "").strip()
    if summary:
        itinerary["summary"] = summary
    themes = out.get("themes") if isinstance(out.get("themes"), dict) else {}
    for d in days:
        theme = str(themes.get(str(d.get("day"))) or "").strip()
        if theme:
            d["theme"] = theme[:80]
