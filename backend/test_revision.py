"""critic_repair_node sends days with surviving high-severity issues back to
the LLM once, and keeps the result only if the critic scores it no worse."""
import pytest

import critic_repair
import eval_store
import planner

GANGNAM = (37.4979, 127.0276)
BUKCHON = (37.5826, 126.9836)


def _poi(name, at, ptype="tourist_spot"):
    return {"name": name, "type": ptype, "address": "", "lat": at[0], "lng": at[1],
            "stay_minutes": 60, "notes": ""}


def _day(n, prefix, at):
    return {"day": n, "pois": [_poi(f"{prefix} {i}", at) for i in range(5)]
            + [_poi(f"{prefix} cafe", at, "cafe")]}


def _state(day1):
    # Day 1 was meant to be Bukchon. The candidate pool is empty, so the code
    # repairer has nothing to fix it with and the high issue survives.
    return {
        "day_specs": [{"day": 1, "region": "bukchon"},
                      {"day": 2, "region": "gangnam"}],
        "itinerary": {"days": [day1, _day(2, "gangnam", GANGNAM)]},
        "retrieved_courses": [],
        "planning_context": {"requested_areas": ["bukchon", "gangnam"], "google_supplement": []},
    }


@pytest.fixture
def node(monkeypatch):
    monkeypatch.setattr(eval_store, "save_eval", lambda **k: None)  # never the real DB
    monkeypatch.setattr(planner, "describe_itinerary", lambda *a: None)  # no live Gemini
    calls = []

    def run(state, revise):
        def fake(st, itinerary, flagged):
            calls.append(flagged)
            return revise(itinerary)
        monkeypatch.setattr(planner, "revise_days", fake)
        return critic_repair.make_critic_repair_node()(state)

    return run, calls


def _set_day1(pois_at, prefix):
    def revise(itinerary):
        itinerary["days"][0] = _day(1, prefix, pois_at)
        return itinerary
    return revise


def _log(out):
    return out["critic_report"]["repair_log"]


def test_no_surviving_high_issue_means_no_revision(node):
    run, calls = node
    out = run(_state(_day(1, "bukchon", BUKCHON)), _set_day1(BUKCHON, "x"))
    assert calls == []
    assert not any("Revised" in line for line in _log(out))


def test_a_revision_that_fixes_the_day_is_kept(node):
    run, calls = node
    out = run(_state(_day(1, "wrong", GANGNAM)), _set_day1(BUKCHON, "bukchon"))
    assert list(calls[0]) == [1]
    assert "Bukchon" in calls[0][1][0]
    assert out["itinerary"]["days"][0]["pois"][0]["name"] == "bukchon 0"
    assert out["critic_report"]["after"]["area_coverage"]["bukchon"] > 0
    assert any("accepted" in line for line in _log(out))


def test_a_revision_that_scores_worse_is_dropped(node):
    run, _ = node

    def worse(itinerary):
        itinerary["days"][0]["pois"] = []
        return itinerary

    out = run(_state(_day(1, "wrong", GANGNAM)), worse)
    assert out["itinerary"]["days"][0]["pois"][0]["name"] == "wrong 0"
    assert any("rejected" in line for line in _log(out))


def test_a_failed_revision_keeps_the_trip(node):
    run, _ = node

    def boom(_itinerary):
        raise RuntimeError("503")

    out = run(_state(_day(1, "wrong", GANGNAM)), boom)
    assert out["current_step"] == "done"
    assert out["itinerary"]["days"][0]["pois"][0]["name"] == "wrong 0"
    assert any("failed" in line for line in _log(out))


def _describe(monkeypatch, reply):
    """Run the real describe_itinerary against a fake Gemini reply."""
    monkeypatch.setattr(eval_store, "save_eval", lambda **k: None)
    seen = []

    def fake(prompt):
        seen.append(prompt)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(planner, "_gemini_text", fake)
    state = _state(_day(1, "bukchon", BUKCHON))
    state["itinerary"]["summary"] = "Old summary naming Changdeokgung."
    for d in state["itinerary"]["days"]:
        d["theme"] = f"Old theme {d['day']}"
    return critic_repair.make_critic_repair_node()(state), seen


def test_summary_and_themes_are_rewritten_from_the_final_stops(monkeypatch):
    import json
    out, seen = _describe(monkeypatch, json.dumps({
        "summary": "Bukchon then Gangnam.", "themes": {"1": "Hanok lanes", "9": "Ghost day"}}))
    it = out["itinerary"]
    assert "bukchon 0" in seen[0] and "gangnam 0" in seen[0]   # prompt lists the final stops
    assert it["summary"] == "Bukchon then Gangnam."
    assert [d["theme"] for d in it["days"]] == ["Hanok lanes", "Old theme 2"]
    assert [d["day"] for d in it["days"]] == [1, 2]            # day 9 not invented


def test_a_failed_description_keeps_the_generated_text(monkeypatch):
    out, _ = _describe(monkeypatch, RuntimeError("503"))
    assert out["current_step"] == "done"
    assert out["itinerary"]["summary"] == "Old summary naming Changdeokgung."
    assert out["itinerary"]["days"][0]["theme"] == "Old theme 1"


def test_a_day_past_its_end_time_loses_stops(node):
    run, _ = node
    long_day = _day(1, "bukchon", BUKCHON)
    for p in long_day["pois"]:
        p["stay_minutes"] = 150            # 6 x 2.5h from 10:00 -> 01:00
    state = {**_state(long_day), "pace": "relaxed"}
    out = run(state, lambda it: it)
    day1 = out["itinerary"]["days"][0]["pois"]
    assert len(day1) < 6
    assert any("dropped" in line and "Day 1" in line for line in _log(out))
    assert len(out["itinerary"]["days"][0]["transit_legs"]) == len(day1) - 1


def test_a_stop_swapped_for_a_closed_one_keeps_its_priority():
    # 2026-10-13 is a Tuesday; the palace is closed Tuesdays.
    def raw(name, lat, closed=None):
        return {"poi_name": name, "poi_type": "history", "area": "jongno",
                "lat": lat, "lng": 126.98, "estimated_stay_time": 90,
                "opening_hours": {"closed_weekday": closed} if closed else None}

    course = {"course_id": "c1", "sequence": [raw("Closed Palace", 37.575, ["Tuesday"]),
                                              raw("Open Palace", 37.576),
                                              {**raw("Market", 37.570), "poi_type": "market"}]}
    state = {
        "trip_start_date": "2026-10-13",
        "day_specs": [{"day": 1, "region": "jongno"}],
        "retrieved_courses": [course],
        "planning_context": {"requested_areas": ["jongno"], "google_supplement": []},
        "itinerary": {"days": [{"day": 1, "pois": [
            {"name": "Closed Palace", "type": "history", "lat": 37.575, "lng": 126.98,
             "stay_minutes": 90, "notes": "", "area": "jongno", "priority": 1},
            # A second Jongno stop, so area coverage is met and doesn't claim
            # the open palace before the closed-day swap looks for it.
            {"name": "Market", "type": "market", "lat": 37.570, "lng": 126.98,
             "stay_minutes": 60, "notes": "", "area": "jongno", "priority": 2}]}]},
    }
    report = critic_repair.CriticAgent().evaluate(state)
    fixed, logs = critic_repair.RepairAgent().repair(state, report)
    swapped = fixed["days"][0]["pois"][0]
    assert swapped["name"] == "Open Palace", logs
    assert swapped["priority"] == 1


def _meal_poi(name, slot, tier, at=BUKCHON):
    return {**_poi(name, at, "restaurant"), "meal_slot": slot, "source_tier": tier}


def test_a_diet_day_with_an_open_or_unverified_meal_cannot_score_one(node):
    run, calls = node
    day1 = _day(1, "bukchon", BUKCHON)
    day1["pois"] += [_meal_poi("Veg Lunch", "lunch", "google")]          # no dinner at all
    day2 = _day(2, "gangnam", GANGNAM)
    day2["pois"] += [_meal_poi("Leaf", "lunch", "michelin", GANGNAM),
                     _meal_poi("Sprout", "dinner", "michelin", GANGNAM)]
    state = {**_state(day1), "diet": "vegetarian"}
    state["itinerary"]["days"][1] = day2

    out = run(state, lambda it: it)
    after = out["critic_report"]["after"]
    codes = [(i["code"], i["severity"], i["day"]) for i in after["issues"]]
    assert ("DIET_MEAL_UNVERIFIED", "medium", 1) in codes
    assert ("DIET_MEAL_OPEN", "medium", 1) in codes
    assert not [c for c in codes if c[2] == 2]          # verified Michelin day is clean
    assert after["overall_score"] < 1.0
    assert calls == []                                  # medium: no Gemini revision


def test_the_missing_meal_repair_adds_only_a_cafe_for_a_diet():
    import critic_repair as cr
    pool_items = {
        "meat house": {"name": "Meat House", "type": "restaurant", "area": "bukchon", "lat": 37.58, "lng": 126.98},
        "tea cafe": {"name": "Tea Cafe", "type": "cafe", "area": "bukchon", "lat": 37.58, "lng": 126.98},
    }
    day = {"day": 1, "pois": [_poi("Sight", BUKCHON)]}
    for diet, want in ((None, "Meat House"), ("vegetarian", "Tea Cafe")):
        it = {"days": [{**day, "pois": list(day["pois"])}]}
        out = cr.RepairAgent()._repair_missing_meals(
            itinerary=it, pool=pool_items, requested_areas=["bukchon"], logs=[], diet=diet)
        added = [p["name"] for p in out["days"][0]["pois"] if p["name"] != "Sight"]
        assert added == [want], (diet, added)
