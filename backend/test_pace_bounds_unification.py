"""Self-check for unifying the per-day POI-count floor between planner.py
and critic_repair.py via the new pace.py module.

Bug this fixes: critic_repair.py hardcoded "5" for both TOO_FEW_POIS and
_repair_underfilled_days, completely ignoring state["pace"] -- a "packed"
day (target 7-8) trimmed down to 6 by an earlier repair step was never
flagged, and a "relaxed" day (target 5-6) was held to the same floor as
everyone else. Both now read pace.pace_bounds()'s floor, matching
planner.py's own generator-side target exactly.

Only the floor (min) is exercised/asserted here -- the ceiling (max) is
referenced by pace.py for planner.py's sake but is never read by
critic_repair.py and this file makes no assertion about it.

Network-free: no Gemini/Google Places calls, all data is inline.

Run:  python test_pace_bounds_unification.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from pace import pace_bounds  # noqa: E402
from critic_repair import CriticAgent, RepairAgent  # noqa: E402


def _poi(name: str, ptype: str = "tourist_spot") -> dict:
    return {"name": name, "type": ptype, "lat": 37.5563, "lng": 126.9227, "area": "hongdae"}


def _course_poi(name: str, ptype: str = "tourist_spot") -> dict:
    return {"poi_name": name, "poi_type": ptype, "address_en": f"{name} St, Seoul",
            "lat": 37.5563, "lng": 126.9227, "area": "hongdae", "estimated_stay_time": 60}


def _state(pace: str | None, day_pois: list[dict], pool_names: list[str]) -> dict:
    return {
        "itinerary": {"days": [{"day": 1, "pois": day_pois}]},
        "retrieved_courses": [{
            "course_id": "c1",
            "sequence": [_course_poi(n, "cafe" if n == "D" else "tourist_spot") for n in pool_names],
        }],
        "planning_context": {"requested_areas": [], "google_supplement": []},
        "trip_start_date": None,
        "pace": pace,
        "region": "hongdae",
        "category": "",
    }


def test_relaxed_and_packed_apply_different_too_few_pois_thresholds():
    """5 POIs on a day: relaxed's floor (5) is satisfied, packed's floor (7)
    is not -- Critic must disagree between the two paces on the exact same
    itinerary."""
    day_pois = [_poi(n, "cafe" if n == "D" else "tourist_spot") for n in ("A", "B", "C", "D", "E")]
    critic = CriticAgent()

    relaxed_report = critic.evaluate(_state("relaxed", day_pois, ["A", "B", "C", "D", "E"]))
    packed_report = critic.evaluate(_state("packed", day_pois, ["A", "B", "C", "D", "E"]))

    relaxed_codes = {i["code"] for i in relaxed_report["issues"]}
    packed_codes = {i["code"] for i in packed_report["issues"]}

    assert "TOO_FEW_POIS" not in relaxed_codes, f"relaxed (min 5) should accept 5 POIs: {relaxed_report['issues']}"
    assert "TOO_FEW_POIS" in packed_codes, f"packed (min 7) should reject 5 POIs: {packed_report['issues']}"

    print("OK  relaxed (min=5) accepts 5 POIs; packed (min=7) flags the same day as TOO_FEW_POIS")


def test_packed_itinerary_trimmed_to_six_is_flagged_and_repaired():
    """A packed-pace day sitting at 6 POIs (one below packed's floor of 7) --
    Critic must flag it, and RepairAgent must top it back up to 7 using the
    pool's spare candidate."""
    day_pois = [_poi(n) for n in ("A", "B", "C", "D", "E", "F")]  # 6, below packed's 7
    pool_names = ["A", "B", "C", "D", "E", "F", "G"]  # G is the spare
    state = _state("packed", day_pois, pool_names)

    critic = CriticAgent()
    before = critic.evaluate(state)
    assert any(i["code"] == "TOO_FEW_POIS" for i in before["issues"]), (
        f"packed day with 6 POIs (floor=7) should be flagged: {before['issues']}"
    )

    repaired, logs = RepairAgent().repair(state, before)
    day1_names = {p.get("name") for p in repaired["days"][0]["pois"]}
    assert len(day1_names) == 7, f"expected packed floor (7) to be reached: {day1_names}"
    assert "G" in day1_names, f"expected the spare candidate G to fill the gap: {day1_names}"

    after = critic.evaluate({**state, "itinerary": repaired})
    assert not any(i["code"] == "TOO_FEW_POIS" for i in after["issues"]), (
        f"after repair, packed day should no longer be flagged: {after['issues']}"
    )

    print(f"OK  packed day at 6 POIs is flagged, then repaired up to 7: {sorted(day1_names)}")
    print(f"    repair_log: {logs}")


def test_missing_pace_falls_back_to_default_bounds():
    """No pace on the state at all -- both Critic and Repair must fall back
    to pace.DEFAULT_BOUNDS (6, 7), the same default planner.py already used."""
    default_min, _default_max = pace_bounds(None)
    assert default_min == 6, f"expected the existing default floor to stay 6, got {default_min}"

    day_pois = [_poi(n) for n in ("A", "B", "C", "D", "E")]  # 5 -- below the default floor (6)
    state = {
        "itinerary": {"days": [{"day": 1, "pois": day_pois}]},
        "retrieved_courses": [{
            "course_id": "c1",
            "sequence": [_course_poi(n) for n in ("A", "B", "C", "D", "E", "F")],
        }],
        "planning_context": {"requested_areas": [], "google_supplement": []},
        "trip_start_date": None,
        # "pace" key intentionally absent -- not even None, genuinely missing.
        "region": "hongdae",
        "category": "",
    }

    report = CriticAgent().evaluate(state)
    assert any(i["code"] == "TOO_FEW_POIS" for i in report["issues"]), (
        f"5 POIs should be under the default floor of 6: {report['issues']}"
    )

    repaired, _logs = RepairAgent().repair(state, report)
    day1_names = {p.get("name") for p in repaired["days"][0]["pois"]}
    assert len(day1_names) == 6, f"expected the default floor (6) to be reached: {day1_names}"

    print("OK  a state with no pace at all falls back to the default floor (6)")


if __name__ == "__main__":
    test_relaxed_and_packed_apply_different_too_few_pois_thresholds()
    test_packed_itinerary_trimmed_to_six_is_flagged_and_repaired()
    test_missing_pace_falls_back_to_default_bounds()
    print("all test_pace_bounds_unification self-checks passed")
