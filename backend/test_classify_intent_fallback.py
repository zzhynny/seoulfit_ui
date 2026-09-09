"""Self-check for the _classify_intent default-value fix.

Bug: _gemini_json returns {} when both the initial Gemini call AND its
one retry fail (network error, 429, etc. -- see _gemini_json's own
comment). _classify_intent then read data.get("intent", "CONFIRM") --
so a double API failure while the user was on the confirm screen was
silently treated as "yes, build the itinerary", even if the user had
just typed something like "change my dates" and gotten unlucky timing.

Fix: default is now "UNKNOWN", which is neither "CONFIRM" nor a field
name, so handle_confirm_node's existing fallback branch (asks the user
again) handles it -- no new branch was added.

Network-free: graph._gemini_raw is monkeypatched to always raise,
reproducing the double-failure path without any real Gemini call.

Run:  python test_classify_intent_fallback.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
import graph  # noqa: E402


def _confirm_screen_state(user_message: str) -> dict:
    """A state as if intake finished and the user is looking at the
    confirm-screen summary, about to reply."""
    return {
        "travel_dates": "September 6, 2026 (1 day)",
        "category": "Culture & History",
        "restrictions": "none",
        "companion": "solo",
        "pace": "relaxed",
        "region": "Hongdae",
        "current_step": "confirm",
        "pending": None,
        "asked": list(graph.FIELD_ORDER),
        "confirmed": False,
        "messages": [
            AIMessage(content="Here's your Seoul trip summary:\n...\nType 'confirm' to proceed."),
            HumanMessage(content=user_message),
        ],
    }


def _double_failure_stub():
    """Reproduces _gemini_json's own documented double-failure path: the
    first call returns text that fails json.loads (triggering the one
    retry), and the retry call raises (simulating the 429/5xx/network
    failure _gemini_json's own comment calls out) -- landing on
    `data == {}` via a normal return, not an exception out of
    _classify_intent. This is the exact path that used to default to
    "CONFIRM"."""
    calls = {"n": 0}

    def _gemini_raw_stub(prompt: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "Sorry, I'm not sure how to answer that."  # not valid JSON
        raise RuntimeError("simulated network failure on retry")

    return _gemini_raw_stub, calls


def test_double_gemini_failure_does_not_silently_confirm():
    stub, calls = _double_failure_stub()
    original_gemini_raw = graph._gemini_raw
    graph._gemini_raw = stub
    try:
        # The user asked to change something -- NOT confirming -- right when
        # the classification call happens to fail twice in a row.
        state = _confirm_screen_state("actually can you change my dates")
        result = graph.handle_confirm_node(state)
    finally:
        graph._gemini_raw = original_gemini_raw

    assert calls["n"] == 2, f"expected both the initial call and the retry to run: {calls}"

    assert result.get("confirmed") is not True, (
        f"a failed classification must never silently confirm: {result}"
    )
    assert result.get("current_step") != "retrieving", (
        f"must not proceed to itinerary generation on a failed classification: {result}"
    )
    reply = result["messages"][0].content
    assert "confirm" in reply.lower(), f"expected the user to be asked again, got: {reply!r}"

    print(f"OK  double Gemini failure does not silently confirm; user is re-asked: {reply!r}")


def test_classify_intent_default_is_unknown_not_confirm():
    """Direct unit check of the default value itself."""
    stub, _calls = _double_failure_stub()
    original_gemini_raw = graph._gemini_raw
    graph._gemini_raw = stub
    try:
        result = graph._classify_intent("change my dates")
    finally:
        graph._gemini_raw = original_gemini_raw

    assert result.intent == "UNKNOWN", f"expected 'UNKNOWN', got {result.intent!r}"
    assert result.intent.upper() != "CONFIRM"
    assert result.intent.lower() not in graph.ALL_FIELDS

    print(f"OK  _classify_intent defaults to {result.intent!r} on total failure, not CONFIRM")


if __name__ == "__main__":
    test_classify_intent_default_is_unknown_not_confirm()
    test_double_gemini_failure_does_not_silently_confirm()
    print("all test_classify_intent_fallback self-checks passed")
