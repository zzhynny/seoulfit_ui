"""place_facts (Google hours + review labels by name) and what reads it:
retrieval drops closed places and fills closed_weekday, fix_opening_hours moves
a stop that would arrive while shut, and tips only say what the facts say."""
import pytest

import place_facts
import planner
import retrieval
from critic_repair import CriticAgent


def mon(open_, close):
    return {"open": {"day": 1, "time": open_}, "close": {"day": 1, "time": close}}


FACTS = {
    "mall": {"found": True, "periods": [mon("1030", "2030")]},
    "lateopener": {"found": True, "periods": [mon("1400", "2200")]},
    "gone": {"found": True, "closed_permanently": True},
    "allday": {"found": True, "periods": [{"open": {"day": 0, "time": "0000"}}]},
    "cashbar": {"found": True, "cash_only": 1, "english_support": 1,
                "cultural_friction": 1, "evidence": "Shoes off at the door."},
}


@pytest.fixture(autouse=True)
def facts(monkeypatch):
    monkeypatch.setattr(place_facts, "_all", lambda: FACTS)
    monkeypatch.setattr(planner, "LEG_SLACK_MIN", 0)


def stop(name, stay=60):
    return {"name": name, "type": "tourist_spot", "lat": 37.57, "lng": 126.98, "stay_minutes": stay}


def test_hours_use_restaurant_json_shape_and_empty_days_are_closed():
    h = place_facts.hours("Mall")
    assert h["Monday"] == ["10:30-20:30"] and h["Tuesday"] == []
    assert "Monday" not in place_facts.closed_weekdays("Mall")
    assert place_facts.closed_weekdays("Allday") == []
    assert place_facts.hours("Unknown") is None and place_facts.closed_weekdays("Unknown") is None


def test_tips_say_only_what_the_facts_say():
    assert place_facts.tips("Cash Bar") == "Cash only, so bring won. Heads-up: Shoes off at the door."
    assert place_facts.tips("Mall") == "" and place_facts.tips("Unknown") == ""


def test_a_stop_arriving_before_it_opens_moves_later():
    # 10:00 at a mall that opens 10:30: the park (no hours) goes first instead.
    out = planner.fix_opening_hours([stop("Mall"), stop("Park")], "Monday", 21 * 60)
    assert [p["name"] for p in out] == ["Park", "Mall"]


def test_a_stop_that_fits_nowhere_stays_put():
    # Opens 14:00; the whole day ends at 12:00, so no position opens it.
    day = [stop("Late Opener"), stop("Park")]
    assert planner.fix_opening_hours(day, "Monday", 21 * 60) == day
    assert planner.fix_opening_hours(day, None, 21 * 60) == day


def test_courses_lose_closed_places_and_gain_closed_weekday():
    seq = [{"poi_name": "Gone"}, {"poi_name": "Mall"},
           {"poi_name": "Allday", "opening_hours": {"closed_weekday": ["Tuesday"]}},
           {"poi_name": "Unknown"}]
    out = retrieval._with_place_facts(seq)
    assert [p["poi_name"] for p in out] == ["Mall", "Allday", "Unknown"]
    assert "Tuesday" in out[0]["opening_hours"]["closed_weekday"]
    assert out[1]["opening_hours"]["closed_weekday"] == ["Tuesday"]   # verified value kept
    assert "opening_hours" not in out[2]


def test_foreigner_readiness_reads_labels_by_name():
    issues = []
    itin = {"days": [{"day": 1, "pois": [stop("Cash Bar"), stop("Unknown")]}]}
    assert CriticAgent()._evaluate_foreigner_readiness(itin, issues)["score"] == 0.75
    assert [i.code for i in issues] == ["HIGH_FOREIGNER_FRICTION"]


def test_learn_hours_fetches_only_unknown_non_meal_stops(monkeypatch):
    import critic_repair
    monkeypatch.undo()  # the conftest no-op, the facts and the slack
    monkeypatch.setattr(place_facts, "_all", lambda: FACTS)
    monkeypatch.setattr(place_facts, "_live", {})
    calls = []

    def fake_get(url, params):
        calls.append((url.rsplit("/", 2)[-2], params.get("input") or params.get("place_id")))
        if "findplace" in url:
            return {"candidates": [{"place_id": "found-id"}]}
        return {"result": {"opening_hours": {"periods": [mon("1800", "2300")]}}}

    monkeypatch.setattr(planner, "_google_get", fake_get)
    state = {"planning_context": {"google_supplement": [{"poi_name": "Jazz Bar", "place_id": "sup-id"}]}}
    lunch = {**stop("Noodles"), "meal_slot": "lunch"}
    critic_repair._learn_hours([stop("Mall"), stop("Jazz Bar"), stop("Club"), lunch], state)
    # Mall is in the file, the meal is meal_slots' job; the supplement skips Find Place.
    assert sorted(calls) == [("details", "found-id"), ("details", "sup-id"), ("findplacefromtext", "Club")]
    assert place_facts.hours("Jazz Bar")["Monday"] == ["18:00-23:00"]
    critic_repair._learn_hours([stop("Club")], state)
    assert len(calls) == 3   # remembered, not fetched again


def test_a_shut_stop_with_nowhere_to_go_is_swapped_or_dropped():
    from critic_repair import _replace_shut_stops
    jongno = lambda name: {**stop(name), "area": "jongno"}  # noqa: E731
    day = [jongno("Late Opener")] + [jongno(f"Park {i}") for i in range(4)]
    pool = {"allday": {**jongno("Allday"), "source_kind": "course"},
            "mall": {**jongno("Mall"), "source_kind": "course"}}   # shut at 10:00 too
    logs = []
    out = _replace_shut_stops(day, "Monday", pool, set(), {}, 21 * 60, logs, 1)
    assert [p["name"] for p in out][0] == "Allday" and len(out) == 5
    # No open candidate: dropped while 3+ sights remain, kept below that.
    out = _replace_shut_stops(day, "Monday", {}, set(), {}, 21 * 60, logs, 1)
    assert [p["name"] for p in out] == [f"Park {i}" for i in range(4)]
    core = [{**day[0], "priority": 1}] + day[1:]
    assert _replace_shut_stops(core, "Monday", {}, set(), {}, 21 * 60, logs, 1) == core
    other_type = {"x": {**jongno("Allday"), "type": "shopping", "source_kind": "course"}}
    assert _replace_shut_stops(core, "Monday", other_type, set(), {}, 21 * 60, logs, 1) == core
    short = day[:3]
    assert _replace_shut_stops(short, "Monday", {}, set(), {}, 21 * 60, logs, 1) == short
