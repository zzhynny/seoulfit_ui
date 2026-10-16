import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "evals"))
import bench_metrics as m

# 2026-11-02 is a Monday; Google legacy periods use 0 = Sunday, so Monday = 1.
MON = "2026-11-02"


def stop(name, type_="tourist_spot", lat=37.57, lng=126.98, start=None, stay=60, **kw):
    return {"name": name, "type": type_, "lat": lat, "lng": lng, "start": start,
            "stay_minutes": stay, **kw}


def test_tf_leg_matches_the_slide_piecewise_including_its_jumps():
    # 1km -> need = 15min
    assert m.tf_leg(0, 1) == 0.0
    assert m.tf_leg(7.5, 1) == pytest.approx(0.39)            # ratio .5 -> .78 * .5
    assert m.tf_leg(14.9, 1) < 0.78 and m.tf_leg(15, 1) == 0.82  # jump at ratio 1
    assert m.tf_leg(18.75, 1) == pytest.approx(0.90)           # ratio 1.25
    assert m.tf_leg(26, 1) < 0.96 and m.tf_leg(26.25, 1) == 0.98  # jump at 1.75
    assert m.tf_leg(5, 0) == pytest.approx(0.39)               # need floors at 10min


def test_mc_counts_meals_starting_inside_meal_slots_windows():
    days = [{"date": MON, "stops": [
        stop("L", "restaurant", start=12 * 60),           # lunch in 11:00-13:30
        stop("D", "restaurant", start=20 * 60 + 30),      # dinner after 20:00
    ]}]
    assert m.mc(days) == 0.5


def test_is_open_handles_weekday_overnight_and_24h():
    mon_10_to_18 = [{"open": {"day": 1, "time": "1000"}, "close": {"day": 1, "time": "1800"}}]
    d = date.fromisoformat(MON)
    assert m.is_open(mon_10_to_18, d, 11 * 60, 12 * 60) is True
    assert m.is_open(mon_10_to_18, d, 17 * 60, 19 * 60) is False
    tue_only = [{"open": {"day": 2, "time": "1000"}, "close": {"day": 2, "time": "1800"}}]
    assert m.is_open(tue_only, d, 11 * 60, 12 * 60) is False   # closed Mondays
    sat_night = [{"open": {"day": 6, "time": "1800"}, "close": {"day": 0, "time": "0200"}}]
    assert m.is_open(sat_night, date(2026, 11, 7), 23 * 60, 24 * 60) is True
    assert m.is_open([{"open": {"day": 0, "time": "0000"}}], d, 0, 60) is True
    assert m.is_open(None, d, 0, 60) is None


def test_oh_scores_unknown_as_half():
    facts = {"a": {"found": True, "periods": [
        {"open": {"day": 1, "time": "0900"}, "close": {"day": 1, "time": "2100"}}]},
             "b": {"found": True, "periods": [
        {"open": {"day": 2, "time": "0900"}, "close": {"day": 2, "time": "2100"}}]}}
    days = [{"date": MON, "stops": [stop("A", start=600), stop("B", start=700), stop("C", start=800)]}]
    assert m.oh(days, facts) == pytest.approx((1 + 0.5) / 3)   # ok, conflict, unknown
    facts["c"] = {"found": True, "closed_permanently": True}
    assert m.oh(days, facts) == pytest.approx(1 / 3)           # gone counts as a conflict


def test_ss_is_capped_at_one_and_penalises_zigzag():
    a, b, c = (37.50, 127.00), (37.51, 127.00), (37.52, 127.00)
    assert m.ss_day([a, b, c]) == 1.0
    assert m.ss_day([a, c, b]) < 1.0


def test_vd_fs_and_cp_follow_the_defined_tables():
    days = [{"date": MON, "stops": [
        stop("S", "tourist_spot", stay=60),     # ok
        stop("R", "restaurant", stay=60),       # ok, sight->meal GOOD
        stop("C", "cafe", stay=120),            # over 75 -> fail, meal->cafe GOOD
        stop("C2", "cafe", stay=None),          # unknown, cafe->cafe same type .35
    ]}]
    assert m.vd(days) == pytest.approx((2 + 0.7) / 4)
    assert m.fs(days) == pytest.approx((1 + 1 + 0.35) / 3)   # no category over 60%
    far = [(37.50, 127.00), (37.50 + 15 / 111, 127.00)]       # ~15km apart
    assert m.cp_day(far) == pytest.approx(0)


def test_fg_rubrics_unknown_unmatched_and_guidance():
    facts = {"en": {"found": True, "english_support": 1, "cash_only": 0,
                    "reservation_required": 0, "cultural_friction": 0},
             "cash": {"found": True, "english_support": 0, "cash_only": 1,
                      "cultural_friction": 1}}
    s_en, s_cash = stop("EN"), stop("Cash", notes="Cash only. Take shoes off at the door.")
    s_miss = stop("Missing")
    days = [{"date": MON, "stops": [s_en, s_cash, s_miss]}]
    assert m.la(days, facts) == pytest.approx((1 + 0.5) / 3)
    assert m.ab_stop(s_cash, facts["cash"]) == 0.95          # barrier, guided
    assert m.ab_stop(stop("x"), facts["cash"]) == 0.55       # barrier, no guidance
    assert m.ab_stop(s_miss, None) == 0.30                   # DB 미매칭
    assert m.cf_stop(s_cash, facts["cash"]) == 1.0           # friction + tip
    assert m.cf_stop(stop("x"), facts["cash"]) == 0.35
    assert m.mb_leg(0.5) == 1.0 and m.mb_leg(9) == 0.20


def test_cc_takes_evidence_not_the_itinerarys_own_claim():
    facts = {"yes": {"found": True, "serves_vegetarian": True},
             "no": {"found": True, "serves_vegetarian": False, "vegetarian": 1},  # Google wins
             "soup": {"found": True, "vegan": 0}}
    days = [{"date": MON, "stops": [
        stop("Yes", "restaurant"),
        stop("No", "restaurant"),
        stop("Unknown", "restaurant", notes="Great vegetarian options"),  # a claim is not evidence
        stop("Palace"),                                                   # not a meal stop
    ]}]
    assert m.cc(days, facts, "vegetarian") == pytest.approx((1 + 0.7) / 3)
    assert m.cc(days, facts, None) == 1.0
    vegan_day = [{"date": MON, "stops": [stop("Soup", "restaurant", notes="Try the vegan-friendly hot pot.")]}]
    assert m.cc(vegan_day, facts, "vegan") == 0.0


def test_note_keywords_are_word_bounded():
    assert m.cf_stop(stop("x", notes="Discover the area."), {"cultural_friction": 1}) == 0.35
    assert m.ab_stop(stop("x", notes="Kyobo bookstore"), {"cash_only": 1}) == 0.55
    assert m.ab_stop(stop("x", notes="Book ahead."), {"cash_only": 1}) == 0.95


def test_score_returns_all_axes_in_unit_range():
    days = [{"date": MON, "stops": [
        stop("A", start=600), stop("L", "restaurant", lat=37.571, start=11 * 60 + 15),
        stop("B", lat=37.575, start=13 * 60), stop("D", "restaurant", lat=37.58, start=18 * 60 + 30)]}]
    out = m.score({"days": days}, {})
    assert set(out) >= {"MC", "TF", "OH", "RD", "VD", "SS", "CP", "FS",
                        "LA", "MB", "CC", "AB", "CF", "F", "ECS", "FG", "Score"}
    assert all(0 <= v <= 1 for v in out.values())
    assert out["MC"] == 1.0
