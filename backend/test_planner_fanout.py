"""Per-area and per-day lookups overlap, without changing what comes out.

Generation used to walk requested areas one at a time, each area spending 3-7
blocking Google Places calls. A 7-day trip therefore paid ~30 round trips end to
end while the traveller watched the "Crafting" spinner.

Fanning them out is only safe because of one invariant these tests pin down:
results must come back in *request* order, not completion order.
_dedupe_places keeps the FIRST copy of each duplicate, so completion order would
hand the same trip a different winner from run to run and the itinerary would
stop being reproducible from identical inputs.

Run:  backend/venv/bin/python backend/test_planner_fanout.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import meal_slots  # noqa: E402
import planner  # noqa: E402

AREAS = ["jongno", "hongdae", "gangnam", "seongsu", "itaewon", "mapo"]


def _place(area: str, i: int) -> dict:
    return {"poi_name": f"{area}-{i}", "lat": 37.5 + i / 1000, "lng": 127.0, "area": area}


def test_results_follow_request_order_not_completion_order() -> None:
    """The first-requested area must land first even when it finishes last."""
    delay = {area: (len(AREAS) - i) * 0.05 for i, area in enumerate(AREAS)}

    def fake(*, area, keywords, api_key, day_segments):
        time.sleep(delay[area])          # earlier areas are the SLOWEST here
        return [_place(area, 0)]

    original = planner.build_google_supplement_for_area
    planner.build_google_supplement_for_area = fake
    try:
        out = planner.build_google_supplement_by_areas(
            requested_areas=list(AREAS), location="", keywords=[{"phrase": "food", "poi_type": "restaurant"}],
            api_key="test-key", day_segments=None,
        )
    finally:
        planner.build_google_supplement_for_area = original

    assert [p["area"] for p in out] == AREAS, out


def test_duplicate_resolution_is_stable() -> None:
    """Same POI from two areas: the earlier-requested area always wins."""
    def fake(*, area, keywords, api_key, day_segments):
        time.sleep(0.05 if area == "jongno" else 0.0)   # jongno finishes LAST
        return [{"poi_name": "Shared Cafe", "lat": 37.5, "lng": 127.0, "area": area}]

    original = planner.build_google_supplement_for_area
    planner.build_google_supplement_for_area = fake
    try:
        out = planner.build_google_supplement_by_areas(
            requested_areas=["jongno", "hongdae"], location="", keywords=[{"phrase": "food", "poi_type": "restaurant"}],
            api_key="test-key", day_segments=None,
        )
    finally:
        planner.build_google_supplement_for_area = original

    assert len(out) == 1, out
    assert out[0]["area"] == "jongno", out


def test_areas_actually_overlap() -> None:
    """Fails if this ever regresses to a plain for-loop."""
    def fake(*, area, keywords, api_key, day_segments):
        time.sleep(0.2)
        return [_place(area, 0)]

    original = planner.build_google_supplement_for_area
    planner.build_google_supplement_for_area = fake
    try:
        start = time.monotonic()
        planner.build_google_supplement_by_areas(
            requested_areas=list(AREAS), location="", keywords=[{"phrase": "food", "poi_type": "restaurant"}],
            api_key="test-key", day_segments=None,
        )
        elapsed = time.monotonic() - start
    finally:
        planner.build_google_supplement_for_area = original

    # 6 areas x 0.2s = 1.2s sequential; one round of 6 workers is ~0.2s.
    assert elapsed < 0.6, f"areas did not overlap: {elapsed:.2f}s"


def test_meal_days_keep_their_own_day_number_and_exclusions() -> None:
    """Fan-out must not cross day 1's exclusions onto day 3's lookup."""
    seen: dict[int, tuple] = {}

    def fake_area(spec, day_segments):
        return f"area{spec['day']}"

    def fake_fill(*, area, weekday, slot_start, slot_end, exclude_names=()):
        time.sleep(0.05)
        day = int(area.removeprefix("area"))
        seen[day] = tuple(exclude_names)
        return {"status": "filled", "name": f"Restaurant {day}", "area": area}

    orig_area, orig_fill = planner._primary_area_for_day, meal_slots.fill_meal_slot
    planner._primary_area_for_day, meal_slots.fill_meal_slot = fake_area, fake_fill
    try:
        locked = planner._resolve_locked_meals(
            "2026-09-21", None, 4, meal_type="dinner",
            exclude_by_day={1: ("Only Day One",), 3: ("Only Day Three",)},
        )
    finally:
        planner._primary_area_for_day, meal_slots.fill_meal_slot = orig_area, orig_fill

    assert set(locked) == {1, 2, 3, 4}, locked
    # The pairing is what fan-out could scramble: each day keeps its own name
    # and its own exclusion list.
    for day in (1, 2, 3, 4):
        assert locked[day]["name"] == f"Restaurant {day}", locked[day]
    assert seen == {1: ("Only Day One",), 2: (), 3: ("Only Day Three",), 4: ()}, seen


def test_unresolvable_day_is_absent_not_crashing() -> None:
    """A day with no area drops out; the rest still resolve."""
    def fake_area(spec, day_segments):
        return None if spec["day"] == 2 else f"area{spec['day']}"

    def fake_fill(*, area, weekday, slot_start, slot_end, exclude_names=()):
        day = int(area.removeprefix("area"))
        return {"status": "filled" if day != 3 else "unfilled",
                "name": f"Restaurant {day}", "reason": "no tier match"}

    orig_area, orig_fill = planner._primary_area_for_day, meal_slots.fill_meal_slot
    planner._primary_area_for_day, meal_slots.fill_meal_slot = fake_area, fake_fill
    try:
        locked = planner._resolve_locked_meals("2026-09-21", None, 3, meal_type="lunch")
    finally:
        planner._primary_area_for_day, meal_slots.fill_meal_slot = orig_area, orig_fill

    assert set(locked) == {1}, locked          # 2 has no area, 3 came back unfilled


if __name__ == "__main__":
    test_results_follow_request_order_not_completion_order()
    test_duplicate_resolution_is_stable()
    test_areas_actually_overlap()
    test_meal_days_keep_their_own_day_number_and_exclusions()
    test_unresolvable_day_is_absent_not_crashing()
    print("all planner fan-out self-checks passed")
