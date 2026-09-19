"""Self-check for poi_text: per-stop text grounded in a web search, cached per
place so it reads the same on every screen and every app launch.

No network: the Tavily search and the Gemini rewrite are swapped for fakes.
Run:  backend/venv/bin/python backend/test_poi_text.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poi_text  # noqa: E402

# Deliberately a place neither index lists: these tests exercise the fallback
# paths (Tavily + Gemini text, Google Places photo), and both _POI_SNAP
# (TourAPI) and _MICHELIN_SNAP (restaurant.json) short-circuit ahead of them.
# "Hannam Corner Cafe", the old fixture, is Michelin-listed and stopped reaching them.
WEB = "Hannam Corner Cafe is a small neighbourhood coffee shop in Hannam-dong, Seoul."
REPLY = "A small neighbourhood coffee shop in Hannam-dong."


def _isolated(fn, *, web=(WEB,), reply=REPLY, key="test-key"):
    """Runs fn(searches, prompts) with a temp cache file, a Tavily key (or
    none), and fake search/rewrite. `web` answers searches in order, the last
    one repeating; an Exception entry is raised instead of returned."""
    searches, prompts = [], []

    def fake_search(query):
        searches.append(query)
        answer = web[min(len(searches), len(web)) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def fake_write(prompt):
        prompts.append(prompt)
        return reply

    orig = (poi_text._search, poi_text._write, poi_text.CACHE_PATH,
            dict(poi_text._CACHE), os.environ.get("TAVILY_API_KEY"))
    with tempfile.TemporaryDirectory() as tmp:
        poi_text._search, poi_text._write = fake_search, fake_write
        poi_text.CACHE_PATH = Path(tmp) / "poi_text_cache.json"
        poi_text._CACHE.clear()
        if key is None:
            os.environ.pop("TAVILY_API_KEY", None)
        else:
            os.environ["TAVILY_API_KEY"] = key
        try:
            fn(searches, prompts)
        finally:
            poi_text._search, poi_text._write, poi_text.CACHE_PATH = orig[:3]
            poi_text._CACHE.clear()
            poi_text._CACHE.update(orig[3])
            if orig[4] is None:
                os.environ.pop("TAVILY_API_KEY", None)
            else:
                os.environ["TAVILY_API_KEY"] = orig[4]


def test_text_comes_from_the_web_search_not_memory():
    def run(searches, prompts):
        assert poi_text.poi_text("summary", "Hannam Corner Cafe", "restaurant") == REPLY
        assert "Hannam Corner Cafe" in searches[0], searches
        assert WEB in prompts[0], prompts
        assert "ONLY" in prompts[0], prompts

    _isolated(run)


def test_the_same_place_reads_the_same_everywhere():
    def run(searches, prompts):
        first = poi_text.poi_text("summary", "Hannam Corner Cafe", "restaurant")
        again = poi_text.poi_text("summary", "  hannam corner cafe ", "")
        assert again == first
        assert len(searches) == 1, searches

    _isolated(run)


def test_each_kind_of_text_is_its_own_entry():
    def run(searches, prompts):
        for kind in ("summary", "detail"):
            poi_text.poi_text(kind, "Hannam Corner Cafe", "restaurant")
        assert len(searches) == 2, searches

    _isolated(run)


def test_nothing_on_the_web_means_no_text_and_no_guessing():
    def run(searches, prompts):
        assert poi_text.poi_text("summary", "Nowhere Cafe") == ""
        assert poi_text.poi_text("summary", "Nowhere Cafe") == ""
        assert prompts == [], "Gemini must not write text with nothing to go on"
        assert len(searches) == 1, "an empty answer is still an answer — don't pay twice"

    _isolated(run, web=("",))


def test_a_none_reply_means_no_text():
    # The model's way of saying the search didn't clearly describe this place.
    def run(searches, prompts):
        assert poi_text.poi_text("summary", "Hannam Corner Cafe") == ""

    _isolated(run, reply="NONE")


def test_errors_are_not_cached():
    def run(searches, prompts):
        try:
            poi_text.poi_text("summary", "Hannam Corner Cafe")
            raise AssertionError("a search failure must surface, not become empty text")
        except RuntimeError:
            pass
        assert poi_text.poi_text("summary", "Hannam Corner Cafe") == REPLY
        assert len(searches) == 2, searches

    _isolated(run, web=(RuntimeError("tavily down"), WEB))


def test_cached_text_survives_a_restart():
    def run(searches, prompts):
        poi_text.poi_text("summary", "Hannam Corner Cafe")
        poi_text._CACHE.clear()
        poi_text._load_cache_from_disk()
        assert poi_text.poi_text("summary", "Hannam Corner Cafe") == REPLY
        assert len(searches) == 1, searches

    _isolated(run)


def test_missing_key_is_reported_but_cached_text_still_serves():
    def run(searches, prompts):
        try:
            poi_text.poi_text("summary", "Hannam Corner Cafe")
            raise AssertionError("expected NotConfigured")
        except poi_text.NotConfigured:
            pass
        assert searches == []

    _isolated(run, key=None)


def test_endpoints_serve_the_grounded_text():
    from fastapi.testclient import TestClient
    import api

    def run(searches, prompts):
        client = TestClient(api.app)
        body = {"name": "Hannam Corner Cafe", "type": "restaurant"}
        assert client.post("/poi-summary", json=body).json() == {"summary": REPLY}
        # Removed: its web results rarely said what an entrance looks like.
        assert client.post("/poi-arrival-tip", json=body).status_code == 404
        assert client.post("/poi-detail", json=body).json() == {"detail": REPLY}

    _isolated(run)

    def no_key(searches, prompts):
        client = TestClient(api.app)
        r = client.post("/poi-summary", json={"name": "Somewhere New", "type": ""})
        assert r.status_code == 503, r.text

    _isolated(no_key, key=None)


def test_the_whole_chain_fits_inside_the_client_budget():
    """TourAPI -> Tavily -> Gemini must finish before the app gives up.

    Every other test here stubs _search and _rewrite, so no individual timeout is
    ever exercised and raising one back up would break nothing that runs. This is
    the only thing standing between that and a POI sheet that spins for 30s and
    then renders empty, which is what shipped before these bounds existed.

    30s is api_service._fetchPoiField's own timeout. The margin is deliberate:
    the legs are sequential worst cases, not a budget to spend.
    """
    import tourapi

    CLIENT_TIMEOUT_S = 30
    worst_case = (
        tourapi._TIMEOUT
        + poi_text._TAVILY_TIMEOUT
        + poi_text._GEMINI_TIMEOUT_MS / 1000
    )
    assert worst_case < CLIENT_TIMEOUT_S, (
        f"POI text chain can take {worst_case}s but the client gives up at "
        f"{CLIENT_TIMEOUT_S}s -- the sheet will render empty"
    )


if __name__ == "__main__":
    test_text_comes_from_the_web_search_not_memory()
    test_the_same_place_reads_the_same_everywhere()
    test_each_kind_of_text_is_its_own_entry()
    test_nothing_on_the_web_means_no_text_and_no_guessing()
    test_a_none_reply_means_no_text()
    test_errors_are_not_cached()
    test_cached_text_survives_a_restart()
    test_missing_key_is_reported_but_cached_text_still_serves()
    test_endpoints_serve_the_grounded_text()
    print("poi_text: all checks passed")
