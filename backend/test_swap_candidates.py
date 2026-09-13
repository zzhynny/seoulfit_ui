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
    old = {"poi_name": "Old Diner", "poi_type": "restaurant",
           "lat": 37.556, "lng": 126.923, "area": "hongdae"}
    graph = _FakeGraph({
        "itinerary": {"days": [{"day": 1, "pois": [
            {"name": "Old Diner", "type": "restaurant", "lat": 37.556, "lng": 126.923},
        ]}]},
        "retrieved_courses": [{"sequence": [old]}],
        "planning_context": {},
    })
    fallback = critic_repair.candidate_from_google({
        "poi_name": "New Bistro", "poi_type": "restaurant",
        "address_en": "1 Hongik-ro", "lat": 37.557, "lng": 126.924, "rating": 4.5,
    })

    orig = (api._graph, critic_repair.google_fallback_candidates, planner.GOOGLE_PLACES_API_KEY)
    api._graph = graph
    critic_repair.google_fallback_candidates = lambda **kw: [fallback]
    planner.GOOGLE_PLACES_API_KEY = "test-key"
    try:
        r = TestClient(api.app).post("/swap-candidates", json={
            "thread_id": "trip-test-swap-0001", "day": 1, "slot_index": 0,
            "current_poi": "Old Diner", "day_area": "hongdae",
            "current_poi_type": "restaurant",
        })
        assert r.status_code == 200, r.text
        assert [c["poi_name"] for c in r.json()["candidates"]] == ["New Bistro"], r.json()

        # Exactly what /revalidate does with the traveller's pick.
        edited = critic_repair.apply_slot_edits(
            graph.values["itinerary"],
            {"swapped_slots": {"Old Diner": "New Bistro"}},
            critic_repair.build_candidate_pool(graph.values),
        )
        assert [p["name"] for p in edited["days"][0]["pois"]] == ["New Bistro"], edited
    finally:
        api._graph, critic_repair.google_fallback_candidates, planner.GOOGLE_PLACES_API_KEY = orig


if __name__ == "__main__":
    test_google_fallback_candidate_survives_revalidate()
    print("swap_candidates: all checks passed")
