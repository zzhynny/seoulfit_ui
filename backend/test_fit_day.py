"""fit_day_to_time: a day that runs past its end time (21:00 unless packed or
a nightlife trip) loses its least relevant stops, and evening stops move into
idle time before dinner.

Every POI sits on the same point, so travel is 0 and each timeline is just
the stays plus waiting for a meal window (LEG_SLACK_MIN is zeroed here and
tested on its own). The day starts at 10:00.
"""
import pytest

import planner
from planner import (
    _day_schedule,
    _leg_minutes,
    fit_day_to_time,
    fix_lunch_time,
    rechoose_meals,
)


@pytest.fixture(autouse=True)
def _no_slack(monkeypatch):
    monkeypatch.setattr(planner, "LEG_SLACK_MIN", 0)
    monkeypatch.setattr(planner, "_DAY_END", {"packed": 22 * 60})
    monkeypatch.setattr(planner, "_DAY_END_DEFAULT", 21 * 60)


def test_day_ends_are_22_default_23_packed_24_nightlife(monkeypatch):
    monkeypatch.undo()                                 # the fixture's pinned values
    assert planner._day_end(None, None) == 22 * 60
    assert planner._day_end("relaxed", None) == 22 * 60
    assert planner._day_end("packed", None) == 23 * 60
    assert planner._day_end("packed", "nightlife") == 24 * 60


def test_every_leg_gets_the_slack_on_top_of_travel(monkeypatch):
    monkeypatch.setattr(planner, "LEG_SLACK_MIN", 10)
    a, b = stop("A", 60), stop("B", 60)
    assert _leg_minutes(a, b) == 10                    # same point: slack only
    far = {**b, "lat": 37.57 + 3 / 111}                # ~3km: 6min ride + 10 wait
    assert _leg_minutes(a, far) == 6 + 10 + 10
    assert _day_schedule([a, b])[0] == 10 * 60 + 60 + 10 + 60


def stop(name, minutes, priority=None, area="jongno"):
    p = {"name": name, "type": "tourist_spot", "lat": 37.57, "lng": 126.98,
         "stay_minutes": minutes, "area": area}
    if priority:
        p["priority"] = priority
    return p


def meal(slot):
    return {"name": slot.title(), "type": "restaurant", "lat": 37.57, "lng": 126.98,
            "stay_minutes": 60, "meal_slot": slot, "area": "jongno"}


def names(pois):
    return [p["name"] for p in pois]


def test_evening_stops_move_into_the_afternoon_or_go():
    # 10:00 A, 12:00 lunch, B C D until 16:30, wait, dinner 18:00, E F -> 23:00.
    # After dinner F alone still runs to 22:00, past 21:00 + the grace.
    day = [stop("A", 120, 1), meal("lunch"), stop("B", 90, 1), stop("C", 60, 2),
           stop("D", 60, 1), meal("dinner"), stop("E", 90, 2), stop("F", 180, 3)]
    out, dropped = fit_day_to_time(day, "relaxed")
    # E fits in the 16:30-18:00 gap; F (the filler) doesn't fit anywhere.
    assert names(out) == ["A", "Lunch", "B", "C", "D", "E", "Dinner"]
    assert dropped == [("F", 3)]


def test_the_least_relevant_stop_goes_even_when_it_is_early():
    # X (filler) is in the morning; the priority-1 E after dinner runs to 22:00,
    # past 21:00 plus the 30-minute grace.
    day = [stop("A", 90, 1), meal("lunch"), stop("X", 120, 3), stop("B", 120, 1),
           stop("C", 90, 1), meal("dinner"), stop("E", 180, 1)]
    out, dropped = fit_day_to_time(day, "relaxed")
    assert dropped == [("X", 3)]
    assert "E" in names(out) and names(out).index("E") < names(out).index("Dinner")


def test_meals_and_a_days_only_stop_in_an_area_are_kept():
    day = [stop("Only Bukchon", 240, 3, area="bukchon"), meal("lunch"),
           stop("B", 240, 2), stop("C", 240, 1), meal("dinner"), stop("D", 120, 1)]
    out, dropped = fit_day_to_time(day, "relaxed", requested_areas=["bukchon", "jongno"])
    assert "Only Bukchon" in names(out)
    assert {"Lunch", "Dinner"} <= set(names(out))
    assert ("B", 2) in dropped


def test_it_stops_at_three_stops_even_if_still_late():
    day = [stop(f"S{i}", 300, 3) for i in range(5)]
    out, dropped = fit_day_to_time(day, "relaxed")
    assert len(out) == 3 and len(dropped) == 2


def test_without_meals_it_trims_on_end_time():
    # Default pace ends 21:00 = 11h. 4 x 180 = 12h -> one must go, the priority 3.
    day = [stop("A", 180, 1), stop("B", 180, 3), stop("C", 180, 2), stop("D", 180, 1)]
    out, dropped = fit_day_to_time(day, None)
    assert dropped == [("B", 3)]


def test_a_stop_with_no_priority_counts_as_filler():
    # Code-added stops carry no priority; they go before anything Gemini chose.
    day = [stop("A", 200, 2), stop("Added", 200), stop("C", 200, 2), stop("D", 100, 1)]
    _, dropped = fit_day_to_time(day, "relaxed")
    assert dropped == [("Added", 3)]


def test_a_dropped_stop_comes_back_when_the_day_still_fits():
    # Default pace ends 21:00 = 11h. 120+200+120+60+280 = 13h. The later filler
    # X (60) goes first: 12h, still late. Then Y (200): 9h40. X now fits back in
    # (10h40), so only Y stays dropped.
    day = [stop("A", 120, 1), stop("Y", 200, 3), stop("B", 120, 1),
           stop("X", 60, 3), stop("C", 280, 1)]
    out, dropped = fit_day_to_time(day, None)
    assert sorted(names(out)) == ["A", "B", "C", "X"] and dropped == [("Y", 3)]


def test_a_stop_that_would_push_the_day_late_stays_dropped():
    # 4 x 130 + 200 = 12h -> F goes (8h40); back in it would be 12h again.
    day = [stop("A", 130, 1), stop("B", 130, 1), stop("C", 130, 1),
           stop("D", 130, 1), stop("F", 200, 3)]
    out, dropped = fit_day_to_time(day, None)
    assert names(out) == ["A", "B", "C", "D"] and dropped == [("F", 3)]


def test_a_day_inside_the_grace_is_left_as_planned():
    # 10:00 + 4 x 170 = 21:20: past 21:00 but within 30 minutes. Dropping a
    # 170-minute stop to save 20 would cost more than it saves.
    day = [stop(f"S{i}", 170, 3) for i in range(4)]
    out, dropped = fit_day_to_time(day, None)
    assert dropped == [] and out is day


def test_a_day_past_the_grace_ends_within_it():
    # 10:00 + 4 x 120 + 165 + 60 = 21:45, past 21:30: one stop must go.
    day = [stop("A", 120, 1), stop("B", 120, 1), stop("C", 120, 1),
           stop("D", 120, 1), stop("F", 165, 3), stop("G", 60, 2)]
    out, dropped = fit_day_to_time(day, None)
    assert dropped == [("F", 3)]
    assert _day_schedule(out)[0] <= 21 * 60 + 30


def test_a_nightlife_day_may_run_to_half_past_midnight():
    day = [stop(f"S{i}", 205, 1) for i in range(4)]    # 10:00 + 820 min = 23:40
    day += [stop("Bar", 50, 1)]                        # 24:30, exactly the grace
    out, dropped = fit_day_to_time(day, None, purpose="clubs and bars")
    assert dropped == [] and out is day


def test_a_day_that_fits_is_untouched():
    day = [stop("A", 60, 1), meal("lunch"), stop("B", 60, 3), meal("dinner")]
    out, dropped = fit_day_to_time(day, "relaxed")
    assert dropped == [] and out == day and all(a is b for a, b in zip(out, day))


def test_a_nightlife_trip_keeps_its_clubs_after_dinner():
    # Dinner 18:00, then two clubs to 22:00 -- late for a plain day, but the
    # night out is what this trip is for: nothing moves ahead of dinner.
    day = [stop("A", 120, 1), meal("lunch"), stop("B", 120, 1), meal("dinner"),
           stop("Club", 120, 1), stop("Bar", 60, 1)]
    out, dropped = fit_day_to_time(day, "relaxed", purpose="going to parties, clubs, and bars")
    assert dropped == [] and names(out) == names(day)
    # Same day on a plain trip ends 22:00, past 21:00: the clubs get pulled
    # into the idle afternoon ahead of dinner.
    out, _ = fit_day_to_time(day, "relaxed", purpose="first time with my parents")
    assert names(out).index("Club") < names(out).index("Dinner")


def _at(name, lat, lng, minutes=60, **extra):
    return {"name": name, "type": "tourist_spot", "lat": lat, "lng": lng,
            "stay_minutes": minutes, "area": "jongno", **extra}


def _dinner(name, lat, lng, **extra):
    return {"name": name, "type": "restaurant", "lat": lat, "lng": lng,
            "stay_minutes": 60, "meal_slot": "dinner", "source_tier": "michelin",
            "verified": {"opening_hours": True, "cuisine": True}, "area": "jongno", **extra}


def test_dinner_is_repicked_for_the_stops_it_now_sits_between():
    # Dinner was chosen for the west end; an evening stop was pulled ahead of it
    # and both neighbours are now far east. Its alternative is beside them.
    west, east = _dinner("West Grill", 37.56, 126.98), _dinner("East Grill", 37.56, 127.04)
    locked = {"dinner": {**west, "alternatives": [east]}}
    day = [_at("A", 37.56, 127.035), west, _at("B", 37.56, 127.045)]
    out = rechoose_meals(day, locked, reserved={"westgrill"}, elsewhere=set(),
                         deadline=21 * 60)
    assert names(out) == ["A", "East Grill", "B"]
    assert out[1]["meal_slot"] == "dinner" and out[1]["stay_minutes"] == 60


def test_a_meal_served_on_another_day_is_not_repicked():
    west, east = _dinner("West Grill", 37.56, 126.98), _dinner("East Grill", 37.56, 127.04)
    locked = {"dinner": {**west, "alternatives": [east]}}
    day = [_at("A", 37.56, 127.035), west, _at("B", 37.56, 127.045)]
    out = rechoose_meals(day, locked, reserved={"westgrill"},
                         elsewhere={"eastgrill"}, deadline=21 * 60)
    assert names(out) == ["A", "West Grill", "B"]


def test_a_repick_that_would_end_the_day_late_is_skipped():
    # 10:00 + 120 + 60 + 120 = 13:00 on the spot; but the day is built to end
    # right at the deadline, so a longer walk to the alternative would run over.
    west, east = _dinner("West Grill", 37.56, 126.98), _dinner("East Grill", 37.56, 127.04)
    locked = {"dinner": {**west, "alternatives": [east]}}
    day = [_at("A", 37.56, 126.98, 330), west, _at("B", 37.56, 126.98, 330)]
    out = rechoose_meals(day, locked, reserved=set(), elsewhere=set(), deadline=21 * 60)
    assert names(out) == ["A", "West Grill", "B"]


def test_a_google_pick_without_alternatives_stays():
    g = _dinner("Google Place", 37.56, 126.98, source_tier="google")
    day = [_at("A", 37.56, 127.035), g, _at("B", 37.56, 127.045)]
    out = rechoose_meals(day, {"dinner": g}, reserved={"googleplace"}, elsewhere=set(),
                         deadline=21 * 60)
    assert out == day


def test_a_meal_is_looked_up_again_around_the_stops_it_now_sits_between(monkeypatch):
    # Anchors are in the west; a supplement pulled ahead of dinner is in the
    # east, 3 km from every anchor. The planner's alternatives (found near the
    # anchors) don't reach it, so critic_repair looks the meal up again.
    import critic_repair

    seen = {}
    east = _dinner("East Grill", 37.56, 127.04, alternatives=[])
    monkeypatch.setattr(critic_repair.meal_slots, "fill_meal_slot",
                        lambda **kw: seen.update(kw) or {**east, "status": "filled"})
    west = _dinner("West Grill", 37.56, 126.98, alternatives=[])
    pois = [_at("A", 37.56, 127.035), west, _at("B", 37.56, 127.045)]
    state = {"day_specs": [{"day": 1, "region": "jongno"}], "trip_start_date": "2026-11-03"}
    days = [{"day": 1, "pois": pois}]

    got = critic_repair._locked_near_neighbours(state, 1, "dinner", pois, west, days)

    assert seen["stops"] == [(37.56, 127.035), (37.56, 127.045)]     # the two neighbours
    assert seen["allow_google"] is False and seen["exclude_names"] == ()
    assert got["name"] == "East Grill"
    assert [a["name"] for a in got["alternatives"]] == ["West Grill"]   # original stays an option
    out = rechoose_meals(pois, {"dinner": got}, reserved={"westgrill"}, elsewhere=set(),
                         deadline=21 * 60)
    assert names(out) == ["A", "East Grill", "B"]


def test_a_google_pick_is_not_looked_up_again(monkeypatch):
    import critic_repair

    monkeypatch.setattr(critic_repair.meal_slots, "fill_meal_slot",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("no lookup")))
    g = _dinner("Google Place", 37.56, 126.98, source_tier="google")
    pois = [_at("A", 37.56, 127.035), g, _at("B", 37.56, 127.045)]
    state = {"day_specs": [{"day": 1, "region": "jongno"}], "trip_start_date": "2026-11-03"}
    assert critic_repair._locked_near_neighbours(state, 1, "dinner", pois, g,
                                                 [{"day": 1, "pois": pois}]) is g


def test_a_late_lunch_moves_one_stop_earlier():
    # A + B run to 13:50, past lunch's 13:30 close; after A it starts at 12:00.
    day = [stop("A", 120), stop("B", 110), meal("lunch"), stop("C", 60)]
    out = fix_lunch_time(day)
    assert names(out) == ["A", "Lunch", "B", "C"]
    assert _day_schedule(out)[1]["lunch"] == 12 * 60


def test_lunch_never_becomes_the_first_stop():
    # One 4-hour morning stop: still late at index 1, but at 10:00 it would idle.
    day = [stop("A", 240), meal("lunch"), stop("B", 60)]
    assert fix_lunch_time(day) is day


def test_a_lunch_on_time_is_left_alone():
    day = [stop("A", 60), stop("B", 60), meal("lunch"), stop("C", 60)]
    assert fix_lunch_time(day) is day


def test_a_lunch_move_that_would_push_dinner_past_its_window_is_refused():
    # Moving lunch ahead of B makes it wait 10:30-11:00, which pushes dinner from
    # 19:50 to 20:20, past its 20:00 close.
    day = [stop("A", 30), stop("B", 230), meal("lunch"), stop("C", 270), meal("dinner")]
    assert fix_lunch_time(day) is day


def test_without_the_pull_wins_when_both_keep_the_same_stops_and_it_is_shorter():
    # Everything is in the west except X, 5 km east, after dinner. Either way the
    # 400-minute filler F must go. Pulling X ahead of dinner then makes the day
    # go east and come back for dinner; leaving it after dinner goes east once.
    x = {**stop("X", 60, 1), "lng": 127.04}
    day = [stop("A", 120, 1), meal("lunch"), stop("B", 120, 1), meal("dinner"),
           x, stop("F", 400, 3)]
    out, dropped = fit_day_to_time(day, None)
    assert names(out) == ["A", "Lunch", "B", "Dinner", "X"]
    assert dropped == [("F", 3)]


def test_the_pull_wins_when_it_keeps_more_stops():
    # 16:30-18:00 is idle before dinner. Pulling E and F into it lets G and H
    # stay after dinner (21:30, inside the grace); without the pull two go.
    day = [stop("A", 120, 1), meal("lunch"), stop("B", 90, 1), stop("C", 60, 1),
           stop("D", 60, 1), meal("dinner"), stop("E", 60, 2), stop("F", 60, 2),
           stop("G", 60, 3), stop("H", 60, 2)]
    out, dropped = fit_day_to_time(day, None)
    assert dropped == []                     # the winner's drops, not the other trim's
    assert names(out) == ["A", "Lunch", "B", "C", "D", "E", "F", "Dinner", "G", "H"]


def test_a_google_meal_is_repicked_from_its_alternatives():
    # The Google pick now carries the rest of its search, so it moves like a
    # Michelin one -- and keeps the Google warning, nothing more.
    near = _dinner("Near Place", 37.56, 127.04, source_tier="google")
    far = _dinner("Far Place", 37.56, 126.98, source_tier="google", alternatives=[near])
    day = [_at("A", 37.56, 127.035), far, _at("B", 37.56, 127.045)]
    out = rechoose_meals(day, {"dinner": far}, reserved={"farplace"}, elsewhere=set(),
                         deadline=21 * 60)
    assert names(out) == ["A", "Near Place", "B"]
    assert [w for w in out[1]["warnings"] if "Michelin" in w]     # flagged as unverified


def test_a_diet_alternative_never_gets_the_generic_google_warning():
    warn = "Found by a Google search for 'vegetarian restaurant' — check the menu"
    near = _dinner("Veg Near", 37.56, 127.04, source_tier="google", diet_search=True,
                   warnings=[warn])
    far = _dinner("Veg Far", 37.56, 126.98, source_tier="google", diet_search=True,
                  warnings=[warn], alternatives=[near])
    day = [_at("A", 37.56, 127.035), far, _at("B", 37.56, 127.045)]
    out = rechoose_meals(day, {"dinner": far}, reserved={"vegfar"}, elsewhere=set(),
                         deadline=21 * 60)
    assert out[1]["name"] == "Veg Near" and out[1]["warnings"] == [warn]


def test_two_days_never_share_a_google_meal_after_the_repick():
    # Day 2 already serves "Near Place"; day 1's dinner may not move onto it.
    near = _dinner("Near Place", 37.56, 127.04, source_tier="google")
    far = _dinner("Far Place", 37.56, 126.98, source_tier="google", alternatives=[near])
    day = [_at("A", 37.56, 127.035), far, _at("B", 37.56, 127.045)]
    out = rechoose_meals(day, {"dinner": far}, reserved={"farplace"},
                         elsewhere={"nearplace"}, deadline=21 * 60)
    assert names(out) == ["A", "Far Place", "B"]
