"""retrieve_node — day_specs 로 하루씩 앵커를 고른다. 임베딩 없이."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import json

import pytest

import planner


@pytest.fixture(autouse=True)
def no_judge(monkeypatch):
    """No live Gemini: the judge's call fails, so every day keeps its anchors.
    Tests of the judge itself override this."""
    def fail(prompt):
        raise RuntimeError("no network in tests")
    monkeypatch.setattr(planner, "_gemini_text", fail)


BASE = {
    "travel_dates": "June 1, 2026 to June 3, 2026 (3 days)",
    "companion": "family", "pace": "relaxed", "restrictions": "none",
    "purpose": "",
    "day_specs": [
        {"day": 1, "region": "jongno", "note": ""},
        {"day": 2, "region": "hongdae", "note": ""},
        {"day": 3, "region": "seongsu", "note": ""},
    ],
}


def test_each_day_gets_its_own_segment_with_anchors():
    node = planner.make_retrieve_node("")
    out = node(dict(BASE))
    segs = out["day_segments"]
    assert [s["day_numbers"] for s in segs] == [[1], [2], [3]]
    assert all(len(s["anchor_courses"]) == 3 for s in segs)
    assert out["current_step"] == "planning"


def test_anchors_respect_the_region_of_that_day():
    from retrieval import _in_region
    node = planner.make_retrieve_node("")
    segs = node(dict(BASE))["day_segments"]
    for seg, want in zip(segs, ["jongno", "hongdae", "seongsu"]):
        assert all(_in_region(c, want) for c in seg["anchor_courses"])


def test_days_do_not_share_a_base_course():
    from retrieval import base_id
    node = planner.make_retrieve_node("")
    segs = node(dict(BASE))["day_segments"]
    per_day = [{base_id(c["course_id"]) for c in s["anchor_courses"]} for s in segs]
    assert not (per_day[0] & per_day[1])


def test_synthesises_a_purpose_when_the_traveller_skipped_it():
    text = planner._synth_purpose(BASE)
    assert "relaxed" in text and "family" in text


def test_uses_the_traveller_sentence_when_they_wrote_one():
    assert planner._synth_purpose({**BASE, "purpose": "my mother's first trip"}) == \
        "my mother's first trip"


def test_each_day_is_searched_with_the_trip_purpose_plus_its_own_note(monkeypatch):
    """One batched embedding of the distinct day queries; a day without a note
    reuses the trip query, and the note reaches its segment."""
    import numpy as np

    import retrieval

    ids = [c["course_id"] for c in retrieval.load_courses()]
    monkeypatch.setattr(planner, "load_vectors", lambda: (ids, np.eye(len(ids), 4, dtype="float32")))
    calls, seen = [], []
    monkeypatch.setattr(planner, "_embed_texts",
                        lambda texts: calls.append(list(texts)) or [np.ones(4, "float32")] * len(texts))
    orig = planner.select_anchors
    monkeypatch.setattr(planner, "select_anchors",
                        lambda spec, **k: seen.append(spec["purpose_vec"] is not None) or orig(spec, **k))

    state = {**BASE, "purpose": "first trip with my mom", "day_specs": [
        {"day": 1, "region": "jongno", "note": "rent hanbok"},
        {"day": 2, "region": "hongdae", "note": ""},
        {"day": 3, "region": "seongsu", "note": ""},
    ]}
    segs = planner.make_retrieve_node("")(state)["day_segments"]

    assert calls == [["first trip with my mom rent hanbok", "first trip with my mom"]]
    assert seen == [True, True, True]
    assert [s["note"] for s in segs] == ["rent hanbok", "", ""]


def _judged(monkeypatch, answer):
    """Run retrieve_node with the judge answering `answer(segments)`."""
    def fake(prompt):
        return json.dumps({"days": answer(fake.segs)})
    orig = planner.judge_anchors
    def spy(segments, queries):
        fake.segs = segments
        return orig(segments, queries)
    monkeypatch.setattr(planner, "_gemini_text", fake)
    monkeypatch.setattr(planner, "judge_anchors", spy)
    return planner.make_retrieve_node("")(dict(BASE))


def test_judge_keeps_only_the_chosen_course(monkeypatch):
    out = _judged(monkeypatch, lambda segs: [
        {"day": s["day_numbers"][0], "course_id": s["anchor_courses"][1]["course_id"]} for s in segs])
    assert all(len(s["anchor_courses"]) == 1 for s in out["day_segments"])
    # Turned-down courses leave the pool too, or the validator's min-stop fill
    # reaches for them before Google Places.
    assert len(out["retrieved_courses"]) == 3


def test_judge_null_leaves_the_day_without_an_anchor(monkeypatch):
    out = _judged(monkeypatch, lambda segs: [
        {"day": s["day_numbers"][0], "course_id": None} for s in segs])
    assert all(s["anchor_courses"] == [] for s in out["day_segments"])
    assert out["retrieved_courses"] == []
    assert out["current_step"] == "planning"
    # No trip keywords and the judge suggested no search: the day still gets
    # one, or Google Places isn't asked and the day has no candidates at all.
    assert all(s["keywords"] == [{"phrase": "things to do", "poi_type": "tourist_spot"}]
               for s in out["day_segments"])


def test_a_day_without_a_course_searches_what_the_judge_suggests(monkeypatch):
    out = _judged(monkeypatch, lambda segs: [
        {"day": 1, "course_id": None, "search": [
            {"phrase": "quiet cafes", "poi_type": "cafe"},
            {"phrase": "Michelin dinner", "poi_type": "restaurant"},   # not allowed
        ]},
        {"day": 2, "course_id": segs[1]["anchor_courses"][0]["course_id"]},
    ])
    d1, d2 = out["day_segments"][0], out["day_segments"][1]
    assert d1["keywords"] == [{"phrase": "quiet cafes", "poi_type": "cafe"}]
    assert d2["keywords"] == []           # the judge suggested none for it


def test_a_day_with_a_course_also_searches_what_the_judge_suggests(monkeypatch):
    """One course rarely fills a day, and Google Places only searches with a
    keyword -- without one the day's only fill was the course's own stops."""
    out = _judged(monkeypatch, lambda segs: [
        {"day": 1, "course_id": segs[0]["anchor_courses"][0]["course_id"],
         "search": [{"phrase": "hanbok rental", "poi_type": "shopping"}]},
    ])
    d1 = out["day_segments"][0]
    assert len(d1["anchor_courses"]) == 1
    assert d1["keywords"] == [{"phrase": "hanbok rental", "poi_type": "shopping"}]


def test_names_differing_only_in_spacing_are_one_place():
    assert planner._normalize_text("IFC Mall (IFC몰)") == planner._normalize_text("IFC Mall (IFC 몰)")


def test_an_answer_without_course_id_is_no_verdict(monkeypatch):
    """Leaving the key out isn't choosing null: the day keeps its anchors."""
    out = _judged(monkeypatch, lambda segs: [
        {"day": s["day_numbers"][0], "search": [], "reason": "?"} for s in segs])
    assert all(len(s["anchor_courses"]) == 3 for s in out["day_segments"])


def test_a_rejected_days_courses_are_kept_aside_for_plan_node(monkeypatch):
    """plan_node restores them if nothing else can fill the day."""
    out = _judged(monkeypatch, lambda segs: [
        {"day": s["day_numbers"][0], "course_id": None} for s in segs])
    assert all(len(s["rejected_courses"]) == 3 for s in out["day_segments"])


def test_a_course_that_was_not_offered_keeps_that_days_anchors(monkeypatch):
    out = _judged(monkeypatch, lambda segs: [
        {"day": 1, "course_id": "MADE_UP"},
        {"day": 2, "course_id": None},
    ])   # day 3 missing from the answer
    assert [len(s["anchor_courses"]) for s in out["day_segments"]] == [3, 0, 3]
