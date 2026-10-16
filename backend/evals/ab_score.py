"""Score A (before critic_repair) and B (after) from an ab_run.py run, with checks
the critic does not compute, so B's win isn't graded by the thing B optimised.

No API calls. Reads <run>/runs.jsonl, writes <run>/scored.jsonl, prints a paired
A-vs-B table. Every metric is computed the same way on A and on B from the saved
itinerary alone (B's transit_legs are ignored; both use straight-line distance).

Usage (from backend/):
    venv/bin/python evals/ab_score.py evals/out/ab_<ts>
"""
import itertools
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

import planner
from geo import area_matches_requested, haversine_km, infer_area_from_fields

GOLD_RADIUS_KM = 0.15  # a stop within 150m of a gold-course POI counts as that POI
FAR_LEG_KM = 3.0       # past this a leg is a transit ride, not a walk
# Both fill notes end with this: planner's validator and critic_repair's RepairAgent.
FILLER_NOTE = "to make the day sufficiently complete."

# (metric, which direction is better). Higher-is-better metrics go first.
METRICS = [
    ("gold_hits", "higher"),
    ("stops", "higher"),
    ("off_area", "lower"),
    ("route_km", "lower"),
    ("max_leg_km", "lower"),
    ("far_legs", "lower"),
    ("filler", "lower"),
    ("missing_meals", "lower"),
    ("unverified_meals", "lower"),
    # Minutes past the pace's end time. Not independent of the critic: it is
    # the same planner._day_schedule clock DAY_RUNS_LATE reads.
    ("late_min", "lower"),
    # Minutes past end time + planner._DAY_END_GRACE: what fit_day_to_time and
    # the critic now count as actually late.
    ("late_over_grace", "lower"),
    # Minutes lunch starts after its window closes (13:30).
    ("lunch_late_min", "lower"),
]


def gold_points(scenario_id):
    """Coordinates of every POI in this persona's hand-labelled gold courses."""
    import retrieval
    gold = json.loads((HERE / "personas.json").read_text())["gold"].get(str(scenario_id)) or []
    by_id = {c["course_id"]: c for c in retrieval.load_courses()}
    return [(s["lat"], s["lng"]) for cid in gold if cid in by_id
            for s in by_id[cid]["sequence"] if s.get("lat") and s.get("lng")]


def score(itinerary, state, gold):
    """Independent metrics for one itinerary. Meals count toward route, not stops."""
    out = dict.fromkeys((m for m, _ in METRICS), 0)
    regions = {s["day"]: s["region"] for s in state.get("day_specs") or []}
    for day in itinerary.get("days") or []:
        pois = day.get("pois") or []
        region = regions.get(day.get("day"))
        stops = [p for p in pois if not p.get("meal_slot")]
        meals = [p for p in pois if p.get("meal_slot")]
        out["stops"] += len(stops)
        # Re-inferred from address/coords, not the pipeline's own `area` tag.
        off = [bool(region) and not area_matches_requested(
                   infer_area_from_fields(p.get("name"), p.get("address"), p.get("lat"), p.get("lng")),
                   region)
               for p in stops]
        out["off_area"] += sum(off)
        # A fill that lands in the requested area is the validator doing its
        # job, now that Google searches run on every day; only an off-area fill
        # is a defect.
        out["filler"] += sum(o and FILLER_NOTE in (p.get("notes") or "")
                             for p, o in zip(stops, off))
        out["missing_meals"] += len({"lunch", "dinner"} - {m["meal_slot"] for m in meals})
        out["unverified_meals"] += sum(not all((m.get("verified") or {}).values()) for m in meals)
        out["gold_hits"] += sum(
            any(haversine_km(p["lat"], p["lng"], la, ln) <= GOLD_RADIUS_KM for la, ln in gold)
            for p in stops if p.get("lat") and p.get("lng"))
        pts = [(p["lat"], p["lng"]) for p in pois if p.get("lat") and p.get("lng")]
        legs = [haversine_km(*a, *b) for a, b in itertools.pairwise(pts)]
        out["route_km"] += sum(legs)
        out["max_leg_km"] = max(out["max_leg_km"], max(legs, default=0))
        out["far_legs"] += sum(leg > FAR_LEG_KM for leg in legs)
        end, meal_starts = planner._day_schedule(pois)
        lunch_close = planner._hhmm(planner.meal_slots.MEAL_SLOTS["lunch"][1])
        out["lunch_late_min"] += max(0, meal_starts.get("lunch", 0) - lunch_close)
        day_end = planner._day_end(state.get("pace"), state.get("purpose"))
        out["late_min"] += max(0, end - day_end)
        out["late_over_grace"] += max(0, end - day_end - planner._DAY_END_GRACE)
        out["end_min"] = max(out.get("end_min", 0), end)  # reported, not compared
    out["route_km"] = round(out["route_km"], 2)
    out["max_leg_km"] = round(out["max_leg_km"], 2)
    return out


def sign_test(wins, losses):
    """Two-sided exact sign test p-value; ties dropped."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def compare(scored):
    """Per metric: mean A, mean B, and B better/worse/tied counted per scenario.

    Reps of one scenario are not independent samples, so they're averaged first."""
    by_sc = defaultdict(list)
    for r in scored:
        by_sc[r["scenario_id"]].append(r)
    rows = []
    for metric, better in METRICS:
        a = [sum(r["A"][metric] for r in rs) / len(rs) for rs in by_sc.values()]
        b = [sum(r["B"][metric] for r in rs) / len(rs) for rs in by_sc.values()]
        sign = 1 if better == "higher" else -1
        win = sum((y - x) * sign > 0 for x, y in zip(a, b))
        loss = sum((y - x) * sign < 0 for x, y in zip(a, b))
        rows.append((metric, better, sum(a) / len(a), sum(b) / len(b), win, loss,
                     len(a) - win - loss, sign_test(win, loss)))
    return rows


def print_table(title, rows):
    print(f"\n{title}")
    print(f"{'metric':17} {'better':6} {'A':>7} {'B':>7}  B win/loss/tie   p")
    for metric, better, a, b, w, l, t, p in rows:
        print(f"{metric:17} {better:6} {a:7.2f} {b:7.2f}  {w:>3}/{l:>3}/{t:>3}  {p:6.3f}")


def main():
    run = Path(sys.argv[1])
    rows = [json.loads(line) for line in (run / "runs.jsonl").read_text().splitlines()]
    rows = [r for r in rows if not r.get("error")]
    gold = {sid: gold_points(sid) for sid in {r["scenario_id"] for r in rows}}
    scored = [{"scenario_id": r["scenario_id"], "rep": r["rep"],
               "repair_applied": r.get("repair_applied"),
               "A": score(r["A"], r["state"], gold[r["scenario_id"]]),
               "B": score(r["B"], r["state"], gold[r["scenario_id"]])} for r in rows]
    (run / "scored.jsonl").write_text(
        "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in scored))

    print(f"{len(scored)} runs, {len({s['scenario_id'] for s in scored})} scenarios -> {run / 'scored.jsonl'}")
    print_table("all scenarios", compare(scored))
    touched = [s for s in scored if s["repair_applied"]]
    if touched:
        print_table(f"repair_applied only ({len(touched)} runs)", compare(touched))


if __name__ == "__main__":
    main()
