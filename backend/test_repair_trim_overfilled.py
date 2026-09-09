"""Self-check for RepairAgent._trim_overfilled_days -- the new per-day POI
count ceiling, added after every other repair step, driven by
pace.pace_bounds(pace)'s max half (never a new constant).

Protects (never removed even at the cost of staying over max):
  (a) user-selected POIs (apply_slot_edits' swapped_slots, passed through
      structurally via RepairAgent.repair(user_selected_names=...) --
      no notes-text matching).
  (b) meal-slot POIs (is_meal_poi -- structural).
  (c) the itinerary-wide SOLE POI covering a requested area (same
      itinerary-wide counting CriticAgent._evaluate_area_coverage uses,
      NOT planner.py's own per-day version at planner.py:1500, which is
      untouched).

Removes, in order: (1) _repair_underfilled_days' own filler from the same
repair() call, (2) farthest-average-distance from the day's other POIs.

Network-free: no Gemini/Google Places calls, all data is inline.

Run:  python test_repair_trim_overfilled.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from critic_repair import CriticAgent, RepairAgent, apply_slot_edits, normalize_text  # noqa: E402
from pace import pace_bounds  # noqa: E402


def _poi(name: str, ptype: str = "tourist_spot", lat: float = 37.5563, lng: float = 126.9227) -> dict:
    return {"name": name, "type": ptype, "lat": lat, "lng": lng, "area": "hongdae"}


def _course_poi(name: str, ptype: str = "tourist_spot", lat: float = 37.5563, lng: float = 126.9227) -> dict:
    return {"poi_name": name, "poi_type": ptype, "address_en": f"{name} St, Seoul",
            "lat": lat, "lng": lng, "area": "hongdae", "estimated_stay_time": 60}


def _state(pace: str | None, day_pois: list[dict], pool_names: list[str],
           requested_areas: list[str] | None = None) -> dict:
    return {
        "itinerary": {"days": [{"day": 1, "pois": day_pois}]},
        "retrieved_courses": [{
            "course_id": "c1",
            "sequence": [_course_poi(n) for n in pool_names],
        }],
        "planning_context": {"requested_areas": requested_areas or [], "google_supplement": []},
        "trip_start_date": None,
        "pace": pace,
        "region": " ".join(requested_areas or []),
        "category": "",
    }


def test_packed_ten_pois_trims_to_eight_meal_survives():
    day_pois = [_poi(f"P{i}") for i in range(1, 10)] + [_poi("Meal", ptype="cafe")]
    assert len(day_pois) == 10
    state = _state("packed", day_pois, [p["name"] for p in day_pois])
    report = {"requested_areas": []}

    repaired, logs = RepairAgent().repair(state, report)

    names = [p.get("name") for p in repaired["days"][0]["pois"]]
    poi_min, poi_max = pace_bounds("packed")
    assert poi_max == 8, poi_max
    assert len(names) == 8, f"expected trim to packed max (8), got {len(names)}: {names}"
    assert "Meal" in names, f"meal-slot POI must survive the trim: {names}"

    print(f"OK  packed: 10 POIs trimmed to 8, meal POI kept: {sorted(names)}")
    print(f"    repair_log: {logs}")


def test_relaxed_eight_pois_trims_to_six():
    day_pois = [_poi(f"P{i}") for i in range(1, 8)] + [_poi("Meal", ptype="cafe")]
    assert len(day_pois) == 8
    state = _state("relaxed", day_pois, [p["name"] for p in day_pois])
    report = {"requested_areas": []}

    repaired, logs = RepairAgent().repair(state, report)

    names = [p.get("name") for p in repaired["days"][0]["pois"]]
    poi_min, poi_max = pace_bounds("relaxed")
    assert poi_max == 6, poi_max
    assert len(names) == 6, f"expected trim to relaxed max (6), got {len(names)}: {names}"
    assert "Meal" in names, f"meal-slot POI must survive the trim: {names}"

    print(f"OK  relaxed: 8 POIs trimmed to 6, meal POI kept: {sorted(names)}")
    print(f"    repair_log: {logs}")


def test_protected_only_day_of_nine_is_left_untouched():
    """9 POIs, ALL meal-type (protected tier b) -- relaxed max is 6, but
    nothing removable exists, so the day must stay at 9 and a log entry
    must explain why."""
    day_pois = [_poi(f"Meal{i}", ptype="cafe") for i in range(1, 10)]
    assert len(day_pois) == 9
    state = _state("relaxed", day_pois, [p["name"] for p in day_pois])
    report = {"requested_areas": []}

    repaired, logs = RepairAgent().repair(state, report)

    names = [p.get("name") for p in repaired["days"][0]["pois"]]
    assert len(names) == 9, f"an all-protected day must not be trimmed: {names}"
    assert any("not trimmed" in log for log in logs), f"expected a log explaining the skip: {logs}"

    print(f"OK  9 protected-only POIs left untouched (over the max of 6), logged: {logs}")


def test_distance_based_removal_prefers_the_farthest_poi():
    """No repair-inserted filler in this scenario, so removal order falls
    straight to criterion (2): among a cluster of close-together POIs plus
    one genuine outlier, the outlier must be the one trimmed."""
    cluster = [_poi(f"C{i}", lat=37.5563 + i * 0.0005, lng=126.9227 + i * 0.0005) for i in range(1, 8)]
    outlier = _poi("FarAway", lat=37.4000, lng=127.1500)  # genuinely across the city
    day_pois = cluster + [outlier]
    assert len(day_pois) == 8
    state = _state("relaxed", day_pois, [p["name"] for p in day_pois])  # max=6, excess=2
    report = {"requested_areas": []}

    repaired, logs = RepairAgent().repair(state, report)
    names = [p.get("name") for p in repaired["days"][0]["pois"]]

    assert len(names) == 6, names
    assert "FarAway" not in names, f"the outlier must be removed first: {names}"

    print(f"OK  distance-based removal drops the genuine outlier first: kept {sorted(names)}")


def test_user_selected_poi_survives_trim_even_as_the_outlier():
    """A POI passed in via user_selected_names (RepairAgent.repair's
    structural param -- what api.py's /revalidate now derives from
    apply_slot_edits' swapped_in_names, not notes text) must survive the
    trim even when it would otherwise be the clear removal pick (the
    farthest outlier, with nothing else protecting it)."""
    cluster = [_poi(f"C{i}", lat=37.5563 + i * 0.0005, lng=126.9227 + i * 0.0005) for i in range(1, 8)]
    outlier = _poi("UserPick", lat=37.4000, lng=127.1500)
    day_pois = cluster + [outlier]
    state = _state("relaxed", day_pois, [p["name"] for p in day_pois])  # max=6
    report = {"requested_areas": []}

    repaired, _logs = RepairAgent().repair(
        state, report, user_selected_names={normalize_text("UserPick")},
    )
    names = [p.get("name") for p in repaired["days"][0]["pois"]]

    assert len(names) == 6, names
    assert "UserPick" in names, f"user-selected POI must survive even as the outlier: {names}"

    print(f"OK  user-selected POI survives trim despite being the geographic outlier: {sorted(names)}")


def test_sole_area_coverage_poi_survives_trim():
    """A POI that is the itinerary-wide ONLY match for a requested area must
    survive, matching CriticAgent._evaluate_area_coverage's own
    itinerary-wide counting (not planner.py:1500's per-day version)."""
    sole = {"name": "SoleHongdae", "type": "tourist_spot", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"}
    fillers = [
        {"name": f"F{i}", "type": "tourist_spot", "lat": 37.5133, "lng": 127.1028, "area": "jamsil"}
        for i in range(1, 8)
    ]  # jamsil is not adjacent to hongdae/myeongdong in geo.py's adjacency table
    day_pois = [sole] + fillers
    assert len(day_pois) == 8
    state = _state("relaxed", day_pois, [p["name"] for p in day_pois],
                   requested_areas=["hongdae", "myeongdong"])
    report = {"requested_areas": ["hongdae", "myeongdong"]}

    repaired, _logs = RepairAgent().repair(state, report)
    names = [p.get("name") for p in repaired["days"][0]["pois"]]

    assert len(names) == 6, names
    assert "SoleHongdae" in names, f"the sole hongdae-covering POI must survive: {names}"

    print(f"OK  itinerary-wide sole area-coverage POI survives trim: {sorted(names)}")


def test_five_consecutive_revalidate_calls_never_exceed_max():
    """Mirrors api.py's /revalidate call sequence (apply_slot_edits ->
    CriticAgent.evaluate -> RepairAgent.repair(user_selected_names=...)),
    called 5 times in a row, each call's output itinerary feeding the next
    call's input (as _graph.update_state persists between real /revalidate
    calls). Asserts the invariant holds after EVERY call, not just the
    last: _trim_overfilled_days runs at the end of every repair() call, so
    no matter what churn an edit causes mid-call, the day can never leave a
    call over the pace max."""
    initial_pois = [_poi(f"P{i}") for i in range(1, 10)] + [_poi("Meal", ptype="cafe")]
    assert len(initial_pois) == 10
    spare_names = [f"Spare{i}" for i in range(1, 6)]
    pool_names = [p["name"] for p in initial_pois] + spare_names

    itinerary = {"days": [{"day": 1, "pois": initial_pois}]}
    state = {
        "itinerary": itinerary,
        "retrieved_courses": [{"course_id": "c1", "sequence": [_course_poi(n) for n in pool_names]}],
        "planning_context": {"requested_areas": [], "google_supplement": []},
        "trip_start_date": None,
        "pace": "packed",
        "region": "",
        "category": "",
    }
    poi_min, poi_max = pace_bounds("packed")
    critic = CriticAgent()

    from critic_repair import build_candidate_pool

    for call_num in range(1, 6):
        pool = build_candidate_pool(state)
        # Swap one non-meal POI still present for a not-yet-used spare, same
        # shape as a real /swap-candidates -> /revalidate round trip.
        current_names = {normalize_text(p.get("name")) for p in state["itinerary"]["days"][0]["pois"]}
        swap_target = next(
            n for n in [f"P{i}" for i in range(1, 10)]
            if normalize_text(n) in current_names
        )
        spare = spare_names[(call_num - 1) % len(spare_names)]
        edits = {"swapped_slots": {swap_target: spare}}

        edited_itinerary, user_selected_names = apply_slot_edits(state["itinerary"], edits, pool)
        edited_state = {**state, "itinerary": edited_itinerary}
        before_report = critic.evaluate(edited_state)
        repaired, _logs = RepairAgent().repair(
            edited_state, before_report, user_selected_names=user_selected_names,
        )

        day_count = len(repaired["days"][0]["pois"])
        assert day_count <= poi_max, (
            f"call {call_num}: day has {day_count} POIs, exceeds pace max {poi_max}"
        )

        state = {**state, "itinerary": repaired}  # persisted for the next call, like update_state

    print(f"OK  5 consecutive /revalidate-equivalent calls never exceeded the pace max ({poi_max})")


if __name__ == "__main__":
    test_packed_ten_pois_trims_to_eight_meal_survives()
    test_relaxed_eight_pois_trims_to_six()
    test_protected_only_day_of_nine_is_left_untouched()
    test_distance_based_removal_prefers_the_farthest_poi()
    test_user_selected_poi_survives_trim_even_as_the_outlier()
    test_sole_area_coverage_poi_survives_trim()
    test_five_consecutive_revalidate_calls_never_exceed_max()
    print("all test_repair_trim_overfilled self-checks passed")
