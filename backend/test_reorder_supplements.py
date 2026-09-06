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
movable = {normalize_text("Mid Cafe")}
fixed = reorder_supplements([W, E, MID], movable)
assert _dist(fixed) < _dist([W, E, MID]), "cheapest-insertion should shorten the route"
assert fixed[1] is MID, "supplement should land between W and E"

# 2) the anchor backbone keeps its curated order
assert [p for p in fixed if p is not MID] == [W, E], "backbone must not reorder"

# 3) real shipped plans: total walking strictly drops.
#    Stand in for build_candidate_pool's google names using the old `source` tag.
GOOGLE_ISH = ("google places", "repair_meal_insert")


def _is_google(p):
    return any(g in (p.get("source") or "").lower() for g in GOOGLE_ISH)


here = os.path.dirname(__file__)
before = after = 0.0
for f in sorted(glob.glob(os.path.join(here, "..", "benchmark", "seoulfit_results", "scenario_*.json"))):
    for day in json.load(open(f)).get("days", []):
        ps = [p for p in day.get("pois", []) if isinstance(p.get("lat"), (int, float))]
        if len(ps) < 3:
            continue
        names = {normalize_text(p.get("name")) for p in ps if _is_google(p)}
        before += _dist(ps)
        after += _dist(reorder_supplements(ps, names))
assert after < before, f"expected less walking, got {after:.1f} >= {before:.1f}"
print(f"OK  backbone preserved; benchmark walking {before:.1f}km -> {after:.1f}km "
      f"({100 * (before - after) / before:.1f}% less)")
