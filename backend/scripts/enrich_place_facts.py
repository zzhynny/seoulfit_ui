"""Google Places facts for every course POI and Michelin restaurant, written to
dataset/place_facts.json (read by place_facts.py).

It is the benchmark's own lookup and Gemini label pass (evals/bench_verify),
so hours and labels mean the same thing in the app and in scoring. Course POIs
with a verified closed_weekday_place_id skip Find Place. Area-type POIs (streets,
neighbourhoods) have no hours or staff to label and are skipped.

Resumable: names already in the file are skipped, failed labels are retried.

Run: LANGSMITH_TRACING=false venv/bin/python scripts/enrich_place_facts.py
"""
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(BACKEND), str(BACKEND / "evals")]

import bench_run
import bench_verify


def main():
    bench_run.setup("seoulfit")
    import meal_slots
    import place_facts
    import planner
    import retrieval

    stops = []
    for c in json.loads(retrieval.COURSE_DATA.read_text(encoding="utf-8")):
        for p in c.get("sequence") or []:
            if p.get("is_area_type") or p.get("is_generic_activity") or p.get("is_transit_marker"):
                continue
            stops.append({"name": p["poi_name"], "lat": p.get("lat"), "lng": p.get("lng"),
                          "place_id": (p.get("opening_hours") or {}).get("closed_weekday_place_id")})
    restaurants = json.loads(meal_slots.RESTAURANT_PATH.read_text(encoding="utf-8"))
    stops += [{"name": r["name"], "lat": r.get("lat"), "lng": r.get("lon")} for r in restaurants]

    bench_verify.verify(planner, stops, place_facts.PATH)
    facts = bench_verify.relabel(planner, place_facts.PATH)

    # Michelin's own payment field beats a guess from five reviews.
    for r in restaurants:
        f, pay = facts.get(place_facts.key(r["name"])), (r.get("payment") or "").lower()
        if f and f.get("found") and pay:
            f["cash_only"] = 1 if "cash only" in pay else 0
    place_facts.PATH.write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
    found = sum(bool(f.get("found")) for f in facts.values())
    print(f"place_facts: {found}/{len(facts)} found, "
          f"{sum(bool(f.get('periods')) for f in facts.values())} with hours")


if __name__ == "__main__":
    main()
