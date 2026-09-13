"""Self-check for odsay: the on-disk route cache, error handling, and the
short-hop skip in planner.compute_transit_legs.

No network: requests.get is swapped for a counter that answers from fixtures.
Run:  backend/venv/bin/python backend/test_odsay.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import odsay  # noqa: E402
import planner  # noqa: E402

_OK = {"result": {"path": [{
    "pathType": 1,
    "info": {"totalTime": 20, "payment": 1500, "totalWalk": 300,
             "subwayTransitCount": 1, "busTransitCount": 0},
    "subPath": [],
}]}}
_NO_ROUTE = {"result": {"path": []}}
_QUOTA = {"error": [{"code": "429", "message": "Daily quota exceeded"}]}

HOP = (37.5796, 126.9770, 37.5636, 126.9860)   # Gyeongbokgung -> Myeongdong


class _Resp:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def _isolated(fn, *responses):
    """Runs fn(calls) with a temp cache file, a fake key, no call gap, and
    requests.get answering `responses` in order (the last one repeats)."""
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        return _Resp(responses[min(len(calls), len(responses)) - 1])

    orig = (odsay.requests.get, odsay.ODSAY_API_KEY, odsay.CACHE_PATH,
            odsay.CALL_GAP_SECONDS, dict(odsay._CACHE))
    with tempfile.TemporaryDirectory() as tmp:
        odsay.requests.get = fake_get
        odsay.ODSAY_API_KEY = "test-key"
        odsay.CACHE_PATH = Path(tmp) / "odsay_cache.json"
        odsay.CALL_GAP_SECONDS = 0
        odsay._CACHE.clear()
        try:
            fn(calls)
        finally:
            (odsay.requests.get, odsay.ODSAY_API_KEY, odsay.CACHE_PATH,
             odsay.CALL_GAP_SECONDS) = orig[:4]
            odsay._CACHE.clear()
            odsay._CACHE.update(orig[4])


def test_the_same_hop_is_only_paid_for_once():
    def run(calls):
        first = odsay.fetch_odsay_options(*HOP)
        second = odsay.fetch_odsay_options(*HOP)
        assert len(first) == 1 and second == first, (first, second)
        assert len(calls) == 1, calls

    _isolated(run, _OK)


def test_gps_jitter_still_hits_the_cache():
    def run(calls):
        odsay.fetch_odsay_options(*HOP)
        lat1, lng1, lat2, lng2 = HOP
        odsay.fetch_odsay_options(lat1 + 0.000001, lng1, lat2, lng2 - 0.000001)
        assert len(calls) == 1, calls

    _isolated(run, _OK)


def test_errors_are_not_cached_so_they_retry_later():
    # A quota or network error says nothing about the route itself.
    def run(calls):
        assert odsay.fetch_odsay_options(*HOP) == []
        assert len(odsay.fetch_odsay_options(*HOP)) == 1
        assert len(calls) == 2, calls

    _isolated(run, _QUOTA, _OK)


def test_a_no_route_answer_is_cached():
    def run(calls):
        assert odsay.fetch_odsay_options(*HOP) == []
        assert odsay.fetch_odsay_options(*HOP) == []
        assert len(calls) == 1, calls

    _isolated(run, _NO_ROUTE)


def test_cached_routes_survive_a_restart():
    def run(calls):
        odsay.fetch_odsay_options(*HOP)
        odsay._CACHE.clear()
        odsay._load_cache_from_disk()
        assert len(odsay.fetch_odsay_options(*HOP)) == 1
        assert len(calls) == 1, calls

    _isolated(run, _OK)


def test_expired_routes_are_fetched_again():
    def run(calls):
        odsay.fetch_odsay_options(*HOP)
        key = next(iter(odsay._CACHE))
        odsay._CACHE[key][0] = 0  # expired long ago
        odsay.fetch_odsay_options(*HOP)
        assert len(calls) == 2, calls

    _isolated(run, _OK)


def test_short_hops_never_call_odsay():
    asked = []
    orig = odsay.fetch_odsay_options, odsay.ODSAY_API_KEY
    odsay.fetch_odsay_options = lambda *coords: asked.append(coords) or []
    odsay.ODSAY_API_KEY = "test-key"
    try:
        near = [{"name": "a", "lat": 37.5700, "lng": 126.9700},
                {"name": "b", "lat": 37.5705, "lng": 126.9705}]    # ~70 m
        legs = planner.compute_transit_legs(near)
        assert asked == [] and legs[0]["transit_options"] == [], asked

        far = [{"name": "a", "lat": 37.5700, "lng": 126.9700},
               {"name": "b", "lat": 37.5500, "lng": 126.9900}]    # ~2.8 km
        planner.compute_transit_legs(far)
        assert len(asked) == 1, asked
    finally:
        odsay.fetch_odsay_options, odsay.ODSAY_API_KEY = orig


if __name__ == "__main__":
    test_the_same_hop_is_only_paid_for_once()
    test_gps_jitter_still_hits_the_cache()
    test_errors_are_not_cached_so_they_retry_later()
    test_a_no_route_answer_is_cached()
    test_cached_routes_survive_a_restart()
    test_expired_routes_are_fetched_again()
    test_short_hops_never_call_odsay()
    print("odsay: all checks passed")
