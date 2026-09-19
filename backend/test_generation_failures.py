"""What a failed or rate-limited itinerary generation leaves behind.

Several travellers generating at once is exactly when Gemini returns 429. The
planner used to have no retry, and a failure parked the thread on "done" with
no itinerary -- where every "Try again" from the app was silently ignored.

Run: backend/venv/bin/python -m pytest backend/test_generation_failures.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import google.genai
from google.genai import errors
from langchain_core.messages import HumanMessage

import graph  # noqa: E402
import planner  # noqa: E402


def _api_error(code: int) -> errors.APIError:
    # The real constructor wants an HTTP response; only .code is read.
    e = errors.ClientError.__new__(errors.ClientError)
    e.code = code
    return e


def _fake_gemini(monkeypatch, outcomes):
    """google.genai.Client whose generate_content plays `outcomes` in order."""
    calls = []

    class _Resp:
        def __init__(self, text):
            self.text = text

    class _Models:
        def generate_content(self, **kw):
            calls.append(kw)
            out = outcomes[len(calls) - 1]
            if isinstance(out, Exception):
                raise out
            return _Resp(out)

    class _Client:
        def __init__(self, **kw):
            self.models = _Models()

    monkeypatch.setattr(google.genai, "Client", _Client)
    monkeypatch.setattr(planner, "_GEMINI_RETRY_DELAYS", (0.0, 0.0))
    return calls


def test_a_rate_limit_is_retried_until_it_clears(monkeypatch):
    calls = _fake_gemini(monkeypatch, [_api_error(429), _api_error(503), '{"ok": 1}'])
    assert planner._gemini_text("p") == '{"ok": 1}'
    assert len(calls) == 3


def test_retries_give_up_after_three_tries(monkeypatch):
    calls = _fake_gemini(monkeypatch, [_api_error(429)] * 3)
    try:
        planner._gemini_text("p")
        raise AssertionError("expected the last 429 to propagate")
    except errors.APIError as e:
        assert e.code == 429
    assert len(calls) == 3


def test_a_bad_request_is_not_retried(monkeypatch):
    calls = _fake_gemini(monkeypatch, [_api_error(400), '{"ok": 1}'])
    try:
        planner._gemini_text("p")
        raise AssertionError("a 400 will fail the same way again")
    except errors.APIError:
        pass
    assert len(calls) == 1


def test_a_failed_plan_can_be_regenerated_and_leaks_nothing(monkeypatch):
    def boom(_prompt):
        raise RuntimeError("SECRET request URL and module path")

    monkeypatch.setattr(planner, "_gemini_text", boom)
    monkeypatch.setattr(planner, "_format_courses_for_prompt", lambda *a, **k: "")
    state = {
        "retrieved_courses": [{"course_id": "c1", "sequence": []}],
        "day_specs": [{"day": 1, "region": "jongno", "interest": "Shopping"}],
        "travel_dates": "x (1 day)",
        "messages": [],
    }

    out = planner.plan_node(state)

    assert not out.get("itinerary")
    reply = out["messages"][-1].content
    assert "SECRET" not in reply, reply
    # The app's retry sends "confirm"; from here it must reach generation again.
    retry = {**out, "messages": [HumanMessage(content="confirm")]}
    assert graph.route_entry(retry) == "handle_confirm"


def test_a_retry_waits_for_the_generation_in_flight(monkeypatch):
    """The app gives up after 180s while the server keeps generating. A retry on
    the same session must queue behind that run, not start a second one."""
    import threading
    import time

    from fastapi.testclient import TestClient

    import api

    active, peak, guard = [0], [0], threading.Lock()

    def slow_run(_tid, _msg):
        with guard:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.2)
        with guard:
            active[0] -= 1
        return {"current_step": "done", "confirmed": True, "messages": []}

    monkeypatch.setattr(api, "_run", slow_run)
    monkeypatch.setattr(api, "is_blocked", lambda *a: False)
    client = TestClient(api.app)

    def run_together(ids):
        peak[0] = 0
        threads = [threading.Thread(target=client.post, args=("/chat",),
                                    kwargs={"json": {"thread_id": i, "message": "confirm"}})
                   for i in ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return peak[0]

    assert run_together(["same-session-0000001"] * 2) == 1
    # Other travellers are not held up by it.
    assert run_together(["session-aaaaaaaaaaa1", "session-bbbbbbbbbbb2"]) == 2
