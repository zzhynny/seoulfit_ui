"""day_specs 기본값과 POST /day-plan."""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))

import graph  # noqa: E402
from api import app  # noqa: E402

client = TestClient(app)
THREAD = "test-day-plan-0123456789"


def test_defaults_give_each_day_a_different_region():
    specs = graph.default_day_specs({"travel_dates": "June 1, 2026 to June 3, 2026 (3 days)"})
    assert [s["day"] for s in specs] == [1, 2, 3]
    assert len({s["region"] for s in specs}) == 3


def test_defaults_cover_a_seven_day_trip():
    specs = graph.default_day_specs({"travel_dates": "June 1, 2026 to June 7, 2026 (7 days)"})
    assert len(specs) == 7
    assert len({s["region"] for s in specs}) == 7


def test_defaults_open_every_day_on_the_default_interest():
    # The chat no longer collects a trip-wide interest -- the traveller picks
    # one per day right here -- so nothing else may seed the rows.
    specs = graph.default_day_specs({"travel_dates": "June 1, 2026 to June 3, 2026 (3 days)",
                                     "category": "Shopping"})
    assert all(s["interest"] == graph.DEFAULT_INTEREST for s in specs)


def test_planner_purpose_comes_from_the_day_plan_interests():
    from planner import _trip_interests
    state = {"day_specs": [
        {"day": 1, "region": "hongdae", "interest": "Food & Cafes"},
        {"day": 2, "region": "seongsu", "interest": "Shopping"},
        {"day": 3, "region": "jongno", "interest": "Food & Cafes"},
    ]}
    assert _trip_interests(state) == "Food & Cafes, Shopping"
    assert _trip_interests({}) == ""


def _seed(days=3):
    """day_plan 단계의 스레드를 만든다."""
    client.post("/reset", params={"thread_id": THREAD})
    from api import _config, _graph
    label = f"June 1, 2026 to June {days}, 2026 ({days} days)"
    _graph.update_state(_config(THREAD), {
        "travel_dates": label, "current_step": "day_plan",
        "day_specs": graph.default_day_specs({"travel_dates": label}),
    })


def test_state_returns_the_defaults():
    _seed()
    body = client.get("/state", params={"thread_id": THREAD}).json()
    assert body["current_step"] == "day_plan"
    assert len(body["day_specs"]) == 3


def test_posting_a_plan_stores_it_and_advances_to_confirm():
    _seed()
    days = [{"day": 1, "region": "hongdae", "interest": "Food & Cafes"},
            {"day": 2, "region": "seongsu", "interest": "Shopping"},
            {"day": 3, "region": "jongno", "interest": "Culture & History"}]
    r = client.post("/day-plan", json={"thread_id": THREAD, "days": days})
    assert r.status_code == 200
    assert r.json()["current_step"] == "confirm"
    assert client.get("/state", params={"thread_id": THREAD}).json()["day_specs"] == days


@pytest.mark.parametrize("days,why", [
    ([{"day": 1, "region": "hongdae", "interest": "Shopping"}], "길이 불일치"),
    ([{"day": 1, "region": "atlantis", "interest": "Shopping"},
      {"day": 2, "region": "jongno", "interest": "Shopping"},
      {"day": 3, "region": "jongno", "interest": "Shopping"}], "없는 지역"),
    ([{"day": 1, "region": "jongno", "interest": "Beauty"},
      {"day": 2, "region": "jongno", "interest": "Shopping"},
      {"day": 3, "region": "jongno", "interest": "Shopping"}], "어휘 밖 관심사"),
    ([{"day": 1, "region": "jongno", "interest": "Shopping"},
      {"day": 1, "region": "jongno", "interest": "Shopping"},
      {"day": 3, "region": "jongno", "interest": "Shopping"}], "day 중복"),
    # geo.SEOUL_AREA_CENTERS has 33 keys but the app only ever offers 12
    # (lib/models/travel_state.dart's kRegionLabels) -- these three are real
    # geo keys with a near-empty course pool (measured: dobong 1, gwanak 1,
    # dmc 3) that /day-plan must still reject, not just made-up ones.
    ([{"day": 1, "region": "dobong", "interest": "Shopping"},
      {"day": 2, "region": "jongno", "interest": "Shopping"},
      {"day": 3, "region": "jongno", "interest": "Shopping"}], "앱이 안 주는 지역 (dobong)"),
    ([{"day": 1, "region": "gwanak", "interest": "Shopping"},
      {"day": 2, "region": "jongno", "interest": "Shopping"},
      {"day": 3, "region": "jongno", "interest": "Shopping"}], "앱이 안 주는 지역 (gwanak)"),
    ([{"day": 1, "region": "dmc", "interest": "Shopping"},
      {"day": 2, "region": "jongno", "interest": "Shopping"},
      {"day": 3, "region": "jongno", "interest": "Shopping"}], "앱이 안 주는 지역 (dmc)"),
])
def test_bad_plans_are_rejected(days, why):
    _seed()
    r = client.post("/day-plan", json={"thread_id": THREAD, "days": days})
    assert r.status_code == 400, why


def test_day_plan_regions_are_all_valid_geo_keys():
    """graph.DAY_PLAN_REGIONS (what POST /day-plan validates region against)
    must never drift ahead of geo.SEOUL_AREA_CENTERS -- every region the app
    can offer has to resolve to real coordinates, or Google Places
    supplementing and meal-slot lookups silently fall back to a default
    area instead of the one the traveller picked."""
    from geo import SEOUL_AREA_CENTERS
    assert set(graph.DAY_PLAN_REGIONS) <= set(SEOUL_AREA_CENTERS)
    # And it's the app's 12, not the full 33 -- see the rejected-region
    # cases above.
    assert len(graph.DAY_PLAN_REGIONS) == 12


def test_day_plan_rejects_a_thread_that_has_not_reached_day_plan():
    # A brand-new thread id, never touched -- current_step defaults to
    # "start" (see _get_state's fallback dict), so _parse_num_days(None) == 1
    # used to let a trivial 1-day plan sail through and jump the thread
    # straight to confirm. A never-used id keeps this test independent of
    # THREAD's state regardless of /reset (see test_graph.py for /reset's
    # own coverage).
    fresh_thread = "test-day-plan-never-seeded-0000000001"
    days = [{"day": 1, "region": "jongno", "interest": "Shopping"}]
    r = client.post("/day-plan", json={"thread_id": fresh_thread, "days": days})
    assert r.status_code == 409


def test_editing_a_field_from_confirm_keeps_the_travellers_day_plan(monkeypatch):
    """Regression: `asked` stays full across a confirm-stage re-ask, so the
    next answer makes `_ask` see field=None again. That must land back on
    confirm with the existing day_specs untouched -- not recompute defaults
    and bounce back into day_plan."""
    _seed()
    days = [{"day": 1, "region": "hongdae", "interest": "Food & Cafes"},
            {"day": 2, "region": "seongsu", "interest": "Shopping"},
            {"day": 3, "region": "jongno", "interest": "Culture & History"}]
    client.post("/day-plan", json={"thread_id": THREAD, "days": days})

    from api import _config, _graph
    # Mimic handle_confirm_node re-asking one field from the confirm screen
    # ("asked" deliberately stays full -- that is the mechanism of the bug).
    _graph.update_state(_config(THREAD), {
        "asked": graph.FIELD_ORDER, "companion": None,
        "pending": "companion", "current_step": "collecting",
    })
    monkeypatch.setattr(graph, "_gemini_raw", lambda prompt: '{"companion": "couple"}')

    r = client.post("/chat", json={"thread_id": THREAD, "message": "couple"})
    assert r.status_code == 200
    body = r.json()
    assert body["current_step"] == "confirm"
    assert body["day_specs"] == days


def test_editing_travel_dates_to_a_new_length_recomputes_the_day_plan():
    """Regression: keeping day_specs on a confirm re-ask (round 1's fix) is
    only correct while the trip is still the same length. Stretching the
    trip from 3 to 5 days must throw the stale 3-entry plan away and route
    back to day_plan -- otherwise Task 6's retrieve_node builds the wrong
    number of days with nothing to show for it."""
    _seed()
    days = [{"day": 1, "region": "hongdae", "interest": "Food & Cafes"},
            {"day": 2, "region": "seongsu", "interest": "Shopping"},
            {"day": 3, "region": "jongno", "interest": "Culture & History"}]
    client.post("/day-plan", json={"thread_id": THREAD, "days": days})

    from api import _config, _graph
    # Mimic handle_confirm_node re-asking travel_dates from the confirm
    # screen (it clears trip_start_date alongside travel_dates + pending).
    _graph.update_state(_config(THREAD), {
        "asked": graph.FIELD_ORDER, "travel_dates": None, "trip_start_date": None,
        "pending": "travel_dates", "current_step": "collecting",
    })

    # Picker-format text, same as conversational_intake_screen.dart emits.
    # Sept 6 -> Sept 10 inclusive = 5 days, up from the original 3.
    r = client.post("/chat", json={
        "thread_id": THREAD, "message": "September 6, 2026 to September 10, 2026",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["current_step"] == "day_plan"
    assert len(body["day_specs"]) == 5
