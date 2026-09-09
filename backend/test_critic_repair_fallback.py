"""Self-check for the P0 fix: when CriticAgent/RepairAgent raise inside
critic_repair_node, the response must fall back to the pre-Critic/Repair
(planner-validated) itinerary -- unmutated -- and carry a
critic_report.verification_failed flag, instead of silently returning
whatever partially-repaired state the itinerary object was left in.

Network-free: no Gemini/Google Places calls. CriticAgent.evaluate is
monkeypatched to raise, simulating an unexpected internal failure.

Run:  python test_critic_repair_fallback.py
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import critic_repair as cr  # noqa: E402


def test_exception_falls_back_to_unmutated_pre_repair_itinerary():
    original_itinerary = {
        "days": [
            {"day": 1, "pois": [{"name": "Some Cafe", "type": "cafe", "lat": 37.5, "lng": 127.0}]},
        ],
        "requested_areas": ["hongdae"],
    }
    # Deep copy up front so we have an untouched reference to compare against
    # after the call -- the whole point of the fix is that the returned
    # itinerary must equal this, not some in-place-mutated variant.
    expected = copy.deepcopy(original_itinerary)

    state = {
        "itinerary": original_itinerary,
        "retrieved_courses": [],
        "planning_context": {"requested_areas": ["hongdae"], "google_supplement": []},
        "trip_start_date": None,
        "region": "hongdae",
        "category": "",
    }

    # Force CriticAgent.evaluate to blow up, simulating any unexpected internal
    # failure (malformed POI data, a bug in one of the geo helpers, etc.) --
    # this is the exact class of failure the P0 fix is about.
    original_evaluate = cr.CriticAgent.evaluate

    def _boom(self, state):
        raise RuntimeError("simulated critic failure")

    cr.CriticAgent.evaluate = _boom
    try:
        node = cr.make_critic_repair_node()
        result = node(state)
    finally:
        cr.CriticAgent.evaluate = original_evaluate

    assert result["current_step"] == "done"

    returned_itinerary = result["itinerary"]
    report = returned_itinerary.get("critic_report") or {}
    assert report.get("verification_failed") is True, report
    assert "simulated critic failure" in (report.get("error") or ""), report
    # Same shape as the success path (before/after/repair_applied/repair_log
    # keys present, just empty) so a caller reading those subfields blindly
    # doesn't need a separate null-check.
    assert report["before"] is None and report["after"] is None
    assert report["repair_applied"] is False
    assert report["repair_log"] == []

    # Top-level state.critic_report mirrors the same flag (matches the
    # success-path convention of setting it both nested and top-level).
    assert result["critic_report"]["verification_failed"] is True

    # The itinerary content itself must be exactly the pre-repair snapshot --
    # not an empty/partial one, and not accidentally mutated in place.
    assert returned_itinerary["days"] == expected["days"], returned_itinerary["days"]
    assert returned_itinerary["requested_areas"] == expected["requested_areas"]

    print("OK  critic_repair_node falls back to the unmutated pre-repair itinerary "
          "and flags verification_failed on exception")


if __name__ == "__main__":
    test_exception_falls_back_to_unmutated_pre_repair_itinerary()
    print("all test_critic_repair_fallback self-checks passed")
