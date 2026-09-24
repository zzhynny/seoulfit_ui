"""Self-check for critic_repair.reorder_supplements (route tidy).

Supplements are identified by name against the candidate pool's google entries
(the pipeline strips source_kind from final POIs). This test asserts the
algorithm (1) shortens a hand-made backtracking day and drops the supplement
between its neighbors, (2) never reorders the anchor backbone, and (3) cuts
total walking on the real benchmark plans. Distances are measured independently
here — the function under test does not grade itself.

NOTE: the benchmark JSONs predate the current source_kind scheme but still carry
a per-POI `source`, so the movable set is derived from that here to stand in for
build_candidate_pool's google names. Magnitude on live output should be
re-confirmed with a real pipeline run.

Run:  backend/venv/bin/python backend/test_reorder_supplements.py
"""
import glob
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from critic_repair import reorder_supplements, normalize_text  # noqa: E402


def _hav(a, b):
    R = 6371.0
    la1, ln1, la2, ln2 = map(math.radians, (a["lat"], a["lng"], b["lat"], b["lng"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((ln2 - ln1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _dist(ps):
    return sum(_hav(ps[i], ps[i + 1]) for i in range(len(ps) - 1))


# 1) a supplement stranded at the end belongs in the middle
W = {"name": "West Anchor", "lat": 37.55, "lng": 126.90}
E = {"name": "East Anchor", "lat": 37.55, "lng": 126.94}
MID = {"name": "Mid Cafe", "lat": 37.55, "lng": 126.92}

# Stand in for build_candidate_pool's google names using the old `source` tag.
GOOGLE_ISH = ("google places", "repair_meal_insert")

here = os.path.dirname(__file__)
BENCHMARK_GLOB = os.path.join(here, "..", "benchmark", "seoulfit_results", "scenario_*.json")


def _is_google(p):
    return any(g in (p.get("source") or "").lower() for g in GOOGLE_ISH)


def test_supplement_lands_between_its_neighbors():
    movable = {normalize_text("Mid Cafe")}
    fixed = reorder_supplements([W, E, MID], movable)
    assert _dist(fixed) < _dist([W, E, MID]), "cheapest-insertion should shorten the route"
    assert fixed[1] is MID, "supplement should land between W and E"


def test_anchor_backbone_keeps_its_curated_order():
    movable = {normalize_text("Mid Cafe")}
    fixed = reorder_supplements([W, E, MID], movable)
    assert [p for p in fixed if p is not MID] == [W, E], "backbone must not reorder"


def test_benchmark_plans_lose_walking():
    """Real shipped plans: total walking strictly drops.

    The benchmark JSONs are not in this repo — they came with the pipeline this
    code was lifted from. Skip rather than fail when they are absent: an empty
    corpus made this compare 0.0 < 0.0, which read as a routing regression.
    """
    files = sorted(glob.glob(BENCHMARK_GLOB))
    if not files:
        import pytest
        pytest.skip(f"no benchmark plans at {BENCHMARK_GLOB}")

    before = after = 0.0
    for f in files:
        with open(f, encoding="utf-8") as _fh:
            days = json.load(_fh).get("days", [])
        for day in days:
            ps = [p for p in day.get("pois", []) if isinstance(p.get("lat"), (int, float))]
            if len(ps) < 3:
                continue
            names = {normalize_text(p.get("name")) for p in ps if _is_google(p)}
            before += _dist(ps)
            after += _dist(reorder_supplements(ps, names))
    assert after < before, f"expected less walking, got {after:.1f} >= {before:.1f}"
    print(f"OK  benchmark walking {before:.1f}km -> {after:.1f}km "
          f"({100 * (before - after) / before:.1f}% less)")


if __name__ == "__main__":
    test_supplement_lands_between_its_neighbors()
    test_anchor_backbone_keeps_its_curated_order()
    print("OK  backbone preserved")
    if glob.glob(BENCHMARK_GLOB):
        test_benchmark_plans_lose_walking()
    else:
        print("SKIP benchmark plans (not in this repo)")


def test_supplements_never_cross_a_meal():
    """Day 2 of a real 'parties, clubs, bars' trip, validator order: the three
    Google bars/clubs sat around lunch and dinner. Cheapest-insertion put all of
    them before lunch -- the traveller got lunch after the club."""
    lunch = {"name": "Table for Four", "lat": 37.53468, "lng": 127.00523, "meal_slot": "lunch"}
    dinner = {"name": "Mosu", "lat": 37.54115, "lng": 126.99615, "meal_slot": "dinner"}
    day = [
        {"name": "Leeum", "lat": 37.53856, "lng": 126.99881},
        {"name": "Gyeongnidan Street", "lat": 37.54001, "lng": 126.99239},
        lunch,
        {"name": "Day and Night", "lat": 37.53504, "lng": 126.99383},
        {"name": "APT SEOUL", "lat": 37.53184, "lng": 126.99467},
        dinner,
        {"name": "Soap Seoul", "lat": 37.53420, "lng": 126.99090},
    ]
    movable = {normalize_text(n) for n in ("Day and Night", "APT SEOUL", "Soap Seoul")}
    names = [p["name"] for p in reorder_supplements(day, movable)]
    assert names.index("Table for Four") < names.index("Day and Night") < names.index("Mosu")
    assert names.index("APT SEOUL") < names.index("Mosu") < names.index("Soap Seoul")
