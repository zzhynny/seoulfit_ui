"""Self-check for NON_REPAIRABLE_CODES -- excluding Critic rules with no
RepairAgent method (SCATTERED_DAY_ROUTE, HIGH_FOREIGNER_FRICTION) from
run_critic_repair_loop's convergence count, while keeping them fully
visible in report["issues"] and factored into overall_score/
feasibility_score.

Bug this fixes: repair() has no method for either code, so a round where
they're the only thing left produced repair_log=[] and an unchanged issue
count -- the loop read that as "didn't improve" and rolled back/stopped
after just 1 round, even when the itinerary was otherwise perfect.

Network-free: no Gemini/Google Places calls, all data is inline.

Run:  python test_critic_repair_non_repairable_codes.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import critic_repair as cr  # noqa: E402


def _issues_from_codes(codes: list[str]) -> list[dict]:
    return [
        {"code": code, "severity": "medium", "message": f"dummy {code}", "day": None, "area": None}
        for code in codes
    ]


def _scripted_report(codes: list[str]) -> dict:
    # feasibility_score docked a bit whenever SCATTERED_DAY_ROUTE/
    # TOO_FEW_POIS is present, mirroring how CriticAgent._evaluate_days
    # actually docks it -- just enough for overall_score to visibly move.
    penalty = 0.2 * sum(1 for c in codes if c in ("SCATTERED_DAY_ROUTE", "TOO_FEW_POIS"))
    feasibility = max(0.0, 1.0 - penalty)
    overall = round(0.35 * feasibility + 0.35 * 1.0 + 0.15 * 1.0 + 0.15 * 1.0, 3)
    return {
        "overall_score": overall,
        "feasibility_score": feasibility,
        "requested_area_coverage_score": 1.0,
        "duplicate_score": 1.0,
        "foreigner_readiness_score": 1.0,
        "requested_areas": [],
        "area_coverage": {},
        "missing_areas": [],
        "issues": _issues_from_codes(codes),
    }


def _scripted_evaluate_with_codes(sequence: list[list[str]]):
    """CriticAgent.evaluate stub yielding sequence[call_n]'s codes as issues
    on each successive call (clamped past the end)."""
    calls = {"n": 0}

    def _evaluate(self, state):
        idx = min(calls["n"], len(sequence) - 1)
        calls["n"] += 1
        return _scripted_report(sequence[idx])

    return _evaluate, calls


def _trivial_itinerary() -> dict:
    pois = [
        {"name": f"P{i}", "type": "tourist_spot", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"}
        for i in range(1, 7)
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
    stub, calls = _scripted_evaluate_with_codes(sequence)
    cr.CriticAgent.evaluate = stub
    return original, calls


def _real_scattered_only_itinerary() -> dict:
    """A real (unmocked-Critic) itinerary whose ONLY problem is two POIs far
    enough apart to trip SCATTERED_DAY_ROUTE -- everything else (POI count,
    meal slot, no requested areas, no closed-day data) is clean."""
    pois = [
        {"name": "Hongdae Spot", "type": "tourist_spot", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"},
        {"name": "Jamsil Spot", "type": "tourist_spot", "lat": 37.5133, "lng": 127.1028, "area": "jamsil"},
        {"name": "P3", "type": "tourist_spot", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"},
        {"name": "P4", "type": "tourist_spot", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"},
        {"name": "P5", "type": "cafe", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"},
        {"name": "P6", "type": "tourist_spot", "lat": 37.5563, "lng": 126.9227, "area": "hongdae"},
    ]
    return {"days": [{"day": 1, "pois": pois}]}


def test_scattered_present_does_not_block_fixing_other_issues():
    """SCATTERED_DAY_ROUTE sits at a constant 1 across all rounds while a
    real, fixable violation (TOO_FEW_POIS x2 -> x1 -> 0) genuinely
    decreases -- the loop must keep going round over round instead of
    treating SCATTERED's presence as "no improvement", and must converge
    once the fixable ones are gone."""
    sequence = [
        ["SCATTERED_DAY_ROUTE", "TOO_FEW_POIS", "TOO_FEW_POIS"],  # round 0: raw 3
        ["SCATTERED_DAY_ROUTE", "TOO_FEW_POIS"],                  # round 1: raw 2 (improved)
        ["SCATTERED_DAY_ROUTE"],                                  # round 2: raw 1, convergence 0
    ]
    original_evaluate, calls = _patch_evaluate(sequence)
    try:
        result = cr.run_critic_repair_loop(_state(_trivial_itinerary()))
    finally:
        cr.CriticAgent.evaluate = original_evaluate

    assert calls["n"] == 3, f"expected the loop to run both repair rounds (not stop after round 1), got {calls['n']}"
    outcomes = [r["outcome"] for r in result["rounds"]]
    assert outcomes == ["initial", "improved", "converged"], outcomes
    assert result["converged"] is True
    assert [i["code"] for i in result["report"]["issues"]] == ["SCATTERED_DAY_ROUTE"]

    print(f"OK  SCATTERED_DAY_ROUTE staying constant doesn't block fixing TOO_FEW_POIS across rounds: "
          f"{[(r['round'], r['issue_count'], r['convergence_issue_count'], r['outcome']) for r in result['rounds']]}")


def test_scattered_only_converges_immediately_with_real_repair():
    """Real (unmocked) RepairAgent: an itinerary whose only problem is
    SCATTERED_DAY_ROUTE must converge at round 0 -- repair() is never even
    called, since there's nothing left to fix once SCATTERED is excluded."""
    result = cr.run_critic_repair_loop(_state(_real_scattered_only_itinerary()))

    assert result["converged"] is True, result["rounds"]
    assert len(result["rounds"]) == 1 and result["rounds"][0]["outcome"] == "initial", (
        "must converge without attempting a repair round"
    )
    assert [i["code"] for i in result["report"]["issues"]] == ["SCATTERED_DAY_ROUTE"]

    print("OK  a SCATTERED_DAY_ROUTE-only itinerary converges immediately with the real RepairAgent, "
          "no wasted repair round")


def test_scattered_still_counted_in_issues_and_score():
    """converged=True must NOT hide SCATTERED_DAY_ROUTE from report["issues"]
    or leave overall_score/feasibility_score at a perfect 1.0 -- only the
    loop's own stop/rollback decision ignores it."""
    result = cr.run_critic_repair_loop(_state(_real_scattered_only_itinerary()))

    assert result["converged"] is True
    codes = [i["code"] for i in result["report"]["issues"]]
    assert "SCATTERED_DAY_ROUTE" in codes, f"must stay visible in issues: {codes}"
    assert result["report"]["feasibility_score"] < 1.0, (
        f"feasibility_score must still be docked for SCATTERED_DAY_ROUTE: {result['report']['feasibility_score']}"
    )
    assert result["report"]["overall_score"] < 1.0, (
        f"overall_score must still reflect the penalty: {result['report']['overall_score']}"
    )

    print(f"OK  SCATTERED_DAY_ROUTE stays in issues ({codes}) and still docks "
          f"feasibility_score={result['report']['feasibility_score']} / "
          f"overall_score={result['report']['overall_score']} despite converged=True")


if __name__ == "__main__":
    test_scattered_present_does_not_block_fixing_other_issues()
    test_scattered_only_converges_immediately_with_real_repair()
    test_scattered_still_counted_in_issues_and_score()
    print("all test_critic_repair_non_repairable_codes self-checks passed")
