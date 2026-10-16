"""/revalidate after a traveller's edit: a day pushed past its pace's end time
is reported (DAY_RUNS_LATE), never trimmed -- the stops are the traveller's
choice -- and the summary is rewritten from the edited stops.

Every POI sits on the same point, so each timeline is just the stays plus
waiting for meal windows (LEG_SLACK_MIN is zeroed here). The day starts at
10:00; relaxed ends at 21:00.
"""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fastapi.testclient import TestClient

import api
import planner
from critic_repair import CriticAgent


@pytest.fixture(autouse=True)
def _no_slack(monkeypatch):
    monkeypatch.setattr(planner, "LEG_SLACK_MIN", 0)
    monkeypatch.setattr(planner, "_DAY_END", {"packed": 22 * 60})
    monkeypatch.setattr(planner, "_DAY_END_DEFAULT", 21 * 60)


def stop(name, minutes):
    return {"name": name, "type": "tourist_spot", "lat": 37.57, "lng": 126.98,
            "stay_minutes": minutes, "area": "jongno"}


# 10:00 + 13h of stays -> 23:00, past relaxed's 21:00.
LATE_DAY = [stop(f"S{i}", 180) for i in range(4)] + [stop("Late", 60)]
SHORT_DAY = [stop("A", 60), stop("B", 60)]


def late_codes(pois, pace="relaxed"):
    report = CriticAgent().evaluate({"itinerary": {"days": [{"day": 1, "pois": pois}]},
                                     "pace": pace})
    return [i for i in report["issues"] if i["code"] == "DAY_RUNS_LATE"]


def test_critic_flags_a_day_that_runs_past_its_pace_end():
    [issue] = late_codes(LATE_DAY)
    assert issue["day"] == 1 and issue["severity"] == "medium", issue
    assert "23:00" in issue["message"] and "21:00" in issue["message"], issue["message"]


def test_critic_is_quiet_when_the_day_fits():
    assert late_codes(SHORT_DAY) == []


def test_a_day_within_the_grace_is_not_late():
    # 10:00 + 11h20m = 21:20, inside 21:00 + 30 minutes.
    assert late_codes([stop(f"S{i}", 170) for i in range(4)], pace=None) == []


def test_a_day_past_the_grace_is_late_and_names_the_pace_end():
    # 10:00 + 11h31m = 21:31.
    [issue] = late_codes([stop(f"S{i}", 170) for i in range(3)] + [stop("T", 181)],
                         pace=None)
    assert "21:31" in issue["message"] and "past 21:00" in issue["message"]


def test_a_day_within_the_grace_is_not_too_few():
    # Under 6 stops, but 21:20 leaves no hour for another.
    assert too_few([stop(f"S{i}", 170) for i in range(4)]) == []


def too_few(pois):
    # No pace: at least 6 sights, ending by 21:00.
    report = CriticAgent().evaluate({"itinerary": {"days": [{"day": 1, "pois": pois}]}})
    return [i for i in report["issues"] if i["code"] == "TOO_FEW_POIS"]


def test_a_short_day_with_time_left_is_too_few():
    assert len(too_few(SHORT_DAY)) == 1           # ends 12:00


def test_a_day_trimmed_to_end_on_time_is_full_not_too_few():
    # 5 stops, 10:00 + 650 min -> 20:50: under 6, but no hour left for a 6th.
    # Flagging it penalised fit_day_to_time's trim harder than the lateness.
    assert too_few([stop(f"S{i}", 130) for i in range(5)]) == []


class _FakeGraph:
    def __init__(self, values):
        self.values = values

    def get_state(self, config):
        return SimpleNamespace(values=self.values)

    def update_state(self, config, update):
        self.values = {**self.values, **update}


def test_revalidate_reports_a_late_day_keeps_its_stops_and_rewrites_the_summary(monkeypatch):
    graph = _FakeGraph({"itinerary": {"days": [{"day": 1, "pois": list(LATE_DAY)}]},
                        "pace": "relaxed", "planning_context": {}})
    described = []
    monkeypatch.setattr(api, "_graph", graph)
    monkeypatch.setattr(planner, "compute_transit_legs", lambda pois: [])
    monkeypatch.setattr(planner, "describe_itinerary",
                        lambda state, itin: described.append([p["name"] for p in itin["days"][0]["pois"]]))

    r = TestClient(api.app).post("/revalidate", json={"thread_id": "trip-test-reval-0001", "edits": {}})
    assert r.status_code == 200, r.text
    body = r.json()

    names = [p["name"] for p in body["repaired_itinerary"]["days"][0]["pois"]]
    assert names == [p["name"] for p in LATE_DAY], "revalidate must not drop the traveller's stops"
    assert "DAY_RUNS_LATE" in {i["code"] for i in body["after"]["issues"]}
    assert described == [names], "summary must be rewritten from the edited stops"


def test_a_failed_summary_rewrite_does_not_fail_revalidate(monkeypatch):
    graph = _FakeGraph({"itinerary": {"days": [{"day": 1, "pois": list(SHORT_DAY)}]},
                        "pace": "relaxed", "planning_context": {}})
    monkeypatch.setattr(api, "_graph", graph)
    monkeypatch.setattr(planner, "compute_transit_legs", lambda pois: [])

    def boom(state, itin):
        raise RuntimeError("402 RESOURCE_EXHAUSTED")
    monkeypatch.setattr(planner, "describe_itinerary", boom)

    r = TestClient(api.app).post("/revalidate", json={"thread_id": "trip-test-reval-0002", "edits": {}})
    assert r.status_code == 200, r.text
