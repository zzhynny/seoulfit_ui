"""Self-check for the day-cap fold redesign, the day-level pace-aware
trim/fill bounds, and pace-aware POI targets in planner.py/rag.py. Together
these fix the "17-42 POIs crammed into one day" bug: the fold spreads
overflow across days when there's more than one day, and the trim step
(added after the fold no longer has anywhere to redistribute to, e.g. a
1-day trip) caps any single day at the pace's max instead of leaving
everything the fold couldn't redistribute in place.

Note: an earlier version of this fix added state["start_date"]/state["num_days"]
fields end-to-end (state.py/graph.py/api.py). That was abandoned when
kdlee02's "Collect trip details one question at a time" (PR #3, commit
b56d9b6) landed on origin/main with a different, already-shipped mechanism:
graph.collect_node's date-picker flow bakes the day count straight into
travel_dates as a "(N days)" suffix (see graph._describe_trip), which the
existing rag._parse_num_days text parser already reads correctly -- no
separate state field needed. planner._resolve_num_days/the `num_days`
override parameter added here are kept as a seam for a future caller that
has an explicit count without text (see their docstrings) but resolve to
None/unused in the actual app today; that's expected, not a bug.

No framework, no network/LLM key needed: monkeypatches planner._gemini_text
with a scripted reply. Run: `python test_num_days_fix.py`.
"""
import json
from datetime import date

import graph
import planner
import rag


def test_parse_num_days_override():
    # override wins even when duration text would parse to something else.
    assert rag._parse_num_days("this is not a date", override=4) == 4
    assert rag._parse_num_days("", override=4) == 4
    assert rag._parse_num_days(None, override=4) == 4
    # override=0/None doesn't short-circuit -- legacy text parsing still runs.
    assert rag._parse_num_days("4 days", override=None) == 4
    assert rag._parse_num_days("4 days", override=0) == 4
    assert rag._parse_num_days("2박 3일") == 3
    print("OK - _parse_num_days override")


def test_resolve_num_days():
    assert planner._resolve_num_days({"num_days": 4}) == 4
    assert planner._resolve_num_days({"num_days": 0}) == 3       # invalid -> safe default
    assert planner._resolve_num_days({"num_days": -2}) == 3      # invalid -> safe default
    assert planner._resolve_num_days({"num_days": None}) is None  # not sent -> use travel_dates text
    assert planner._resolve_num_days({}) is None
    print("OK - _resolve_num_days")


def test_parse_day_segments_override_bypasses_text_parsing():
    # "asdf" alone would legacy-parse to 1 day; override must win regardless.
    segments = rag.parse_day_segments(location="", purpose="", duration="asdf", num_days=4)
    assert len(segments) == 1
    assert segments[0]["day_numbers"] == [1, 2, 3, 4], segments[0]["day_numbers"]
    print("OK - parse_day_segments num_days override")


def test_pace_bounds():
    assert planner._pace_bounds({"pace": "relaxed"}) == (5, 6)
    assert planner._pace_bounds({"pace": "packed"}) == (7, 8)
    assert planner._pace_bounds({"pace": None}) == (6, 7)   # no pace on record -- middling default
    assert planner._pace_bounds({}) == (6, 7)
    assert planner._pace_bounds({"pace": "PACKED"}) == (7, 8)  # case-insensitive
    print("OK - _pace_bounds")


def test_pace_target_line():
    # Single source of truth: the numbers in the prompt line must always
    # match _pace_bounds exactly (that's the whole point of routing both
    # through it) -- assert against _pace_bounds' own output, not literals.
    lo, hi = planner._pace_bounds({"pace": "packed"})
    assert f"{lo}-{hi}" in planner._pace_target_line({"pace": "packed"})
    lo, hi = planner._pace_bounds({"pace": "relaxed"})
    assert f"{lo}-{hi}" in planner._pace_target_line({"pace": "relaxed"})
    assert planner._pace_target_line({"pace": None}) == ""
    assert planner._pace_target_line({}) == ""
    assert planner._pace_target_line({"pace": "PACKED"}) != ""  # case-insensitive
    print("OK - _pace_target_line")


def _poi(name: str) -> dict:
    return {"name": name, "type": "tourist_spot", "address": "", "lat": 37.5, "lng": 127.0,
            "stay_minutes": 60, "notes": "", "area": None}


def test_fold_least_filled_not_round_robin():
    """Simulates a planner LLM that front-loaded POIs into a few of its
    over-produced days. With num_days=4, the kept days start skewed
    (3, 0, 0, 0) before 17 overflow POIs get folded in. Round-robin would
    keep adding to day 1 in lockstep with the others and end up more skewed
    (day 1 starts ahead and stays ahead); least-filled-first should end up
    balanced instead."""
    pool_names = [f"poi {i}" for i in range(20)]
    courses = [{
        "sequence": [
            {"poi_name": n, "lat": 37.5, "lng": 127.0, "estimated_stay_time": 60}
            for n in pool_names
        ],
    }]

    days = [
        {"day": 1, "pois": [_poi(pool_names[i]) for i in range(0, 3)]},
        {"day": 2, "pois": []},
        {"day": 3, "pois": []},
        {"day": 4, "pois": []},
        {"day": 5, "pois": [_poi(pool_names[i]) for i in range(3, 13)]},   # 10 overflow
        {"day": 6, "pois": [_poi(pool_names[i]) for i in range(13, 20)]},  # 7 overflow
    ]
    itinerary = {"days": days}

    result = planner._validate_and_repair_itinerary(
        itinerary,
        courses=courses,
        google_supplement=[],
        requested_areas=[],
        duration="",
        num_days=4,
        purpose="",
    )

    out_days = result["days"]
    assert len(out_days) == 4, len(out_days)
    counts = [len(d["pois"]) for d in out_days]
    assert sum(counts) == 20, counts          # no POI lost or duplicated
    assert max(counts) - min(counts) <= 1, counts  # balanced, not dumped into one day

    all_names = {p["name"] for d in out_days for p in d["pois"]}
    assert all_names == set(pool_names), all_names - set(pool_names)
    print(f"OK - fold least-filled-first, final day sizes = {counts}")


def _poi_typed(name: str, ptype: str, area: str) -> dict:
    return {"name": name, "type": ptype, "address": "", "lat": 37.5, "lng": 127.0,
            "stay_minutes": 60, "notes": "", "area": area}


def _bloated_one_day_courses_and_itinerary():
    """25 POIs spread across 5 fake LLM day-entries for what should be a
    1-day trip -- the exact shape that used to survive the fold as one day
    with 25 POIs (no upper cap existed before this trim step)."""
    pool_names = [f"poi {i}" for i in range(25)]
    types = ["restaurant" if i == 3 else "tourist_spot" for i in range(25)]
    areas = ["hongdae" if i < 15 else "seongsu" for i in range(25)]
    courses = [{
        "sequence": [
            {"poi_name": n, "lat": 37.5, "lng": 127.0, "estimated_stay_time": 60,
             "poi_type": t, "address_en": a}
            for n, t, a in zip(pool_names, types, areas)
        ],
    }]
    days = [
        {"day": i + 1, "pois": [_poi_typed(pool_names[i * 5 + j], types[i * 5 + j], areas[i * 5 + j])
                                 for j in range(5)]}
        for i in range(5)
    ]
    return courses, {"days": days}


def test_trim_over_max_keeps_meal_and_area_coverage():
    """The bug this trim step fixes: a 1-day trip has nowhere to redistribute
    overflow, so without an upper cap all 25 POIs from an over-produced LLM
    response used to survive untouched in that single day. Checks both pace
    extremes, and that the meal-slot POI and the requested area survive the
    cut."""
    for pace, expected_max in [("packed", 8), ("relaxed", 6)]:
        courses, itinerary = _bloated_one_day_courses_and_itinerary()
        result = planner._validate_and_repair_itinerary(
            itinerary, courses=courses, google_supplement=[],
            requested_areas=["hongdae"], duration="October 10, 2026 (1 day)",
            num_days=None, pace=pace, purpose="",
        )
        out_days = result["days"]
        assert len(out_days) == 1, len(out_days)
        pois = out_days[0]["pois"]
        assert len(pois) == expected_max, (pace, len(pois))  # trimmed exactly to the pace max
        assert any(planner._is_meal_poi(p) for p in pois), (pace, "meal POI lost")
        assert any(p.get("area") == "hongdae" for p in pois), (pace, "requested area lost")
        print(f"OK - trim to pace max ({pace}): 25 POIs -> {len(pois)}, meal+area survived")


def test_trim_backs_off_when_protected_set_alone_exceeds_max():
    """If the protected set (meal POIs + one per requested area) alone
    already reaches/exceeds the pace max, trimming must back off entirely
    (log only) rather than cut into coverage -- coverage wins."""
    # Real Seoul area names -- _poi_area/_infer_area_from_text_or_coords only
    # recognizes these (via alias-pattern matching on name/address text), not
    # arbitrary made-up labels.
    requested_areas = ["hongdae", "seongsu", "gangnam", "itaewon", "myeongdong", "jongno"]
    # One non-meal POI per requested area (6 protected-by-area) + one meal
    # POI in an unrelated area (protected-by-meal) = 7 protected already,
    # which alone exceeds relaxed's max of 6.
    pois = [_poi_typed(f"spot {a}", "tourist_spot", a) for a in requested_areas]
    pois.append(_poi_typed("restaurant x", "restaurant", "mapo"))
    # Two removable filler POIs duplicating an already-protected area.
    pois.append(_poi_typed("extra 1", "tourist_spot", "hongdae"))
    pois.append(_poi_typed("extra 2", "tourist_spot", "hongdae"))
    assert len(pois) == 9

    itinerary = {"days": [{"day": 1, "pois": pois}]}
    courses = [{"sequence": [
        {"poi_name": p["name"], "lat": 37.5, "lng": 127.0, "poi_type": p["type"], "address_en": p["area"]}
        for p in pois
    ]}]

    result = planner._validate_and_repair_itinerary(
        itinerary, courses=courses, google_supplement=[],
        requested_areas=requested_areas, duration="October 10, 2026 (1 day)",
        num_days=None, pace="relaxed", purpose="",
    )
    out_pois = result["days"][0]["pois"]
    # 7 protected > relaxed max (6), and only 2 removable < needed excess (3)
    # -- not enough to cut down to 6, so nothing is removed at all.
    assert len(out_pois) == 9, len(out_pois)
    print("OK - trim backs off (coverage wins) when protected set alone exceeds the pace max")


def test_plan_node_end_to_end_with_structured_num_days():
    """Full plan_node run (Gemini call monkeypatched) proving the pieces work
    together: an empty travel_dates text + structured num_days=4 still
    produces a correctly-sized, correctly-capped 4-day itinerary, and the
    prompt actually carries the resolved day count + pace guidance instead of
    an empty/guessed duration."""
    pool_names = [f"poi {i}" for i in range(12)]
    courses = [{
        "course_id": "c1",
        "sequence": [
            {"poi_name": n, "lat": 37.5, "lng": 127.0, "estimated_stay_time": 60}
            for n in pool_names
        ],
    }]

    # LLM over-produces 6 days instead of the requested 4, skewed toward day 1.
    fake_llm_days = [
        {"day": 1, "theme": "Day 1", "pois": [{"name": pool_names[i]} for i in range(0, 4)]},
        {"day": 2, "theme": "Day 2", "pois": [{"name": pool_names[i]} for i in range(4, 6)]},
        {"day": 3, "theme": "Day 3", "pois": [{"name": pool_names[i]} for i in range(6, 8)]},
        {"day": 4, "theme": "Day 4", "pois": []},
        {"day": 5, "theme": "Day 5", "pois": [{"name": pool_names[i]} for i in range(8, 10)]},
        {"day": 6, "theme": "Day 6", "pois": [{"name": pool_names[i]} for i in range(10, 12)]},
    ]
    fake_response = json.dumps({"summary": "test trip", "days": fake_llm_days})

    captured_prompts = []
    original_gemini_text = planner._gemini_text

    def fake_gemini_text(prompt: str) -> str:
        captured_prompts.append(prompt)
        return fake_response

    planner._gemini_text = fake_gemini_text
    original_google_key = planner.GOOGLE_PLACES_API_KEY
    # Disable the live Google Places supplement call -- irrelevant to what
    # this test verifies (num_days/pace wiring) and would otherwise hit the
    # real network using whatever key is in .env.
    planner.GOOGLE_PLACES_API_KEY = ""
    try:
        state = {
            "retrieved_courses": courses,
            "day_segments": None,
            "region": "",
            "category": "",
            "travel_dates": "",       # deliberately empty/stale -- structured field must carry it
            "num_days": 4,
            "pace": "packed",
            "restrictions": None,
        }
        result = planner.plan_node(state)
    finally:
        planner._gemini_text = original_gemini_text
        planner.GOOGLE_PLACES_API_KEY = original_google_key

    assert result["current_step"] == "critic", result.get("messages")
    itinerary = result["itinerary"]
    assert len(itinerary["days"]) == 4, len(itinerary["days"])

    counts = [len(d["pois"]) for d in itinerary["days"]]
    assert sum(counts) == 12, counts
    # Day 1 already had 4 fixed POIs going in (more than the 3/day average),
    # so perfect [3,3,3,3] balance isn't achievable without moving POIs out
    # of a kept day -- this fold only ever adds overflow POIs. What matters
    # is that overflow doesn't pile onto one day (the original bug): no day
    # should end up with anywhere near all 12.
    assert max(counts) <= 6, counts

    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]
    assert "Duration: 4 days" in prompt, prompt.splitlines()[:6]
    assert "PACE: packed schedule" in prompt, prompt

    print(f"OK - plan_node end-to-end, final day sizes = {counts}")


def test_plan_node_with_origin_date_picker_format():
    """The actual production path: travel_dates is exactly what
    graph._describe_trip produces for a real date-picker range (no
    state["num_days"]/state["start_date"] at all -- origin never sets them).
    _resolve_num_days must resolve to None here (nothing to override with),
    and the day count must still come out right because the "(N days)"
    suffix is baked into travel_dates itself.
    """
    days, travel_dates_label = graph._describe_trip(date(2026, 10, 10), date(2026, 10, 13))
    assert days == 4, days
    assert travel_dates_label == "October 10, 2026 to October 13, 2026 (4 days)", travel_dates_label

    pool_names = [f"poi {i}" for i in range(12)]
    courses = [{
        "course_id": "c1",
        "sequence": [
            {"poi_name": n, "lat": 37.5, "lng": 127.0, "estimated_stay_time": 60}
            for n in pool_names
        ],
    }]
    # LLM over-produces 6 days instead of the requested 4, skewed toward day 1.
    fake_llm_days = [
        {"day": 1, "theme": "Day 1", "pois": [{"name": pool_names[i]} for i in range(0, 4)]},
        {"day": 2, "theme": "Day 2", "pois": [{"name": pool_names[i]} for i in range(4, 6)]},
        {"day": 3, "theme": "Day 3", "pois": [{"name": pool_names[i]} for i in range(6, 8)]},
        {"day": 4, "theme": "Day 4", "pois": []},
        {"day": 5, "theme": "Day 5", "pois": [{"name": pool_names[i]} for i in range(8, 10)]},
        {"day": 6, "theme": "Day 6", "pois": [{"name": pool_names[i]} for i in range(10, 12)]},
    ]
    fake_response = json.dumps({"summary": "test trip", "days": fake_llm_days})

    captured_prompts = []
    original_gemini_text = planner._gemini_text
    original_google_key = planner.GOOGLE_PLACES_API_KEY

    def fake_gemini_text(prompt: str) -> str:
        captured_prompts.append(prompt)
        return fake_response

    planner._gemini_text = fake_gemini_text
    planner.GOOGLE_PLACES_API_KEY = ""  # no live network in this fast check
    try:
        state = {
            "retrieved_courses": courses,
            "day_segments": None,
            "region": "",
            "category": "",
            "travel_dates": travel_dates_label,   # exactly what collect_node would store
            "trip_start_date": "2026-10-10",
            "pace": "relaxed",
            "restrictions": None,
        }
        assert "num_days" not in state and "start_date" not in state
        assert planner._resolve_num_days(state) is None  # nothing to override with -- expected

        result = planner.plan_node(state)
    finally:
        planner._gemini_text = original_gemini_text
        planner.GOOGLE_PLACES_API_KEY = original_google_key

    assert result["current_step"] == "critic", result.get("messages")
    itinerary = result["itinerary"]
    assert len(itinerary["days"]) == 4, len(itinerary["days"])

    counts = [len(d["pois"]) for d in itinerary["days"]]
    assert sum(counts) == 12, counts
    assert max(counts) <= 6, counts  # overflow didn't pile onto one day

    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]
    assert f"Duration: {travel_dates_label}" in prompt, prompt.splitlines()[:6]
    assert "PACE: relaxed pace" in prompt, prompt

    print(f"OK - plan_node with origin's real date-picker travel_dates format, day sizes = {counts}")


if __name__ == "__main__":
    test_parse_num_days_override()
    test_resolve_num_days()
    test_parse_day_segments_override_bypasses_text_parsing()
    test_pace_bounds()
    test_pace_target_line()
    test_fold_least_filled_not_round_robin()
    test_trim_over_max_keeps_meal_and_area_coverage()
    test_trim_backs_off_when_protected_set_alone_exceeds_max()
    test_plan_node_end_to_end_with_structured_num_days()
    test_plan_node_with_origin_date_picker_format()
    print("\nAll num_days/pace self-checks passed.")
