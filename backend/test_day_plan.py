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
    specs = graph.default_day_specs({"travel_dates": "June 1, 2026 to June 3, 2026 (3 days)",
                                     "category": "Shopping"})
    assert [s["day"] for s in specs] == [1, 2, 3]
    assert len({s["region"] for s in specs}) == 3
    assert all(s["interest"] == "Shopping" for s in specs)


def test_defaults_cover_a_seven_day_trip():
    specs = graph.default_day_specs({"travel_dates": "June 1, 2026 to June 7, 2026 (7 days)",
                                     "category": "Culture & History"})
    assert len(specs) == 7
    assert len({s["region"] for s in specs}) == 7


def test_defaults_fall_back_to_culture_when_no_interest_was_given():
    specs = graph.default_day_specs({"travel_dates": "June 1, 2026 (1 day)", "category": None})
    assert specs[0]["interest"] == "Culture & History"


def _seed(days=3, interest="Shopping"):
    """day_plan 단계의 스레드를 만든다."""
    client.post("/reset", params={"thread_id": THREAD})
    from api import _config, _graph
    label = f"June 1, 2026 to June {days}, 2026 ({days} days)"
    _graph.update_state(_config(THREAD), {
        "travel_dates": label, "category": interest, "current_step": "day_plan",
        "day_specs": graph.default_day_specs({"travel_dates": label, "category": interest}),
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
])
def test_bad_plans_are_rejected(days, why):
    _seed()
    r = client.post("/day-plan", json={"thread_id": THREAD, "days": days})
    assert r.status_code == 400, why
