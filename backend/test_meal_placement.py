"""Lunch and dinner must land in different parts of the day, never side by side.

Both locked meals used to be inserted at a fixed index 2, so dinner went in at 2
and lunch then went in at 2 and shoved it to 3 -- adjacent on every single trip,
with dinner scheduled before most of the sightseeing.

Run:  backend/venv/bin/python backend/test_meal_placement.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import planner  # noqa: E402
from critic_repair import reorder_supplements  # noqa: E402
from planner import (  # noqa: E402
    _is_meal_poi, _meal_slot_indices, _validate_and_repair_itinerary,
)


def _course(n: int) -> dict:
    """A course whose POIs all sit in Hongdae, spaced ~150m apart."""
    return {
        "course_id": "T_1",
        "course_title": "Test course",
        "source": "Visit Seoul",
        "source_url": "https://example.test",
        "sequence": [
            {
                "sequence_order": i,
                "poi_name": f"Stop {i}",
                "poi_type": "tourist_spot",
                "address_en": f"{i} Hongdae-ro, Mapo-gu, Seoul",
                "lat": 37.5560 + i * 0.0015,
                "lng": 126.9230 + i * 0.0015,
                "estimated_stay_time": 60,
            }
            for i in range(n)
        ],
    }


def _meal(name: str, slot: str) -> dict:
    return {
        "name": name, "type": "restaurant", "meal_slot": slot,
        "address": "1 Hongdae-ro, Mapo-gu, Seoul",
        "lat": 37.5565, "lng": 126.9235,
        "source_tier": "michelin", "verified": True, "area": "hongdae",
    }


def test_indices_always_leave_a_gap() -> None:
    """Whenever the day has a stop to spare, the two meals are not neighbours."""
    for n in range(2, 13):
        lunch, dinner = _meal_slot_indices(n)
        assert 0 <= lunch < dinner <= n, (n, lunch, dinner)
        # Dinner is inserted first, so lunch landing earlier shifts it right by 1.
        gap = (dinner + 1) - lunch - 1
        assert gap >= 1, f"n={n}: lunch@{lunch} dinner@{dinner + 1} are adjacent"
    # A day with 0-1 other stops has nothing to put between them; ordered, at least.
    assert _meal_slot_indices(0) == (0, 1)
    assert _meal_slot_indices(1) == (0, 1)


def test_lunch_comes_before_dinner_and_is_not_last() -> None:
    for n in range(4, 13):
        lunch, dinner = _meal_slot_indices(n)
        assert lunch < n / 2, f"n={n}: lunch@{lunch} should sit in the first half"
        assert dinner >= n / 2, f"n={n}: dinner@{dinner} should sit in the back half"


def test_repair_pass_separates_the_two_meals() -> None:
    """End-to-end through the real validator, not just the index helper."""
    course = _course(6)
    itinerary = {
        "days": [{
            "day": 1, "theme": "Day 1", "estimated_cost": "",
            "pois": [
                {"name": p["poi_name"], "type": "tourist_spot",
                 "address": p["address_en"], "lat": p["lat"], "lng": p["lng"],
                 "stay_minutes": 60, "notes": ""}
                for p in course["sequence"]
            ],
        }],
    }

    out = _validate_and_repair_itinerary(
        itinerary,
        courses=[course],
        google_supplement=[],
        requested_areas=["hongdae"],
        day_segments=[{"day_numbers": [1], "area": "hongdae",
                       "purpose_hint": None, "anchor_courses": [course]}],
        duration="1 day",
        num_days=1,
        pace="relaxed",
        locked_meals={1: _meal("DinnerPick", "dinner")},
        locked_lunch_meals={1: _meal("LunchPick", "lunch")},
    )

    pois = out["days"][0]["pois"]
    names = [p.get("name") for p in pois]
    assert "LunchPick" in names and "DinnerPick" in names, names

    li, di = names.index("LunchPick"), names.index("DinnerPick")
    assert li < di, f"lunch must precede dinner: {names}"
    assert di - li > 1, f"lunch and dinner are still adjacent: {names}"


def test_route_tidy_does_not_pull_the_meals_back_together() -> None:
    """reorder_supplements optimises walking distance; it must leave meals alone.

    Both meals are searched from the same area centre, so they sit close to each
    other -- cheapest-insertion would otherwise happily re-pair them.
    """
    pois = [
        {"name": "Stop 0", "lat": 37.5560, "lng": 126.9230},
        {"name": "LunchPick", "lat": 37.5565, "lng": 126.9235, "meal_slot": "lunch"},
        {"name": "Stop 1", "lat": 37.5600, "lng": 126.9300},
        {"name": "Stop 2", "lat": 37.5620, "lng": 126.9330},
        {"name": "DinnerPick", "lat": 37.5566, "lng": 126.9236, "meal_slot": "dinner"},
        {"name": "Stop 3", "lat": 37.5640, "lng": 126.9360},
    ]
    # Both meals are named in the google pool -- without the meal_slot guard they
    # would be treated as movable supplements and snapped next to each other.
    movable = {"lunchpick", "dinnerpick"}

    names = [p["name"] for p in reorder_supplements(pois, movable)]
    li, di = names.index("LunchPick"), names.index("DinnerPick")
    assert abs(di - li) > 1, f"route tidy re-adjacented the meals: {names}"


def test_backfill_fills_a_short_day_with_sights_not_more_restaurants() -> None:
    """Every day already gets a locked lunch and dinner, so topping up a short
    day must reach for sightseeing first.

    It used to reach for restaurants first, twice over: _candidate_items_for_area
    ranked cafe/restaurant types ahead of everything else, and sorted on source
    before type so every Google item beat every course item regardless. Measured
    on this exact fixture, the day came out 1 sight / 5 eating stops -- and
    step 4's own target counts only non-meal POIs, so each restaurant it inserted
    did nothing to move it closer.
    """
    course = _course(6)
    google = [
        {"poi_name": f"G Restaurant {i}", "poi_type": "restaurant", "area": "hongdae",
         "lat": 37.5565, "lng": 126.9230, "address_en": "Mapo-gu, Seoul",
         "estimated_stay_time": 60, "source": "Google Places (Hongdae)"}
        for i in range(4)
    ]
    itinerary = {"days": [{
        "day": 1, "theme": "Day 1", "estimated_cost": "",
        "pois": [{"name": course["sequence"][0]["poi_name"], "type": "tourist_spot",
                  "address": course["sequence"][0]["address_en"],
                  "lat": course["sequence"][0]["lat"], "lng": course["sequence"][0]["lng"],
                  "stay_minutes": 60, "notes": ""}],
    }]}

    out = _validate_and_repair_itinerary(
        itinerary,
        courses=[course],
        google_supplement=google,
        requested_areas=["hongdae"],
        day_segments=[{"day_numbers": [1], "area": "hongdae",
                       "purpose_hint": "Culture & History", "anchor_courses": [course]}],
        duration="1 day",
        num_days=1,
        pace="relaxed",
        locked_meals={1: _meal("DinnerPick", "dinner")},
        locked_lunch_meals={1: _meal("LunchPick", "lunch")},
    )

    pois = out["days"][0]["pois"]
    eating = [p["name"] for p in pois if _is_meal_poi(p)]
    assert sorted(eating) == ["DinnerPick", "LunchPick"], (
        f"backfill added eating stops on top of the two locked meals: {eating}")
    assert len(pois) - len(eating) >= 3, f"day is mostly food: {[p['name'] for p in pois]}"


def test_a_restaurant_search_only_runs_when_the_purpose_names_food() -> None:
    """The supplement used to sweep for restaurants on every area regardless of
    interest, duplicating the locked meals. It now searches only what the
    traveller's purpose named. meal_slots' own tier-2 fallback and
    /swap-candidates each call Google themselves, so nothing downstream depends
    on this one."""
    calls: list[str] = []
    orig_nearby, orig_text = planner.fetch_nearby_places, planner.fetch_text_places
    planner.fetch_nearby_places = lambda **kw: calls.append(kw["place_type"]) or []
    planner.fetch_text_places = lambda **kw: calls.append(kw.get("poi_type")) or []
    try:
        planner.build_google_supplement_for_area(
            area="hongdae", keywords=[{"phrase": "rooftop bars", "poi_type": "tourist_spot"}],
            api_key="k", day_segments=None)
        assert "restaurant" not in calls, calls

        planner.build_google_supplement_for_area(
            area="hongdae", keywords=[{"phrase": "street food", "poi_type": "restaurant"}],
            api_key="k", day_segments=None)
        assert calls.count("restaurant") == 1, calls
    finally:
        planner.fetch_nearby_places, planner.fetch_text_places = orig_nearby, orig_text


def test_a_day_that_follows_the_pace_keeps_every_stop() -> None:
    """Walkthrough 2026-09-24, day 1: Gemini returned 5 stops for a relaxed day
    (5-6) including a tea house. The fill step counted the cafe as a meal and
    added a stop; the trim step counted both locked meals against the max of 6
    and then cut two -- one of them Changdeokgung, the model's own pick."""
    course = _course(8)
    picked = course["sequence"][:4]
    day = [{"name": p["poi_name"], "type": "tourist_spot", "address": p["address_en"],
            "lat": p["lat"], "lng": p["lng"], "stay_minutes": 60, "notes": ""} for p in picked]
    tea = {"poi_name": "Tea House", "poi_type": "cafe", "area": "hongdae",
           "lat": 37.5570, "lng": 126.9240, "address_en": "Mapo-gu, Seoul",
           "estimated_stay_time": 60, "source": "Google Places (Hongdae)"}
    day.append({"name": "Tea House", "type": "cafe", "address": "Mapo-gu, Seoul",
                "lat": tea["lat"], "lng": tea["lng"], "stay_minutes": 60, "notes": ""})

    out = _validate_and_repair_itinerary(
        {"days": [{"day": 1, "theme": "T", "estimated_cost": "", "pois": day}]},
        courses=[course],
        google_supplement=[tea],
        requested_areas=["hongdae"],
        day_segments=[{"day_numbers": [1], "area": "hongdae",
                       "purpose_hint": "Culture & History", "anchor_courses": [course]}],
        duration="1 day",
        num_days=1,
        pace="relaxed",
        locked_meals={1: _meal("DinnerPick", "dinner")},
        locked_lunch_meals={1: _meal("LunchPick", "lunch")},
    )

    names = [p["name"] for p in out["days"][0]["pois"]]
    assert set(names) == {p["poi_name"] for p in picked} | {"Tea House", "LunchPick", "DinnerPick"}, names


if __name__ == "__main__":
    test_indices_always_leave_a_gap()
    test_lunch_comes_before_dinner_and_is_not_last()
    test_repair_pass_separates_the_two_meals()
    test_route_tidy_does_not_pull_the_meals_back_together()
    test_backfill_fills_a_short_day_with_sights_not_more_restaurants()
    test_a_day_that_follows_the_pace_keeps_every_stop()
    test_a_restaurant_search_only_runs_when_the_purpose_names_food()
    print("all meal placement self-checks passed")
