"""Self-check for /poi-image: the course's own photo first, then the place's
Google Maps photo (owner and reviewer uploads) through the /place-photo proxy.
No web image search, and the Places key never appears in a returned URL.

Run:  backend/venv/bin/python backend/test_poi_image.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
import planner  # noqa: E402

client = TestClient(api.app)


def _with(fn, *, photo_ref="REF123", key="test-key", images=None):
    """Runs fn(looked_up) with a fake Google lookup, a Places key (or none),
    and a stand-in course-photo table; restores everything after."""
    looked_up = []
    orig_lookup = planner.find_place_photo_ref
    orig_key = os.environ.get("GOOGLE_PLACES_API_KEY")
    orig_images = api._POI_IMAGES

    def fake_lookup(*, name, api_key):
        looked_up.append(name)
        return photo_ref

    planner.find_place_photo_ref = fake_lookup
    if key is None:
        os.environ.pop("GOOGLE_PLACES_API_KEY", None)
    else:
        os.environ["GOOGLE_PLACES_API_KEY"] = key
    api._POI_IMAGES = images if images is not None else {}
    try:
        fn(looked_up)
    finally:
        planner.find_place_photo_ref = orig_lookup
        if orig_key is None:
            os.environ.pop("GOOGLE_PLACES_API_KEY", None)
        else:
            os.environ["GOOGLE_PLACES_API_KEY"] = orig_key
        api._POI_IMAGES = orig_images


def _image_for(name, type_="restaurant"):
    return client.post("/poi-image", json={"name": name, "type": type_})


def test_course_photo_wins_without_a_google_lookup():
    def run(looked_up):
        r = _image_for("Test Palace", "history")
        assert r.json() == {"image_url": "https://img.example/palace.jpg"}, r.json()
        assert looked_up == []

    _with(run, images={"Test Palace": "https://img.example/palace.jpg"})


def test_google_maps_photo_goes_through_the_key_hiding_proxy():
    def run(looked_up):
        # Deliberately a place neither index lists: these tests exercise the fallback
        # paths (Tavily + Gemini text, Google Places photo), and both _POI_SNAP
        # (TourAPI) and _MICHELIN_SNAP (restaurant.json) short-circuit ahead of them.
        # "Hannam Corner Cafe", the old fixture, is Michelin-listed and stopped reaching them.
        r = _image_for("Hannam Corner Cafe")
        assert r.status_code == 200, r.text
        url = r.json()["image_url"]
        assert url == "http://testserver/place-photo?ref=REF123&w=400", url
        assert "test-key" not in url
        assert looked_up == ["Hannam Corner Cafe"]

    _with(run)


def test_no_google_photo_means_no_image():
    def run(looked_up):
        assert _image_for("Nowhere Cafe").json() == {"image_url": ""}

    _with(run, photo_ref=None)


def test_missing_places_key_is_reported():
    def run(looked_up):
        assert _image_for("Hannam Corner Cafe").status_code == 503
        assert looked_up == []

    _with(run, key=None)


def test_photo_lookup_takes_the_first_photo_and_stays_in_seoul():
    seen = {}
    orig = planner._google_get

    def fake_get(url, params):
        seen.update(params)
        return fake_get.reply

    planner._google_get = fake_get
    try:
        fake_get.reply = {"candidates": [{"photos": [{"photo_reference": "R1"}, {"photo_reference": "R2"}]}]}
        assert planner.find_place_photo_ref(name="Hannam Corner Cafe", api_key="k") == "R1"
        assert "photos" in seen["fields"], seen
        assert seen["locationbias"].startswith("circle:"), seen

        fake_get.reply = {"candidates": [{"name": "No Photos Here"}]}
        assert planner.find_place_photo_ref(name="Hannam Corner Cafe", api_key="k") is None

        fake_get.reply = {"candidates": []}
        assert planner.find_place_photo_ref(name="Hannam Corner Cafe", api_key="k") is None
    finally:
        planner._google_get = orig


if __name__ == "__main__":
    test_course_photo_wins_without_a_google_lookup()
    test_google_maps_photo_goes_through_the_key_hiding_proxy()
    test_no_google_photo_means_no_image()
    test_missing_places_key_is_reported()
    test_photo_lookup_takes_the_first_photo_and_stays_in_seoul()
    print("poi_image: all checks passed")
