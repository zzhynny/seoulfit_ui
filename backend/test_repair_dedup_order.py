"""Self-check for moving RepairAgent.repair()'s _remove_duplicates call from
the end of the chain to the front.

Bug this fixes: _repair_underfilled_days used to run BEFORE dedup, so a day
with 5 POIs where one name repeats (4 actually unique) looked "full" and was
skipped -- then dedup removed the repeat at the very end, silently leaving
the day at 4. Running dedup first makes every later step's len(pois)/
coverage/meal-presence count accurate.

Also verifies the claim in repair()'s "No second dedup pass" comment: once
dedup runs first, _repair_closed_on_assigned_day's "move to another day"
branch (which never checks the destination day's existing POIs) cannot
reintroduce a duplicate, because dedup already guarantees the POI being
moved exists in exactly one place at move time.

Network-free: no Gemini/Google Places calls, all data is inline.

Run:  python test_repair_dedup_order.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from critic_repair import RepairAgent, normalize_text  # noqa: E402


def _poi(name: str, ptype: str = "tourist_spot", area: str = "hongdae") -> dict:
    return {"poi_name": name, "poi_type": ptype, "address_en": f"{name} St, Seoul",
            "lat": 37.5563, "lng": 126.9227, "area": area, "estimated_stay_time": 60}


def _all_names(itinerary: dict) -> list[str]:
    return [normalize_text(p.get("name")) for d in itinerary["days"] for p in d.get("pois") or []]


def test_duplicate_removal_no_longer_leaves_day_under_minimum():
    """Day 1 has 5 POI entries but only 4 unique names (A repeats). After
    repair(), the day must have 5 unique POIs -- dedup removes the repeat,
    then under-fill tops it back up with the pool's spare candidate."""
    day1_pois = [
        {"name": "A", "type": "tourist_spot", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"},
        {"name": "B", "type": "tourist_spot", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"},
        {"name": "C", "type": "tourist_spot", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"},
        {"name": "D", "type": "cafe", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"},
        {"name": "A", "type": "tourist_spot", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"},  # duplicate
    ]
    itinerary = {"days": [{"day": 1, "pois": day1_pois}]}
    state = {
        "itinerary": itinerary,
        "retrieved_courses": [{
            "course_id": "c1",
            "sequence": [
                _poi("A"), _poi("B"), _poi("C"), _poi("D", ptype="cafe"),
                _poi("E"),  # spare, unused candidate -- what under-fill should reach for
            ],
        }],
        "planning_context": {"requested_areas": [], "google_supplement": []},
        "trip_start_date": None,
        "region": "hongdae",
        "category": "",
    }
    report = {"requested_areas": []}

    repaired, logs = RepairAgent().repair(state, report)

    day1 = repaired["days"][0]["pois"]
    names = [normalize_text(p.get("name")) for p in day1]

    assert len(names) == 5, f"expected 5 POIs after dedup+refill, got {len(names)}: {names}"
    assert len(set(names)) == 5, f"expected 5 unique POIs, got duplicates in {names}"
    assert names.count(normalize_text("A")) == 1, "A must appear exactly once after dedup"
    assert normalize_text("E") in names, f"expected the spare candidate E to fill the gap: {names}"

    print(f"OK  duplicate removed AND day refilled back to 5: {names}")
    print(f"    repair_log: {logs}")


def test_dedup_first_prevents_closed_day_move_from_reintroducing_a_duplicate():
    """Day 1 (Monday) and Day 2 (Tuesday) both independently contain "X"
    before repair() runs (as the raw LLM output might). X is also closed on
    Mondays, so _repair_closed_on_assigned_day will try to move Day 1's copy
    elsewhere. Verifies: (1) the front dedup collapses the pre-existing
    cross-day duplicate first, (2) the later move relocates the single
    surviving X into Day 2 without creating a new duplicate there."""
    closed_x = {**_poi("X"), "opening_hours": {"closed_weekday": ["Monday"]}}
    # candidate_from_course_poi reads opening_hours.closed_weekday -- see
    # planner._poi_from_course_item / critic_repair.candidate_from_course_poi.

    day1_pois = [
        {"name": "X", "type": "tourist_spot", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"},
        {"name": "P1", "type": "cafe", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"},
        {"name": "P2", "type": "tourist_spot", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"},
        {"name": "P3", "type": "tourist_spot", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"},
    ]
    day2_pois = [
        {"name": "X", "type": "tourist_spot", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"},  # pre-existing dup
        {"name": "Q1", "type": "cafe", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"},
        {"name": "Q2", "type": "tourist_spot", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"},
        {"name": "Q3", "type": "tourist_spot", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"},
        {"name": "Q4", "type": "tourist_spot", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"},
    ]
    itinerary = {"days": [{"day": 1, "pois": day1_pois}, {"day": 2, "pois": day2_pois}]}
    state = {
        "itinerary": itinerary,
        "retrieved_courses": [{
            "course_id": "c1",
            "sequence": [
                closed_x, _poi("P1", ptype="cafe"), _poi("P2"), _poi("P3"),
                _poi("Q1", ptype="cafe"), _poi("Q2"), _poi("Q3"), _poi("Q4"),
            ],
        }],
        "planning_context": {"requested_areas": [], "google_supplement": []},
        "trip_start_date": "2027-02-01",  # Monday (see date_utils.py's own self-check)
        "region": "hongdae",
        "category": "",
    }
    report = {"requested_areas": []}

    repaired, logs = RepairAgent().repair(state, report)

    all_names = _all_names(repaired)
    assert len(all_names) == len(set(all_names)), f"no duplicate should survive: {all_names}"

    day1_names = [normalize_text(p.get("name")) for p in repaired["days"][0]["pois"]]
    day2_names = [normalize_text(p.get("name")) for p in repaired["days"][1]["pois"]]
    assert normalize_text("X") not in day1_names, f"X is closed on Monday, must not stay on Day 1: {day1_names}"
    assert day2_names.count(normalize_text("X")) == 1, (
        f"X must be moved into Day 2 exactly once (not duplicated): {day2_names}"
    )

    print(f"OK  no cross-day duplicate survives; X relocated to Day 2 exactly once")
    print(f"    Day 1: {day1_names}")
    print(f"    Day 2: {day2_names}")
    print(f"    repair_log: {logs}")


if __name__ == "__main__":
    test_duplicate_removal_no_longer_leaves_day_under_minimum()
    test_dedup_first_prevents_closed_day_move_from_reintroducing_a_duplicate()
    print("all test_repair_dedup_order self-checks passed")
