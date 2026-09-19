"""Self-check: a swap candidate only Google's fallback found still lands in the
plan. /revalidate swaps in names from build_candidate_pool(state), so
/swap-candidates has to leave fallback candidates on the thread.

Run:  backend/venv/bin/python backend/test_swap_candidates.py
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
import critic_repair  # noqa: E402
import planner  # noqa: E402


class _FakeGraph:
    def __init__(self, values):
        self.values = values

    def get_state(self, config):
        return SimpleNamespace(values=self.values)

    def update_state(self, config, update):
        self.values = {**self.values, **update}


def test_google_fallback_candidate_survives_revalidate():
    # A cafe, not a restaurant: restaurant slots now go to the Michelin branch
    # (see the test below) and never reach the Google fallback while something
    # Michelin sits within SWAP_RADIUS_KM -- which, in Hongdae, it does. The
    # fallback -> revalidate path this test is actually about is unchanged.
    old = {"poi_name": "Old Cafe", "poi_type": "cafe",
           "lat": 37.556, "lng": 126.923, "area": "hongdae"}
    graph = _FakeGraph({
        "itinerary": {"days": [{"day": 1, "pois": [
            {"name": "Old Cafe", "type": "cafe", "lat": 37.556, "lng": 126.923},
        ]}]},
        "retrieved_courses": [{"sequence": [old]}],
        "planning_context": {},
    })
    fallback = critic_repair.candidate_from_google({
        "poi_name": "New Cafe", "poi_type": "cafe",
        "address_en": "1 Hongik-ro", "lat": 37.557, "lng": 126.924, "rating": 4.5,
    })

    orig = (api._graph, critic_repair.google_fallback_candidates, planner.GOOGLE_PLACES_API_KEY)
    api._graph = graph
    critic_repair.google_fallback_candidates = lambda **kw: [fallback]
    planner.GOOGLE_PLACES_API_KEY = "test-key"
    try:
        r = TestClient(api.app).post("/swap-candidates", json={
            "thread_id": "trip-test-swap-0001", "day": 1, "slot_index": 0,
            "current_poi": "Old Cafe", "day_area": "hongdae",
            "current_poi_type": "cafe",
        })
        assert r.status_code == 200, r.text
        assert [c["poi_name"] for c in r.json()["candidates"]] == ["New Cafe"], r.json()

        # Exactly what /revalidate does with the traveller's pick.
        edited = critic_repair.apply_slot_edits(
            graph.values["itinerary"],
            {"swapped_slots": {"Old Cafe": "New Cafe"}},
            critic_repair.build_candidate_pool(graph.values),
        )
        assert [p["name"] for p in edited["days"][0]["pois"]] == ["New Cafe"], edited
    finally:
        api._graph, critic_repair.google_fallback_candidates, planner.GOOGLE_PLACES_API_KEY = orig


def test_restaurant_swap_offers_michelin_nearest_first():
    """A restaurant slot swaps within the curated set the locked meals come from,
    ranked by distance -- not Google's prominence ranking of the area centre."""
    import meal_slots

    # Gyeongbokgung. The locked meal is not in retrieved_courses or
    # google_supplement, so build_candidate_pool cannot supply its coordinates --
    # they have to come off the itinerary.
    lat, lng = 37.5796, 126.9770
    graph = _FakeGraph({
        "itinerary": {"days": [{"day": 1, "pois": [
            {"name": "Locked Dinner Pick", "type": "restaurant",
             "lat": lat, "lng": lng, "meal_slot": "dinner"},
        ]}]},
        "retrieved_courses": [],
        "trip_start_date": "2026-10-05",   # a Monday
        "planning_context": {},
    })

    orig = api._graph
    api._graph = graph
    try:
        r = TestClient(api.app).post("/swap-candidates", json={
            "thread_id": "trip-test-swap-0002", "day": 1, "slot_index": 0,
            "current_poi": "Locked Dinner Pick", "day_area": "jongno",
            "current_poi_type": "restaurant",
        })
        assert r.status_code == 200, r.text
        got = r.json()["candidates"]
    finally:
        api._graph = orig

    assert got, "restaurant swap returned nothing"
    names = {c["poi_name"] for c in got}
    michelin = {x["name"] for x in meal_slots.load_restaurants()}
    assert names <= michelin, f"non-Michelin candidates offered: {names - michelin}"

    distances = [c["distance_km"] for c in got]
    assert distances == sorted(distances), f"not nearest-first: {distances}"
    assert all(d <= meal_slots.SWAP_RADIUS_KM for d in distances), distances

    # Monday closures are surfaced, not filtered out -- the traveller decides.
    assert any(c["warnings"] for c in got), got
    assert all("grade" in c for c in got), got


def test_restaurant_swap_falls_back_when_nothing_michelin_is_near():
    """Deep in a residential outer district there is no Michelin within 2km, and
    an empty sheet is worse than a Google suggestion."""
    graph = _FakeGraph({
        "itinerary": {"days": [{"day": 1, "pois": [
            {"name": "Far Diner", "type": "restaurant", "lat": 37.6900, "lng": 127.0900},
        ]}]},
        "retrieved_courses": [],
        "planning_context": {},
    })
    fallback = critic_repair.candidate_from_google({
        "poi_name": "Suburb Bistro", "poi_type": "restaurant",
        "address_en": "far away", "lat": 37.6901, "lng": 127.0901, "rating": 4.2,
    })

    orig = (api._graph, critic_repair.google_fallback_candidates, planner.GOOGLE_PLACES_API_KEY)
    api._graph = graph
    critic_repair.google_fallback_candidates = lambda **kw: [fallback]
    planner.GOOGLE_PLACES_API_KEY = "test-key"
    try:
        r = TestClient(api.app).post("/swap-candidates", json={
            "thread_id": "trip-test-swap-0003", "day": 1, "slot_index": 0,
            "current_poi": "Far Diner", "day_area": "nowon",
            "current_poi_type": "restaurant",
        })
        assert r.status_code == 200, r.text
        assert [c["poi_name"] for c in r.json()["candidates"]] == ["Suburb Bistro"], r.json()
    finally:
        api._graph, critic_repair.google_fallback_candidates, planner.GOOGLE_PLACES_API_KEY = orig


if __name__ == "__main__":
    test_google_fallback_candidate_survives_revalidate()
    test_restaurant_swap_offers_michelin_nearest_first()
    test_restaurant_swap_falls_back_when_nothing_michelin_is_near()
    print("swap_candidates: all checks passed")
