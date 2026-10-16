import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "evals"))
import ab_score

import planner


@pytest.fixture(autouse=True)
def _no_slack(monkeypatch):
    """The expected minutes below are bare travel time."""
    monkeypatch.setattr(planner, "LEG_SLACK_MIN", 0)
    monkeypatch.setattr(planner, "_DAY_END", {"packed": 22 * 60})
    monkeypatch.setattr(planner, "_DAY_END_DEFAULT", 21 * 60)

STATE = {"day_specs": [{"day": 1, "region": "seongsu"}]}
SEONGSU = {"name": "Seoul Forest", "address": "Seongdong-gu", "lat": 37.5444, "lng": 127.0374}
JONGNO = {"name": "광장시장", "address": "Jongno-gu", "lat": 37.5704, "lng": 127.0003,
          "notes": ab_score.FILLER_NOTE}
LUNCH = {"name": "L", "lat": 37.5445, "lng": 127.0375, "meal_slot": "lunch",
         "verified": {"opening_hours": True, "cuisine": False}}


def test_score_flags_off_area_filler_far_leg_and_meals():
    it = {"days": [{"day": 1, "pois": [SEONGSU, LUNCH, JONGNO]}]}
    s = ab_score.score(it, STATE, gold=[(37.5444, 127.0374)])
    assert s["stops"] == 2 and s["gold_hits"] == 1
    assert s["off_area"] == 1 and s["filler"] == 1
    assert s["far_legs"] == 1 and s["max_leg_km"] > 3
    assert s["missing_meals"] == 1 and s["unverified_meals"] == 1
    assert s["late_min"] == 0 and s["end_min"] > 10 * 60


def test_late_min_counts_minutes_past_the_pace_end():
    long = [{**SEONGSU, "name": f"S{i}", "stay_minutes": 180} for i in range(4)]
    s = ab_score.score({"days": [{"day": 1, "pois": long}]}, STATE, gold=[])
    assert s["end_min"] == 22 * 60 and s["late_min"] == 60     # 10:00 + 12h, past 21:00
    assert s["late_over_grace"] == 30                           # past 21:30


def test_lunch_late_min_counts_minutes_after_the_window():
    late = [{**SEONGSU, "name": "S", "stay_minutes": 240}, {**LUNCH, "stay_minutes": 60}]
    s = ab_score.score({"days": [{"day": 1, "pois": late}]}, STATE, gold=[])
    assert s["lunch_late_min"] == 30                           # 14:00 vs 13:30


def test_filler_counts_only_when_it_is_off_area():
    near = {**SEONGSU, "name": "Near fill", "notes": ab_score.FILLER_NOTE}
    s = ab_score.score({"days": [{"day": 1, "pois": [near, JONGNO]}]}, STATE, gold=[])
    assert s["filler"] == 1      # JONGNO is the off-area fill; the Seongsu one is a good fill


def test_sign_test():
    assert ab_score.sign_test(0, 0) == 1.0
    assert ab_score.sign_test(5, 5) == 1.0
    assert round(ab_score.sign_test(10, 0), 4) == 0.002


def test_compare_averages_reps_per_scenario():
    a, b = dict.fromkeys((m for m, _ in ab_score.METRICS), 0), None
    b = {**a, "stops": 2}
    rows = [{"scenario_id": 1, "A": a, "B": b}, {"scenario_id": 1, "A": a, "B": a}]
    stops = next(r for r in ab_score.compare(rows) if r[0] == "stops")
    assert stops[2:7] == (0, 1, 1, 0, 0)  # one scenario, B wins on mean 1 > 0
