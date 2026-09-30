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

    orig = (api._graph, critic_repair.google_fallback_candidates)
    api._graph = graph
    critic_repair.google_fallback_candidates = lambda **kw: []  # no top-up, no network
    try:
        r = TestClient(api.app).post("/swap-candidates", json={
            "thread_id": "trip-test-swap-0002", "day": 1, "slot_index": 0,
            "current_poi": "Locked Dinner Pick", "day_area": "jongno",
            "current_poi_type": "restaurant",
        })
        assert r.status_code == 200, r.text
        got = r.json()["candidates"]
    finally:
        api._graph, critic_repair.google_fallback_candidates = orig

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

    # And the pick has to survive /revalidate. restaurant.json feeds neither of
    # build_candidate_pool's two sources, so offering a Michelin row without
    # leaving it on the thread silently keeps the original stop.
    picked = got[0]["poi_name"]
    edited = critic_repair.apply_slot_edits(
        graph.values["itinerary"],
        {"swapped_slots": {"Locked Dinner Pick": picked}},
        critic_repair.build_candidate_pool(graph.values),
    )
    assert [p["name"] for p in edited["days"][0]["pois"]] == [picked], edited


def test_restaurant_swap_falls_back_when_nothing_michelin_is_near():
    """Deep in a residential outer district there is no Michelin within 1km, and
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


def test_a_vegetarians_restaurant_swap_offers_only_vegetarian_michelin():
    import meal_slots

    # At a Vegan Michelin restaurant, so the sheet has one to offer.
    veg = [r for r in meal_slots.load_restaurants() if r["cuisine"] in ("Vegan", "Vegetarian")]
    lat, lng = float(veg[0]["lat"]), float(veg[0]["lon"])
    graph = _FakeGraph({
        "itinerary": {"days": [{"day": 1, "pois": [
            {"name": "Locked Dinner Pick", "type": "restaurant",
             "lat": lat, "lng": lng, "meal_slot": "dinner"},
        ]}]},
        "retrieved_courses": [], "trip_start_date": "2026-10-05",
        "planning_context": {}, "diet": "vegetarian",
    })
    orig = (api._graph, critic_repair.google_fallback_candidates)
    api._graph = graph
    critic_repair.google_fallback_candidates = lambda **kw: []  # no top-up, no network
    try:
        got = TestClient(api.app).post("/swap-candidates", json={
            "thread_id": "trip-test-swap-0004", "day": 1, "slot_index": 0,
            "current_poi": "Locked Dinner Pick", "day_area": "gangnam",
            "current_poi_type": "restaurant",
        }).json()["candidates"]
    finally:
        api._graph, critic_repair.google_fallback_candidates = orig

    cuisine = {r["name"]: r["cuisine"] for r in meal_slots.load_restaurants()}
    michelin_rows = [c for c in got if c["poi_name"] in cuisine]
    assert michelin_rows, got
    assert all(cuisine[c["poi_name"]] in ("Vegan", "Vegetarian") for c in michelin_rows), got


def test_fewer_than_3_michelin_are_topped_up_by_the_nearest_google():
    """Michelin first; the gap to 3 is Google around the same stop, nearest first,
    and nothing past SWAP_RADIUS_KM."""
    import meal_slots

    lat, lng = 37.5500, 126.9200
    km = 1 / 111  # degrees of latitude per km
    graph = _FakeGraph({
        "itinerary": {"days": [{"day": 1, "pois": [
            {"name": "Old Lunch", "type": "restaurant", "lat": lat, "lng": lng},
        ]}]},
        "retrieved_courses": [], "planning_context": {},
    })

    def google(name, dist_km):
        return critic_repair.candidate_from_google({
            "poi_name": name, "poi_type": "restaurant", "address_en": "x",
            "lat": lat + dist_km * km, "lng": lng, "rating": 4.0,
        })

    one_michelin = [{"name": "Star Place", "street": "s", "lat": lat, "lon": lng,
                     "grade": "1스타", "distance_km": 0.2, "closed": False}]
    orig = (api._graph, critic_repair.google_fallback_candidates,
            planner.GOOGLE_PLACES_API_KEY, meal_slots.nearest_michelin)
    api._graph = graph
    critic_repair.google_fallback_candidates = lambda **kw: [
        google("Far G", 1.4), google("Mid G", 0.8), google("Near G", 0.3), google("Close G", 0.5)]
    planner.GOOGLE_PLACES_API_KEY = "test-key"
    meal_slots.nearest_michelin = lambda **kw: one_michelin
    try:
        got = TestClient(api.app).post("/swap-candidates", json={
            "thread_id": "trip-test-swap-0005", "day": 1, "slot_index": 0,
            "current_poi": "Old Lunch", "day_area": "hongdae",
            "current_poi_type": "restaurant",
        }).json()["candidates"]
    finally:
        (api._graph, critic_repair.google_fallback_candidates,
         planner.GOOGLE_PLACES_API_KEY, meal_slots.nearest_michelin) = orig

    assert [c["poi_name"] for c in got] == ["Star Place", "Near G", "Close G"], got
    assert got[1]["grade"] is None and got[1]["rating"] == 4.0, got
    assert got[1]["distance_km"] < got[2]["distance_km"] <= meal_slots.SWAP_RADIUS_KM, got
