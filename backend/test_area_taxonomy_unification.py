"""Before/after check for unifying critic_repair.py's area taxonomy with
geo.py (the documented single source of truth). Each case is a requested
area whose POI is tagged exactly as planner.py (which already uses geo.py)
would tag it, and asserts CriticAgent counts it correctly.

Before the fix, only the two cases that request an area critic_repair.py had
no entry for AT ALL (bukchon, yongsan) failed outright. The three
"adjacency" cases (apgujeong->gangnam, bukchon->jongno, yongsan->itaewon)
happened to PASS even before the fix -- not because area recognition was
correct, but because critic_repair's own coordinate fallback mis-relabeled
the unknown area (apgujeong->garosu-gil, bukchon->insadong, yongsan->itaewon)
to a name that, by coincidence, was already in that requested area's local
adjacency set. That's a masked bug, not a non-bug: verified live by calling
infer_area_from_poi() directly against the pre-fix code (see the review
conversation). After the fix all five pass for the right reason -- the POI's
actual, correctly-tagged area.

Run:  python test_area_taxonomy_unification.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import geo  # noqa: E402
from critic_repair import CriticAgent  # noqa: E402


def _poi(name: str, area: str) -> dict:
    lat, lng = geo.SEOUL_AREA_CENTERS[area]
    return {"name": name, "type": "tourist_spot", "lat": lat, "lng": lng, "area": area}


def _itinerary_state(requested_areas: list[str], pois_by_day: list[list[dict]]) -> dict:
    days = [{"day": i + 1, "pois": pois} for i, pois in enumerate(pois_by_day)]
    return {
        "itinerary": {"days": days},
        "planning_context": {"requested_areas": requested_areas, "google_supplement": []},
        "retrieved_courses": [],
        "region": " and ".join(requested_areas),
        "category": "",
    }


CASES = [
    # (label, requested_area, poi_area, coordinates_taken_from)
    ("bukchon POI, bukchon requested (area new to critic_repair)", "bukchon", "bukchon"),
    ("apgujeong POI, gangnam requested (geo.py adjacency)", "gangnam", "apgujeong"),
    ("bukchon POI, jongno requested (geo.py adjacency)", "jongno", "bukchon"),
    ("yongsan POI, itaewon requested (geo.py adjacency)", "itaewon", "yongsan"),
    ("yongsan POI, yongsan requested (area new to critic_repair)", "yongsan", "yongsan"),
]


def run() -> bool:
    critic = CriticAgent()
    all_ok = True
    for label, requested_area, poi_area in CASES:
        pois = [_poi(f"{poi_area} Spot 1", poi_area), _poi(f"{poi_area} Spot 2", poi_area)]
        state = _itinerary_state([requested_area], [pois])
        report = critic.evaluate(state)
        coverage = report["area_coverage"].get(requested_area, 0)
        under_covered = any(i["code"] == "REQUESTED_AREA_UNDER_COVERED" for i in report["issues"])

        ok = coverage == 2 and not under_covered
        all_ok = all_ok and ok
        status = "PASS" if ok else "FAIL"
        print(
            f"[{status}] {label}: coverage={coverage} (expected 2), "
            f"REQUESTED_AREA_UNDER_COVERED={'yes' if under_covered else 'no'} "
            f"(expected no), area_score={report['requested_area_coverage_score']}"
        )
    return all_ok


if __name__ == "__main__":
    ok = run()
    if ok:
        print("all test_area_taxonomy_unification checks PASS")
    else:
        print("test_area_taxonomy_unification: one or more checks FAIL (expected before the fix)")
        sys.exit(1)
