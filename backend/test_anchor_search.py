"""Google Places sweeps centre on the day's own courses, not the area's fixed point.

SEOUL_AREA_CENTERS holds one hand-placed point per neighbourhood; a day's courses
cluster wherever the course actually runs. Measured on the shipped dataset that
point sits up to 3.7km (Mapo) from the POIs the day will visit, so the old search
circle could miss the stops it was meant to surround.

Run:  backend/venv/bin/python backend/test_anchor_search.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import planner  # noqa: E402
from geo import SEOUL_AREA_CENTERS, haversine_km  # noqa: E402
from planner import _ANCHOR_RADIUS_MAX_M, _anchor_search_origin  # noqa: E402
from retrieval import DAY_PLAN_REGION_ORDER, filter_pool  # noqa: E402


def _seg(area: str, coords: list[tuple[float, float]]) -> dict:
    return {
        "day_numbers": [1],
        "area": area,
        "anchor_courses": [{
            "course_id": "T_1",
            "sequence": [
                {"poi_name": f"Stop {i}", "address_en": "Mapo-gu, Seoul",
                 "lat": lat, "lng": lng}
                for i, (lat, lng) in enumerate(coords)
            ],
        }],
    }


def test_too_few_points_falls_back() -> None:
    """Two POIs are one outlier away from a nonsense centroid."""
    assert _anchor_search_origin("hongdae", [_seg("hongdae", [(37.5560, 126.9230),
                                                             (37.5570, 126.9240)])]) is None
    assert _anchor_search_origin("hongdae", None) is None
    assert _anchor_search_origin("hongdae", []) is None


def test_tight_cluster_gets_a_centroid_that_covers_it() -> None:
    coords = [(37.5560 + i * 0.002, 126.9230 + i * 0.002) for i in range(5)]
    origin = _anchor_search_origin("hongdae", [_seg("hongdae", coords)])
    assert origin is not None
    (lat, lng), radius_m = origin

    # Centre sits inside the cluster, not at the neighbourhood's fixed point.
    assert min(c[0] for c in coords) <= lat <= max(c[0] for c in coords)
    assert min(c[1] for c in coords) <= lng <= max(c[1] for c in coords)
    assert radius_m <= _ANCHOR_RADIUS_MAX_M

    # The sweep reaches every POI it was built from.
    assert max(haversine_km(lat, lng, *c) * 1000 for c in coords) <= radius_m


def test_scatter_beyond_one_sweep_falls_back() -> None:
    """Spread wider than a single sweep can cover -> use the fixed centre."""
    coords = [(37.50, 127.02), (37.53, 127.03), (37.56, 126.98), (37.60, 126.90)]
    assert _anchor_search_origin("gangnam", [_seg("gangnam", coords)]) is None


def test_out_of_area_poi_does_not_drag_the_centre() -> None:
    """Mirrors _format_one_course's restrict_area cut: a POI the prompt drops for
    sitting in the wrong neighbourhood must not move the search centre either."""
    near = [(37.5560, 126.9230), (37.5570, 126.9240), (37.5580, 126.9250)]
    seg = _seg("hongdae", near)
    seg["anchor_courses"][0]["sequence"].append(
        {"poi_name": "Far Stop", "address_en": "Gangnam-gu, Seoul",
         "lat": 37.4979, "lng": 127.0276},          # squarely in Gangnam
    )
    origin = _anchor_search_origin("hongdae", [seg])
    assert origin is not None, "the Gangnam POI should be cut, not blow up the spread"
    (lat, lng), _ = origin
    assert haversine_km(lat, lng, 37.4979, 127.0276) > 5.0, "centre drifted toward Gangnam"


def test_real_dataset_gangnam_falls_back() -> None:
    """Pins the one area where the centroid loses.

    Gangnam's courses straddle Sinsa and Apgujeong, so their centroid lands in the
    low-density gap between the clusters -- measurably worse than the hand-placed
    point. If a dataset refresh ever makes this pass silently, the sweep there
    would quietly get worse, so assert the fallback explicitly.
    """
    fell_back = []
    for area in DAY_PLAN_REGION_ORDER:
        segs = [{"day_numbers": [1], "area": area,
                 "anchor_courses": filter_pool(area)[:3]}]
        if _anchor_search_origin(area, segs) is None:
            fell_back.append(area)
    assert "gangnam" in fell_back, f"expected gangnam to fall back, got {fell_back}"


def test_origin_reaches_the_actual_google_call() -> None:
    """The centre/radius must survive the trip down to the request params."""
    calls: list[dict] = []
    orig_nearby, orig_text = planner.fetch_nearby_places, planner.fetch_text_places
    planner.fetch_nearby_places = lambda **kw: calls.append(kw) or []
    planner.fetch_text_places = lambda **kw: calls.append(kw) or []
    try:
        coords = [(37.5560 + i * 0.002, 126.9230 + i * 0.002) for i in range(5)]
        planner.build_google_supplement_for_area(
            area="hongdae", keywords=[{"phrase": "cafes", "poi_type": "cafe"}], api_key="test-key",
            day_segments=[_seg("hongdae", coords)],
        )
    finally:
        planner.fetch_nearby_places, planner.fetch_text_places = orig_nearby, orig_text

    assert calls, "no Google call was attempted"
    centers = {c.get("center") for c in calls}
    assert None not in centers, f"a call fell back to the fixed centre: {centers}"
    assert len(centers) == 1, f"calls disagreed on the centre: {centers}"

    fixed = SEOUL_AREA_CENTERS["hongdae"]
    (lat, lng) = centers.pop()
    assert (lat, lng) != fixed, "still searching from the hand-placed point"

    # The radius is a floor, never shrunk: a tight cluster keeps 2500m.
    for c in calls:
        assert c["radius"] >= 2500, c
        assert c["radius"] <= _ANCHOR_RADIUS_MAX_M, c


# ---------------------------------------------------------------------------
# What each sweep is told to look for, and what it is allowed to bring back
# ---------------------------------------------------------------------------

def test_each_purpose_keyword_is_one_search_with_its_own_poi_type() -> None:
    """The day's interest is not searched -- the anchors are already filtered by
    it. Only what the traveller named in their purpose is, one call each."""
    calls: list[dict] = []
    orig = planner.fetch_text_places
    planner.fetch_text_places = lambda **kw: calls.append(kw) or []
    try:
        planner.build_google_supplement_for_area(
            area="hongdae", keywords=[], api_key="k")
        assert calls == [], "no keywords must mean no Google calls"

        planner.build_google_supplement_for_area(
            area="hongdae", api_key="k", keywords=[
                {"phrase": "rooftop bars", "poi_type": "tourist_spot"},
                {"phrase": "BTS merch", "poi_type": "kpop_landmark"},
            ])
    finally:
        planner.fetch_text_places = orig

    assert [c["query"] for c in calls] == [
        "rooftop bars in Hongdae Seoul", "BTS merch in Hongdae Seoul"], calls
    assert [c["poi_type"] for c in calls] == ["tourist_spot", "kpop_landmark"]
    # K-pop stores are routinely unrated -- a 4.0 floor dropped all of them.
    assert [c["min_rating"] for c in calls] == [4.0, 0.0]


def test_a_sweep_cannot_stamp_an_out_of_area_place_with_the_requested_area() -> None:
    """Itaewon is not in the Hongdae zone, so an Itaewon hit from a Hongdae
    sweep must be dropped -- not relabelled 'hongdae' and handed to the validator,
    which trusts the stamp while the critic re-infers from coordinates."""
    places = [
        {"poi_name": "In Hongdae", "address_en": "", "lat": 37.5563, "lng": 126.9236},
        {"poi_name": "Really In Itaewon", "address_en": "", "lat": 37.5347, "lng": 126.9946},
        {"poi_name": "Nowhere", "address_en": "", "lat": None, "lng": None},
    ]
    kept = planner._stamp_true_area([dict(p) for p in places], "hongdae")
    names = [p["poi_name"] for p in kept]

    assert "Really In Itaewon" not in names
    assert "In Hongdae" in names
    # Un-inferable POIs keep the benefit of the doubt.
    assert "Nowhere" in names
    for p in kept:
        if p["poi_name"] == "In Hongdae":
            assert planner._area_matches_requested(p["area"], "hongdae")


if __name__ == "__main__":
    test_too_few_points_falls_back()
    test_tight_cluster_gets_a_centroid_that_covers_it()
    test_scatter_beyond_one_sweep_falls_back()
    test_out_of_area_poi_does_not_drag_the_centre()
    test_real_dataset_gangnam_falls_back()
    test_origin_reaches_the_actual_google_call()
    test_each_purpose_keyword_is_one_search_with_its_own_poi_type()
    test_a_sweep_cannot_stamp_an_out_of_area_place_with_the_requested_area()
    print("all anchor search self-checks passed")
