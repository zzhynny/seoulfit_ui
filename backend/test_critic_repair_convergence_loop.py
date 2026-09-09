"""Self-check for run_critic_repair_loop -- the evaluate->repair convergence
loop (max 3 rounds) that replaced the old single evaluate->repair->evaluate
->done pass. Shared by graph.py's critic_repair_node and api.py's
/revalidate handler.

Most scenarios here script CriticAgent.evaluate's issue count across calls
(via a call-counter stub) so the loop's own stopping/rollback logic can be
tested deterministically, independent of whatever RepairAgent.repair's real
rules happen to converge in. The pace-max test uses the real repair() (with
trim) to confirm the invariant holds under forced repeated rounds.

Network-free: no Gemini/Google Places calls, all data is inline.

Run:  python test_critic_repair_convergence_loop.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import critic_repair as cr  # noqa: E402
from pace import pace_bounds  # noqa: E402


def _dummy_issues(n: int) -> list[dict]:
    return [
        {"code": "DUMMY", "severity": "medium", "message": "dummy", "day": None, "area": None}
        for _ in range(n)
    ]


def _scripted_report(n: int) -> dict:
    return {
        "overall_score": max(0.0, 1.0 - 0.1 * n),
        "feasibility_score": 1.0,
        "requested_area_coverage_score": 1.0,
        "duplicate_score": 1.0,
        "foreigner_readiness_score": 1.0,
        "requested_areas": [],
        "area_coverage": {},
        "missing_areas": [],
        "issues": _dummy_issues(n),
    }


def _scripted_evaluate(sequence: list[int]):
    """CriticAgent.evaluate stub yielding `sequence[call_n]` dummy issues on
    each successive call (clamped to the last entry past the end)."""
    calls = {"n": 0}

    def _evaluate(self, state):
        idx = min(calls["n"], len(sequence) - 1)
        calls["n"] += 1
        return _scripted_report(sequence[idx])

    return _evaluate, calls


def _trivial_itinerary(n_pois: int = 6) -> dict:
    pois = [
        {"name": f"P{i}", "type": "tourist_spot", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"}
        for i in range(1, n_pois + 1)
    ]
    return {"days": [{"day": 1, "pois": pois}]}


def _state(itinerary: dict) -> dict:
    return {
        "itinerary": itinerary,
        "retrieved_courses": [],
        "planning_context": {"requested_areas": [], "google_supplement": []},
        "trip_start_date": None,
        "pace": None,
        "region": "",
        "category": "",
    }


def _patch_evaluate(sequence):
    original = cr.CriticAgent.evaluate
    stub, calls = _scripted_evaluate(sequence)
    cr.CriticAgent.evaluate = stub
    return original, calls


def test_converges_in_one_round_no_extra_repair_calls():
    """0 issues on the very first evaluate -- must stop immediately, no
    repair() call at all, exactly one round entry (round 0)."""
    original_evaluate = cr.CriticAgent.evaluate
    original_repair = cr.RepairAgent.repair
    repair_calls = {"n": 0}
    cr.RepairAgent.repair = lambda self, state, report, user_selected_names=None: (
        repair_calls.__setitem__("n", repair_calls["n"] + 1) or (state["itinerary"], [])
    )
    stub, evaluate_calls = _scripted_evaluate([0])
    cr.CriticAgent.evaluate = stub
    try:
        result = cr.run_critic_repair_loop(_state(_trivial_itinerary()))
    finally:
        cr.CriticAgent.evaluate = original_evaluate
        cr.RepairAgent.repair = original_repair

    assert result["converged"] is True
    assert evaluate_calls["n"] == 1, f"expected exactly 1 evaluate call, got {evaluate_calls['n']}"
    assert repair_calls["n"] == 0, f"expected 0 repair() calls when already at 0 issues, got {repair_calls['n']}"
    assert len(result["rounds"]) == 1 and result["rounds"][0]["outcome"] == "initial"

    print("OK  0 issues at round 0 converges immediately, no repair() call, no wasted rounds")


def test_converges_after_multiple_rounds_final_issues_zero():
    """5 -> 2 -> 0 across three evaluates: must converge with 0 remaining issues."""
    original_evaluate, calls = _patch_evaluate([5, 2, 0])
    try:
        result = cr.run_critic_repair_loop(_state(_trivial_itinerary()))
    finally:
        cr.CriticAgent.evaluate = original_evaluate

    assert result["converged"] is True
    assert len(result["report"]["issues"]) == 0
    assert calls["n"] == 3, f"expected 3 evaluate calls (round 0,1,2), got {calls['n']}"
    outcomes = [r["outcome"] for r in result["rounds"]]
    assert outcomes == ["initial", "improved", "converged"], outcomes

    print(f"OK  5->2->0 converges over multiple rounds: {[(r['round'], r['issue_count'], r['outcome']) for r in result['rounds']]}")


def test_unfixable_violation_stops_after_max_rounds_with_flag():
    """Strictly improving every round (10->7->4->2) but never reaching 0 --
    must stop after exactly max_rounds (3) repair rounds with converged=False
    and the remaining issues still attached."""
    original_evaluate, calls = _patch_evaluate([10, 7, 4, 2])
    try:
        result = cr.run_critic_repair_loop(_state(_trivial_itinerary()))
    finally:
        cr.CriticAgent.evaluate = original_evaluate

    assert result["converged"] is False
    assert len(result["report"]["issues"]) == 2, "final remaining issues must still be attached"
    assert calls["n"] == 4, f"expected 4 evaluate calls (round 0,1,2,3), got {calls['n']}"
    assert len(result["rounds"]) == 4
    assert [r["round"] for r in result["rounds"]] == [0, 1, 2, 3]

    print(f"OK  never-fully-fixed violation stops after 3 repair rounds, converged=False, "
          f"{len(result['report']['issues'])} issue(s) remain")


def test_non_decreasing_issue_count_stops_early():
    """6 -> 6 (no improvement at all): must stop after round 1, NOT run all
    the way to max_rounds, and must not report convergence."""
    original_evaluate, calls = _patch_evaluate([6, 6])
    try:
        result = cr.run_critic_repair_loop(_state(_trivial_itinerary()))
    finally:
        cr.CriticAgent.evaluate = original_evaluate

    assert result["converged"] is False
    assert calls["n"] == 2, f"expected only 2 evaluate calls (round 0, round 1) -- early stop, got {calls['n']}"
    assert len(result["rounds"]) == 2
    assert result["rounds"][-1]["outcome"] == "rolled_back"
    assert len(result["report"]["issues"]) == 6, "must keep round 0's count, not re-attach round 1's"

    print(f"OK  non-improving round stops early after 1 attempt (not all 3 rounds): "
          f"{[(r['round'], r['issue_count'], r['outcome']) for r in result['rounds']]}")


def test_increasing_issue_count_rolls_back_to_previous_snapshot():
    """6 -> 3 (improved) -> 5 (worse than 3): the round-2 result must be
    discarded entirely -- the returned itinerary must carry round 1's
    content (a distinguishable marker POI) and NOT round 2's (a second,
    different marker), proving the rollback restores the actual previous
    snapshot, not just the previous issue count."""
    original_evaluate, calls = _patch_evaluate([6, 3, 5])
    original_repair = cr.RepairAgent.repair
    repair_calls = {"n": 0}

    def _marker_repair(self, state, report, user_selected_names=None):
        repair_calls["n"] += 1
        itinerary = state["itinerary"]
        itinerary["days"][0]["pois"].append({
            "name": f"Round{repair_calls['n']}Marker", "type": "tourist_spot",
            "lat": 37.0, "lng": 127.0, "area": "hongdae",
        })
        return itinerary, [f"round {repair_calls['n']} marker added"]

    cr.RepairAgent.repair = _marker_repair
    try:
        result = cr.run_critic_repair_loop(_state(_trivial_itinerary()))
    finally:
        cr.CriticAgent.evaluate = original_evaluate
        cr.RepairAgent.repair = original_repair

    names = [p["name"] for p in result["itinerary"]["days"][0]["pois"]]
    assert "Round1Marker" in names, f"round 1's (improving) changes must survive: {names}"
    assert "Round2Marker" not in names, f"round 2's (worsening) changes must be discarded: {names}"
    assert result["converged"] is False
    assert len(result["report"]["issues"]) == 3, "kept report must be round 1's (3), not round 2's (5)"

    print(f"OK  a worse round is rolled back to the exact previous snapshot: kept POIs {sorted(names)}")


def test_three_rounds_never_exceed_pace_max():
    """Real RepairAgent.repair() (trim included) forced through all 3 rounds
    via a scripted, strictly-decreasing-but-never-zero evaluate sequence.
    Starts a day well over the pace max; every round's repair() ends with
    its own trim step, so the day must never exceed the max, in this final
    result or (structurally) at any point along the way."""
    poi_min, poi_max = pace_bounds("packed")
    day_pois = [
        {"name": f"P{i}", "type": "tourist_spot", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"}
        for i in range(1, 11)
    ]  # 10 POIs, packed max is 8
    itinerary = {"days": [{"day": 1, "pois": day_pois}]}
    state = {
        "itinerary": itinerary,
        "retrieved_courses": [{
            "course_id": "c1",
            "sequence": [
                {"poi_name": p["name"], "poi_type": "tourist_spot", "address_en": "x",
                 "lat": p["lat"], "lng": p["lng"], "area": "hongdae", "estimated_stay_time": 60}
                for p in day_pois
            ],
        }],
        "planning_context": {"requested_areas": [], "google_supplement": []},
        "trip_start_date": None,
        "pace": "packed",
        "region": "",
        "category": "",
    }

    original_evaluate, calls = _patch_evaluate([10, 8, 6, 4])  # forces all 3 real repair rounds
    try:
        result = cr.run_critic_repair_loop(state)
    finally:
        cr.CriticAgent.evaluate = original_evaluate

    assert calls["n"] == 4, f"expected the loop to run all 3 real repair rounds, got {calls['n']} evaluate calls"
    day_count = len(result["itinerary"]["days"][0]["pois"])
    assert day_count <= poi_max, f"day has {day_count} POIs after 3 rounds, exceeds pace max {poi_max}"

    print(f"OK  after 3 forced real repair rounds, Day 1 stays at {day_count} POIs (pace max {poi_max})")


if __name__ == "__main__":
    test_converges_in_one_round_no_extra_repair_calls()
    test_converges_after_multiple_rounds_final_issues_zero()
    test_unfixable_violation_stops_after_max_rounds_with_flag()
    test_non_decreasing_issue_count_stops_early()
    test_increasing_issue_count_rolls_back_to_previous_snapshot()
    test_three_rounds_never_exceed_pace_max()
    print("all test_critic_repair_convergence_loop self-checks passed")
