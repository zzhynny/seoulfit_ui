"""plan_node makes one Gemini call per day and merges the results."""
import json
import re

import pytest

import planner

POOL = [f"poi {i}" for i in range(20)]


def _state(days=2, region="jongno"):
    course = {"course_id": "c1", "source_url": "u", "sequence": [
        {"poi_name": n, "lat": 37.5729, "lng": 126.9794, "estimated_stay_time": 60} for n in POOL
    ]}
    segs = [{"day_numbers": [d], "area": region, "note": "rent hanbok" if d == 1 else "",
             "anchor_courses": [course]} for d in range(1, days + 1)]
    return {
        "retrieved_courses": [course],
        "day_segments": segs,
        "day_specs": [{"day": d, "region": region, "note": ""}
                      for d in range(1, days + 1)],
        "travel_dates": f"x ({days} days)",
        "pace": "relaxed",
        "messages": [],
    }


@pytest.fixture
def llm(monkeypatch):
    """Fake Gemini: `answers[day]` is the day's POI names, or an exception."""
    monkeypatch.setattr(planner, "GOOGLE_PLACES_API_KEY", "")
    calls: list[str] = []
    answers: dict[int, object] = {}

    def fake(prompt: str) -> str:
        calls.append(prompt)
        day = int(re.search(r"=== DAY (\d+) CANDIDATES", prompt).group(1))
        ans = answers[day]
        if isinstance(ans, Exception):
            raise ans
        return json.dumps({"theme": f"T{day}", "summary": f"Day {day} sentence.",
                           "pois": [{"name": n, "priority": 1} for n in ans],
                           "sources": [{"course_id": "c1"}]})

    monkeypatch.setattr(planner, "_gemini_text", fake)
    return calls, answers


def _names(day):
    return [p["name"] for p in day["pois"]]


def test_one_call_per_day_merged_in_order(llm):
    calls, answers = llm
    answers.update({1: POOL[0:5], 2: POOL[5:10]})
    out = planner.plan_node(_state(days=2))

    assert out["current_step"] == "critic", out["messages"]
    assert len(calls) == 2
    it = out["itinerary"]
    assert [d["day"] for d in it["days"]] == [1, 2]
    assert _names(it["days"][0])[:5] == POOL[0:5]
    assert it["summary"] == "Day 1 sentence. Day 2 sentence."
    assert [s["course_id"] for s in it["sources"]] == ["c1"]
    assert "PACE: relaxed pace" in calls[0]
    day1 = next(c for c in calls if "=== DAY 1 " in c)
    day2 = next(c for c in calls if "=== DAY 2 " in c)
    assert "Traveller's note for this day: rent hanbok" in day1
    assert "Traveller's note" not in day2
    assert it["days"][0]["pois"][0]["priority"] == 1   # survives canonicalisation


def test_a_place_on_two_days_stays_on_the_first(llm):
    _, answers = llm
    answers.update({1: POOL[0:5], 2: [POOL[0]] + POOL[5:9]})
    it = planner.plan_node(_state(days=2))["itinerary"]
    d1, d2 = (_names(d) for d in it["days"])
    assert POOL[0] in d1 and POOL[0] not in d2
    assert len(d2) >= 5  # the validator backfilled the dropped slot


def test_one_failed_day_is_rebuilt_from_candidates(llm):
    _, answers = llm
    answers.update({1: POOL[0:5], 2: RuntimeError("503")})
    out = planner.plan_node(_state(days=2))
    assert out["current_step"] == "critic"
    day2 = out["itinerary"]["days"][1]
    assert day2["day"] == 2 and len(day2["pois"]) >= 5


def test_every_day_failing_is_a_generation_error(llm):
    _, answers = llm
    answers.update({1: RuntimeError("503"), 2: RuntimeError("503")})
    out = planner.plan_node(_state(days=2))
    assert not out.get("itinerary")
    assert out["current_step"] == "confirm"


def test_revise_days_redoes_only_the_flagged_day_without_reusing_places(llm):
    calls, answers = llm
    state = _state(days=2)
    itinerary = {"days": [
        {"day": 1, "pois": [{"name": n} for n in POOL[0:5]]},
        {"day": 2, "pois": [{"name": n} for n in POOL[5:10]]},
    ]}
    # The model tries to reuse day 1's first place; it must not survive.
    answers[2] = [POOL[0]] + POOL[10:14]

    out = planner.revise_days(state, itinerary, {2: ["Gyeongbokgung is closed on Tuesdays."]})

    assert len(calls) == 1
    assert "Gyeongbokgung is closed on Tuesdays." in calls[0]
    assert _names(out["days"][0]) == POOL[0:5]           # untouched
    day2 = _names(out["days"][1])
    assert POOL[0] not in day2 and POOL[10] in day2
    assert len(day2) >= 5


def test_unrepairable_json_raises_the_json_error():
    # Used to raise NameError: `first_err` is unbound once its except block ends.
    with pytest.raises(json.JSONDecodeError):
        planner._parse_itinerary_json("{not json at all", use_llm_fallback=False)


def test_each_day_is_told_its_weekday_and_never_shown_a_stop_closed_that_day(llm):
    calls, answers = llm
    answers.update({1: POOL[0:5], 2: POOL[5:10]})
    state = _state(days=2)
    closed = {"poi_name": "Closed On Tuesdays", "lat": 37.5729, "lng": 126.9794,
              "estimated_stay_time": 60, "opening_hours": {"closed_weekday": ["Tuesday"]}}
    for seg in state["day_segments"]:
        seg["anchor_courses"][0]["sequence"].append(closed)
    # 2026-10-19 is a Monday, so day 2 is a Tuesday. Vegetarian, and no
    # Google key here, so no vegetarian restaurant is found: meals stay open.
    state.update(trip_start_date="2026-10-19", diet="vegetarian", restrictions="vegetarian")

    planner.plan_node(state)
    day1 = next(c for c in calls if "=== DAY 1 " in c)
    day2 = next(c for c in calls if "=== DAY 2 " in c)

    assert "This day is a Monday." in day1 and "This day is a Tuesday." in day2
    assert "Closed On Tuesdays" in day1 and "Closed On Tuesdays" not in day2
    assert "Day 1 lunch is open: no verified vegetarian restaurant" in day1
    assert "Day 2 dinner is open" in day2
