"""Lunch and dinner must land in different parts of the day, never side by side.

Both locked meals used to be inserted at a fixed index 2, so dinner went in at 2
and lunch then went in at 2 and shoved it to 3 -- adjacent on every single trip,
with dinner scheduled before most of the sightseeing.

Run:  backend/venv/bin/python backend/test_meal_placement.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from critic_repair import reorder_supplements  # noqa: E402
from planner import _meal_slot_indices, _validate_and_repair_itinerary  # noqa: E402


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


if __name__ == "__main__":
    test_indices_always_leave_a_gap()
    test_lunch_comes_before_dinner_and_is_not_last()
    test_repair_pass_separates_the_two_meals()
    test_route_tidy_does_not_pull_the_meals_back_together()
    print("all meal placement self-checks passed")
