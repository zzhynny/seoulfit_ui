"""The critic must read areas the way the rest of the backend does (geo.py).

Production trip 2026-09-23 (Bukchon + Gangnam): RepairAgent added two Bukchon
POIs, then CriticAgent counted Bukchon = 0, because critic_repair.py kept its
own copy of the area tables without "bukchon" in it.
"""
from critic_repair import CriticAgent, infer_area_from_poi


def _poi(name, lat, lng, area=None):
    return {"name": name, "type": "tourist_spot", "address": "", "lat": lat,
            "lng": lng, "stay_minutes": 60, "notes": "", "area": area}


def test_bukchon_pois_count_toward_a_bukchon_request():
    state = {
        "day_specs": [{"day": 1, "region": "bukchon"}],
        "itinerary": {"days": [{"day": 1, "pois": [
            _poi("Bukchon Hanok Village", 37.5826, 126.9836, area="bukchon"),
            _poi("Gahoe-dong 31", 37.5828, 126.9850, area="bukchon"),
        ]}]},
    }
    report = CriticAgent().evaluate(state)
    assert report["area_coverage"] == {"bukchon": 2}
    assert not [i for i in report["issues"] if i["code"] == "REQUESTED_AREA_UNDER_COVERED"]


def test_area_is_inferred_from_coords_with_geo_tables():
    # No stored area, no alias in the text: nearest geo centre wins.
    assert infer_area_from_poi(_poi("Some Gallery", 37.5826, 126.9836)) == "bukchon"
