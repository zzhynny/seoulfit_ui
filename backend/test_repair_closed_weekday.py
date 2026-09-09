"""Self-check for the P0 fix: RepairAgent's area/meal/under-fill insertion
paths must never add a POI that is regularly closed on the day it's being
added to. Reproduces the bug from the static review (candidates_for_area had
no closed_weekday filter, so _repair_missing_areas / _repair_missing_meals /
_repair_underfilled_days could freely insert a closed POI) and asserts it no
longer happens.

Network-free: no Gemini/Google Places calls, all data is inline.

Run:  python test_repair_closed_weekday.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from critic_repair import RepairAgent, candidates_for_area, normalize_text  # noqa: E402


def _course_poi(name, ptype, area, closed_weekday=None):
    return {
        "poi_name": name,
        "poi_type": ptype,
        "address_en": f"{name} St, Seoul",
        "lat": 37.5563,
        "lng": 126.9227,
        "area": area,
        "estimated_stay_time": 60,
        "opening_hours": {"closed_weekday": closed_weekday} if closed_weekday else None,
    }


# 2027-02-01 is a Monday (see date_utils.py's own self-check).
TRIP_START = "2027-02-01"
DAY1_WEEKDAY = "Monday"


def test_candidates_for_area_excludes_closed_weekday():
    """Direct unit test of the new parameter on candidates_for_area itself."""
    pool = {
        "closed cafe": {"name": "Closed Cafe", "type": "cafe", "area": "hongdae",
                         "closed_weekday": ["Monday"]},
        "open cafe": {"name": "Open Cafe", "type": "cafe", "area": "hongdae",
                      "closed_weekday": []},
    }
    # Without the filter, both come back.
    both = candidates_for_area(pool, "hongdae")
    assert {c["name"] for c in both} == {"Closed Cafe", "Open Cafe"}

    # With exclude_closed_on="Monday", the closed one is dropped.
    open_only = candidates_for_area(pool, "hongdae", exclude_closed_on="Monday")
    assert {c["name"] for c in open_only} == {"Open Cafe"}, open_only

    # A weekday the POI isn't closed on doesn't exclude it.
    tuesday_ok = candidates_for_area(pool, "hongdae", exclude_closed_on="Tuesday")
    assert {c["name"] for c in tuesday_ok} == {"Closed Cafe", "Open Cafe"}

    print("OK  candidates_for_area(exclude_closed_on=...) filters correctly")


def test_repair_agent_never_inserts_closed_poi():
    """End-to-end: an empty Day 1 (Monday) must be filled for area coverage,
    meal slot, and the 5-POI minimum -- using only candidates that are open
    that day, even though closed candidates exist in the pool and would
    otherwise be picked first (fewer of them = look "targeted")."""
    retrieved_courses = [{
        "course_id": "c1",
        "sequence": [
            _course_poi("Closed Cafe", "cafe", "hongdae", closed_weekday=["Monday"]),
            _course_poi("Open Cafe", "cafe", "hongdae"),
            _course_poi("Closed Spot", "tourist_spot", "hongdae", closed_weekday=["Monday"]),
            _course_poi("Open Spot 1", "tourist_spot", "hongdae"),
            _course_poi("Open Spot 2", "tourist_spot", "hongdae"),
            _course_poi("Open Spot 3", "tourist_spot", "hongdae"),
            _course_poi("Open Spot 4", "tourist_spot", "hongdae"),
        ],
    }]

    itinerary = {"days": [{"day": 1, "pois": []}]}
    state = {
        "itinerary": itinerary,
        "retrieved_courses": retrieved_courses,
        "planning_context": {"requested_areas": ["hongdae"], "google_supplement": []},
        "trip_start_date": TRIP_START,
        "region": "hongdae",
        "category": "",
    }
    report = {"requested_areas": ["hongdae"]}

    repaired, logs = RepairAgent().repair(state, report)

    day1_names = {normalize_text(p.get("name")) for p in repaired["days"][0]["pois"]}

    assert normalize_text("Closed Cafe") not in day1_names, day1_names
    assert normalize_text("Closed Spot") not in day1_names, day1_names
    # Repair must still have done its job with the open candidates that remain.
    assert len(repaired["days"][0]["pois"]) >= 5, repaired["days"][0]["pois"]
    assert normalize_text("Open Cafe") in day1_names, day1_names

    print("OK  RepairAgent fills Day 1 without ever inserting a Monday-closed POI")
    print(f"    repair_log: {logs}")


if __name__ == "__main__":
    test_candidates_for_area_excludes_closed_weekday()
    test_repair_agent_never_inserts_closed_poi()
    print("all test_repair_closed_weekday self-checks passed")
