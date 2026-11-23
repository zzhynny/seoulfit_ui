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
    answers.update({1: POOL[0:4], 2: POOL[5:9]})
    out = planner.plan_node(_state(days=2))

    assert out["current_step"] == "critic", out["messages"]
    assert len(calls) == 2
    it = out["itinerary"]
    assert [d["day"] for d in it["days"]] == [1, 2]
    assert _names(it["days"][0])[:4] == POOL[0:4]
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
    answers.update({1: POOL[0:4], 2: [POOL[0]] + POOL[5:7]})
    it = planner.plan_node(_state(days=2))["itinerary"]
    d1, d2 = (_names(d) for d in it["days"])
    assert POOL[0] in d1 and POOL[0] not in d2
    assert len(d2) >= 3  # the validator backfilled the dropped slot to relaxed's minimum


def test_one_failed_day_is_rebuilt_from_candidates(llm):
    _, answers = llm
    answers.update({1: POOL[0:4], 2: RuntimeError("503")})
    out = planner.plan_node(_state(days=2))
    assert out["current_step"] == "critic"
    day2 = out["itinerary"]["days"][1]
    assert day2["day"] == 2 and len(day2["pois"]) >= 3


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
    assert len(day2) >= 3


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


def _rejected_state():
    """The judge turned every day down: no anchors, its courses kept aside."""
    state = _state(days=2)
    for seg in state["day_segments"]:
        seg["rejected_courses"], seg["anchor_courses"] = seg["anchor_courses"], []
    state["retrieved_courses"] = []
    return state


def _restored(out):
    assert out["current_step"] == "critic", out["messages"]
    assert [c["course_id"] for c in out["retrieved_courses"]] == ["c1"]
    assert all(s["anchor_courses"] for s in out["day_segments"])
    assert all(any(n in POOL for n in _names(d)) for d in out["itinerary"]["days"])


def test_rejected_courses_come_back_when_there_is_no_places_key(llm):
    calls, answers = llm            # the fixture blanks GOOGLE_PLACES_API_KEY
    answers.update({1: POOL[0:4], 2: POOL[5:9]})
    _restored(planner.plan_node(_rejected_state()))


def test_rejected_courses_come_back_when_places_finds_nothing(llm, monkeypatch):
    calls, answers = llm
    answers.update({1: POOL[0:4], 2: POOL[5:9]})
    monkeypatch.setattr(planner, "GOOGLE_PLACES_API_KEY", "test-key")
    monkeypatch.setattr(planner, "build_google_supplement_by_areas", lambda **kw: [])
    _restored(planner.plan_node(_rejected_state()))


def test_rejected_courses_stay_out_when_places_fills_the_day(llm, monkeypatch):
    calls, answers = llm
    answers.update({1: ["g 0", "g 1", "g 2"], 2: ["g 3", "g 4", "g 5"]})
    monkeypatch.setattr(planner, "GOOGLE_PLACES_API_KEY", "test-key")
    found = [{"poi_name": f"g {i}", "area": "jongno", "lat": 37.5729, "lng": 126.9794,
              "poi_type": "tourist_spot", "source_kind": "google"} for i in range(8)]
    monkeypatch.setattr(planner, "build_google_supplement_by_areas", lambda **kw: found)
    out = planner.plan_node(_rejected_state())
    assert out["current_step"] == "critic", out["messages"]
    assert out["retrieved_courses"] == []
    assert all(s["anchor_courses"] == [] for s in out["day_segments"])


def test_revise_days_react_uses_a_tool_found_place(llm, monkeypatch):
    # The agent searches once, then answers with a place only the tool found.
    # The validator must keep it (it rides in as a supplement row) and still
    # drop the day-1 place the agent tried to reuse.
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage

    import critic_repair
    import revise_agent

    calls, _ = llm

    class Fake(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kw):
            return self

    day = {"theme": "t", "pois": [{"name": n} for n in ["New Museum", POOL[0], *POOL[10:13]]]}
    monkeypatch.setattr(revise_agent, "_model", lambda: Fake(responses=[
        AIMessage(content="", tool_calls=[{"name": "search_places", "id": "t1",
                                           "args": {"area": "jongno", "category": "museum"}}]),
        AIMessage(content=json.dumps(day)),
    ]))
    monkeypatch.setattr(planner, "GOOGLE_PLACES_API_KEY", "x")
    monkeypatch.setattr(critic_repair, "google_fallback_candidates", lambda **k: [
        critic_repair.candidate_from_google({"poi_name": "New Museum", "poi_type": "museum",
                                             "lat": 37.5729, "lng": 126.9794, "area": "jongno"})])
    revise_agent.STATS.clear()
    itinerary = {"days": [
        {"day": 1, "pois": [{"name": n} for n in POOL[0:5]]},
        {"day": 2, "pois": [{"name": n} for n in POOL[5:10]]},
    ]}

    out = planner.revise_days(_state(days=2), itinerary, {2: ["X is closed on Tuesdays."]}, react=True)

    day2 = _names(out["days"][1])
    assert "New Museum" in day2 and POOL[0] not in day2
    assert calls == []                                    # no one-shot fallback
    assert revise_agent.STATS == {"ok": 1, "tool_calls": 1}


# --- CRAG: correct days skip Google Places -----------------------------------

def test_an_area_whose_every_day_is_correct_is_not_searched(llm, monkeypatch):
    calls, answers = llm
    answers.update({1: POOL[0:4], 2: POOL[5:9]})
    monkeypatch.setattr(planner, "GOOGLE_PLACES_API_KEY", "test-key")
    searched = []
    monkeypatch.setattr(planner, "build_google_supplement_by_areas",
                        lambda **kw: searched.append(kw["requested_areas"]) or [])
    state = _state(days=2)
    for seg in state["day_segments"]:
        seg["skip_search"] = True
    out = planner.plan_node(state)
    assert out["current_step"] == "critic", out["messages"]
    assert searched == []

    state["day_segments"][1]["skip_search"] = False      # one day still needs help
    planner.plan_node(state)
    assert searched == [["jongno"]]


# --- ReAct builds a null day -------------------------------------------------

def _react_model(monkeypatch, day):
    """The agent searches once, then answers with `day`."""
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage

    import revise_agent

    class Fake(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kw):
            return self

    monkeypatch.setattr(revise_agent, "_model", lambda: Fake(responses=[
        AIMessage(content="", tool_calls=[{"name": "search_places", "id": "t1",
                                           "args": {"area": "jongno", "category": "museum"}}]),
        AIMessage(content=json.dumps(day)),
    ]))
    revise_agent.STATS.clear()
    return revise_agent


def _null_day_2(monkeypatch):
    """Day 1 has its course; the judge turned day 2's down and Places found some."""
    import critic_repair

    state = _state(days=2)
    seg = state["day_segments"][1]
    seg["rejected_courses"], seg["anchor_courses"] = seg["anchor_courses"], []
    monkeypatch.setattr(planner, "GOOGLE_PLACES_API_KEY", "test-key")
    found = [{"poi_name": f"g {i}", "area": "jongno", "lat": 37.5729, "lng": 126.9794,
              "poi_type": "tourist_spot", "source_kind": "google"} for i in range(3)]
    monkeypatch.setattr(planner, "build_google_supplement_by_areas", lambda **kw: found)
    monkeypatch.setattr(critic_repair, "google_fallback_candidates", lambda **k: [
        critic_repair.candidate_from_google({"poi_name": "New Museum", "poi_type": "museum",
                                             "lat": 37.5729, "lng": 126.9794, "area": "jongno"})])
    return state


def test_a_null_day_is_built_by_the_react_agent(llm, monkeypatch):
    calls, answers = llm
    answers.update({1: POOL[0:4]})
    agent = _react_model(monkeypatch, {"theme": "t", "pois": [
        {"name": n} for n in ["New Museum", "g 0", "g 1", "g 2"]]})

    out = planner.plan_node(_null_day_2(monkeypatch))

    assert out["current_step"] == "critic", out["messages"]
    assert [int(re.search(r"=== DAY (\d+) ", c).group(1)) for c in calls] == [1]  # day 2 never one-shot
    day2 = _names(out["itinerary"]["days"][1])
    # Only a tool found it: the validator keeps it because it joined the
    # supplement, and so does the critic's candidate pool.
    assert "New Museum" in day2
    assert "New Museum" in {r["poi_name"] for r in out["planning_context"]["google_supplement"]}
    assert agent.STATS == {"ok": 1, "tool_calls": 1}


def test_null_day_react_off_keeps_the_one_shot(llm, monkeypatch):
    calls, answers = llm
    answers.update({1: POOL[0:4], 2: ["g 0", "g 1", "g 2"]})
    agent = _react_model(monkeypatch, {"pois": []})
    monkeypatch.setenv("NULL_DAY_REACT", "0")

    out = planner.plan_node(_null_day_2(monkeypatch))

    assert out["current_step"] == "critic", out["messages"]
    assert sorted(int(re.search(r"=== DAY (\d+) ", c).group(1)) for c in calls) == [1, 2]
    assert agent.STATS == {}
