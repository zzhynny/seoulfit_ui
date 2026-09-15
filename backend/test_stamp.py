"""Self-check for stamp: route extraction, prompt, generation status, and the
/trip/checkin + /trip/stamp wiring.

The whole trip gets ONE stamp: every visited place, grouped by day, in the
order it was visited. Visited/partial/empty state is still drawn natively by
trip_recap_screen.dart; this module only paints the background.

Run:  backend/venv/bin/python backend/test_stamp.py
"""
import base64
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stamp  # noqa: E402
from stamp import (  # noqa: E402
    build_prompt, english_labels, generate_stamp, request_stamp, stamp_status, track_rows,
    valid_trip_id, visited_by_day,
)

_HANGUL = re.compile(r"[ᄀ-ᇿ㄰-㆏가-힣]")

ITIN = {"planned": {"1": ["a", "b"], "2": ["c", "d", "e"], "3": ["f"]}}
VISITS = {"1": {"visited": ["b"], "misses": {}}, "2": {"visited": ["e", "c"], "misses": {}}}

_FAKE_PNG_B64 = base64.b64encode(b"fake-png-bytes").decode()


class _FakeImageData:
    b64_json = _FAKE_PNG_B64


class _FakeResult:
    data = [_FakeImageData()]


class _FakeImagesEdit:
    def __init__(self, raise_error=False):
        self.raise_error = raise_error
        self.calls = 0

    def edit(self, **kwargs):
        self.calls += 1
        self.kwargs = kwargs
        if self.raise_error:
            raise RuntimeError("simulated API failure")
        return _FakeResult()


class _FakeClient:
    def __init__(self, raise_error=False):
        self.images = _FakeImagesEdit(raise_error=raise_error)


def _with_temp_dirs(fn):
    """Runs fn with stamp's template/stamps paths pointed at a temp dir, so the
    real assets and stamps directories are never touched."""
    orig_template, orig_stamps = stamp._TEMPLATE_PATH, stamp._STAMPS_DIR
    with tempfile.TemporaryDirectory() as tmp:
        template_path = os.path.join(tmp, "template.png")
        with open(template_path, "wb") as f:
            f.write(b"template-bytes")
        stamp._TEMPLATE_PATH = template_path
        stamp._STAMPS_DIR = os.path.join(tmp, "stamps")
        try:
            fn()
        finally:
            stamp._TEMPLATE_PATH, stamp._STAMPS_DIR = orig_template, orig_stamps


def test_route_groups_visits_by_day_in_plan_order():
    # Plan order within a day (c before e), not the order the visited set lists.
    assert visited_by_day(ITIN, VISITS) == [(1, ["b"]), (2, ["c", "e"])]


def test_route_skips_unvisited_days_and_unplanned_names():
    days = {"1": {"visited": ["b", "not-a-real-stop"]}, "3": {"visited": []}}
    assert visited_by_day(ITIN, days) == [(1, ["b"])]


def test_route_is_empty_when_nothing_checked_in():
    assert visited_by_day(ITIN, {}) == []


def test_prompt_numbers_every_place_in_order_under_its_day():
    prompt = build_prompt([(1, ["Gyeongbokgung", "Tosokchon"]), (2, ["N Seoul Tower"])])
    assert "Day 1:\n1. Gyeongbokgung\n2. Tosokchon\nDay 2:\n3. N Seoul Tower" in prompt, prompt


def test_prompt_counts_every_place_and_says_what_kind_it_is():
    # "ANAM" or "JUEUN" alone tell an image model nothing to draw, and without
    # a count it quietly merges or drops places. Types go in square brackets so
    # they can't be mistaken for part of the name to write.
    prompt = build_prompt(
        [(1, ["ANAM", "Jogeum"]), (2, ["JUEUN"])],
        {"ANAM": "restaurant", "JUEUN": "cafe"},
    )
    assert "exactly 3" in prompt, prompt
    assert "1. ANAM [restaurant]\n2. Jogeum\n" in prompt, prompt
    assert "3. JUEUN [cafe]" in prompt, prompt


def test_prompt_asks_for_a_number_and_name_label_by_each_place():
    prompt = build_prompt([(1, ["Gyeongbokgung"])]).lower()
    assert "label" in prompt and "number and name" in prompt, prompt
    assert "do not add any text" not in prompt


def test_prompt_pins_exactly_one_label_per_number():
    # A real render drew "7. JUEUN" twice plus a garbled extra "10." label, so
    # the prompt says outright: this many labels, each number once, nothing else.
    prompt = build_prompt([(1, ["A", "B"]), (2, ["C"])])
    assert "exactly 3 labels" in prompt, prompt
    assert "each number appears exactly once" in prompt.lower(), prompt


def test_track_rows_follow_the_snaking_rail():
    # Real renders numbered every row left to right, so rows the rail runs
    # right to left came out backwards. Even rows are listed reversed.
    assert track_rows(14) == [[1, 2, 3], [6, 5, 4], [7, 8], [10, 9], [11, 12], [14, 13]]
    assert track_rows(3) == [[1], [2], [3]]
    rows = track_rows(23)
    assert sorted(n for row in rows for n in row) == list(range(1, 24)), rows
    prompt = build_prompt([(1, [str(i) for i in range(14)])])
    assert "Row 2: 6, 5, 4\n" in prompt, prompt


def test_english_names_pass_through_without_a_translation_call():
    calls = []
    labels = english_labels(
        ["Bukchon Hanok Village (북촌한옥마을)", "모드곤 MODGONE", "ANAM"],
        lambda names: calls.append(names) or {},
    )
    assert labels == {
        "Bukchon Hanok Village (북촌한옥마을)": "Bukchon Hanok Village",
        "모드곤 MODGONE": "MODGONE",
        "ANAM": "ANAM",
    }, labels
    assert calls == []


def test_korean_only_names_are_translated_in_one_call():
    calls = []

    def fake(names):
        calls.append(names)
        return {"갤러리현": "Gallery Hyun", "장수촌 풍천장어직판장": "Jangsuchon Eel House"}

    labels = english_labels(["갤러리현", "ANAM", "장수촌 풍천장어직판장"], fake)
    assert labels["갤러리현"] == "Gallery Hyun"
    assert labels["장수촌 풍천장어직판장"] == "Jangsuchon Eel House"
    assert calls == [["갤러리현", "장수촌 풍천장어직판장"]], calls


def test_a_failed_or_korean_translation_falls_back_to_romanization():
    # The image must never get Korean, even when the translation step fails.
    def broken(names):
        raise RuntimeError("gemini down")

    assert english_labels(["갤러리현"], broken) == {"갤러리현": "Gaelreorihyeon"}
    assert english_labels(["갤러리현"], lambda names: {"갤러리현": "갤러리 현"}) == {"갤러리현": "Gaelreorihyeon"}


def test_prompt_prints_the_english_label_not_the_original_name():
    prompt = build_prompt([(1, ["갤러리현"])], {"갤러리현": "gallery"}, {"갤러리현": "Gallery Hyun"})
    assert "1. Gallery Hyun [gallery]" in prompt, prompt
    assert not _HANGUL.search(prompt), prompt


def test_generated_prompt_has_no_korean_at_all():
    def run():
        fake = _FakeClient()
        stamp._client = fake
        original = stamp._translate
        stamp._translate = lambda names: {n: "Gallery Hyun" for n in names}
        try:
            names = ["갤러리현", "Bukchon Hanok Village (북촌한옥마을)"]
            generate_stamp("trip-k", {"planned": {"1": names}}, {"1": {"visited": names}})
        finally:
            stamp._translate = original
        prompt = fake.images.kwargs["prompt"]
        assert "1. Gallery Hyun\n2. Bukchon Hanok Village" in prompt, prompt
        assert not _HANGUL.search(prompt), prompt

    _with_temp_dirs(run)


def test_generate_stamp_sends_place_types_into_the_prompt():
    def run():
        fake = _FakeClient()
        stamp._client = fake
        itin = {**ITIN, "types": {"b": "market", "c": "cafe"}}
        generate_stamp("trip-t", itin, VISITS)
        assert "b [market]" in fake.images.kwargs["prompt"]
        assert "c [cafe]" in fake.images.kwargs["prompt"]

    _with_temp_dirs(run)


def test_trip_ids_are_checked_before_touching_the_filesystem():
    # trip_id comes from an unauthenticated client and becomes a file name.
    assert valid_trip_id("trip-1789114877434")
    for bad in ["../evil", "a/b", "", "x" * 129, "trip.png"]:
        assert not valid_trip_id(bad), bad


def test_nothing_visited_requests_no_stamp():
    def run():
        assert request_stamp("trip-none", ITIN, {}) is False
        assert stamp_status("trip-none") == {"status": "none"}

    _with_temp_dirs(run)


def test_generation_reports_generating_then_ready():
    def run():
        stamp._client = _FakeClient()
        assert request_stamp("trip-x", ITIN, VISITS) is True
        assert stamp_status("trip-x") == {"status": "generating"}

        generate_stamp("trip-x", ITIN, VISITS)

        with open(os.path.join(stamp._STAMPS_DIR, "trip-x.png"), "rb") as f:
            assert f.read() == b"fake-png-bytes"
        status = stamp_status("trip-x")
        assert status["status"] == "ready" and isinstance(status["version"], int), status

    _with_temp_dirs(run)


def test_failed_generation_without_a_stamp_reports_failed_and_can_retry():
    def run():
        stamp._client = _FakeClient(raise_error=True)
        assert request_stamp("trip-f", ITIN, VISITS) is True
        generate_stamp("trip-f", ITIN, VISITS)

        assert stamp_status("trip-f") == {"status": "failed"}
        assert request_stamp("trip-f", ITIN, VISITS) is True, "a failure must not block a retry"

    _with_temp_dirs(run)


def test_failed_generation_keeps_the_previous_stamp():
    def run():
        os.makedirs(stamp._STAMPS_DIR, exist_ok=True)
        out = os.path.join(stamp._STAMPS_DIR, "trip-y.png")
        with open(out, "wb") as f:
            f.write(b"previous-stamp")

        stamp._client = _FakeClient(raise_error=True)
        request_stamp("trip-y", ITIN, VISITS)
        generate_stamp("trip-y", ITIN, VISITS)

        with open(out, "rb") as f:
            assert f.read() == b"previous-stamp", "failure must not clobber the cached stamp"
        assert stamp_status("trip-y")["status"] == "ready"

    _with_temp_dirs(run)


def test_same_visits_are_not_generated_twice():
    def run():
        assert request_stamp("trip-d", ITIN, VISITS) is True
        assert request_stamp("trip-d", ITIN, VISITS) is False
        more = {**VISITS, "3": {"visited": ["f"]}}
        assert request_stamp("trip-d", ITIN, more) is True

    _with_temp_dirs(run)


def test_generate_stamp_skips_api_call_when_nothing_visited_yet():
    def run():
        fake = _FakeClient()
        stamp._client = fake
        generate_stamp("trip-z", ITIN, {})
        assert fake.images.calls == 0

    _with_temp_dirs(run)


def test_generate_stamp_asks_for_a_portrait_image():
    # The recap card is portrait (345x444). A square edit gets cropped so hard
    # under BoxFit.cover that the track drifts away from the native paw stamps.
    def run():
        fake = _FakeClient()
        stamp._client = fake
        generate_stamp("trip-p", ITIN, VISITS)
        assert fake.images.kwargs["size"] == "1024x1536", fake.images.kwargs["size"]

    _with_temp_dirs(run)


def test_checkin_generates_one_stamp_only_when_asked():
    """Every checkbox tap POSTs /trip/checkin; only Complete Check-in asks for a
    stamp, and asking again with the same visits must not pay twice."""
    from fastapi.testclient import TestClient
    import api

    calls = []
    orig = api.generate_stamp, api.save_checkin
    api.generate_stamp = lambda *args: calls.append(args)
    api.save_checkin = lambda *args, **kwargs: True
    try:
        client = TestClient(api.app)
        body = {"trip_id": "trip-gate", "device_id": "dev-gate", "itinerary": ITIN, "days": VISITS}
        assert client.post("/trip/checkin", json=body).status_code == 200
        assert calls == [], "a plain checkbox tap must not start a generation"
        assert client.post("/trip/checkin", json={**body, "generate_stamp": True}).status_code == 200
        assert client.post("/trip/checkin", json={**body, "generate_stamp": True}).status_code == 200
        assert len(calls) == 1, calls
    finally:
        api.generate_stamp, api.save_checkin = orig


def test_stamp_status_endpoint_and_bad_trip_ids():
    from fastapi.testclient import TestClient
    import api

    client = TestClient(api.app)
    assert client.get("/trip/stamp/trip-never-generated").json() == {"status": "none"}
    assert client.get("/trip/stamp/bad.id").status_code == 422
    bad = {"trip_id": "../evil", "device_id": "dev", "itinerary": ITIN, "days": VISITS}
    assert client.post("/trip/checkin", json=bad).status_code == 422


if __name__ == "__main__":
    test_route_groups_visits_by_day_in_plan_order()
    test_route_skips_unvisited_days_and_unplanned_names()
    test_route_is_empty_when_nothing_checked_in()
    test_prompt_numbers_every_place_in_order_under_its_day()
    test_prompt_counts_every_place_and_says_what_kind_it_is()
    test_prompt_asks_for_a_number_and_name_label_by_each_place()
    test_prompt_pins_exactly_one_label_per_number()
    test_track_rows_follow_the_snaking_rail()
    test_english_names_pass_through_without_a_translation_call()
    test_korean_only_names_are_translated_in_one_call()
    test_a_failed_or_korean_translation_falls_back_to_romanization()
    test_prompt_prints_the_english_label_not_the_original_name()
    test_generated_prompt_has_no_korean_at_all()
    test_generate_stamp_sends_place_types_into_the_prompt()
    test_trip_ids_are_checked_before_touching_the_filesystem()
    test_nothing_visited_requests_no_stamp()
    test_generation_reports_generating_then_ready()
    test_failed_generation_without_a_stamp_reports_failed_and_can_retry()
    test_failed_generation_keeps_the_previous_stamp()
    test_same_visits_are_not_generated_twice()
    test_generate_stamp_skips_api_call_when_nothing_visited_yet()
    test_generate_stamp_asks_for_a_portrait_image()
    test_checkin_generates_one_stamp_only_when_asked()
    test_stamp_status_endpoint_and_bad_trip_ids()
    print("stamp: all checks passed")
