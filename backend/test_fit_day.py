"""fit_day_to_time: a day that runs past its end time (21:00 unless packed or
a nightlife trip) loses its least relevant stops, and evening stops move into
idle time before dinner.

Every POI sits on the same point, so travel is 0 and each timeline is just
the stays plus waiting for a meal window. The day starts at 10:00.
"""
from planner import fit_day_to_time


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
    # 10:00 A, 12:00 lunch, B C D until 16:30, wait, dinner 18:00, E F -> 22:30.
    day = [stop("A", 120, 1), meal("lunch"), stop("B", 90, 1), stop("C", 60, 2),
           stop("D", 60, 1), meal("dinner"), stop("E", 90, 2), stop("F", 150, 3)]
    out, dropped = fit_day_to_time(day, "relaxed")
    # E fits in the 16:30-18:00 gap; F (the filler) doesn't fit anywhere.
    assert names(out) == ["A", "Lunch", "B", "C", "D", "E", "Dinner"]
    assert dropped == [("F", 3)]


def test_the_least_relevant_stop_goes_even_when_it_is_early():
    # X (filler) is in the morning; the priority-1 E after dinner runs to 21:30.
    day = [stop("A", 90, 1), meal("lunch"), stop("X", 120, 3), stop("B", 120, 1),
           stop("C", 90, 1), meal("dinner"), stop("E", 150, 1)]
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
