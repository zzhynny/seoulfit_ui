"""retrieve_node — day_specs 로 하루씩 앵커를 고른다. 임베딩 없이."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import planner  # noqa: E402


BASE = {
    "travel_dates": "June 1, 2026 to June 3, 2026 (3 days)",
    "category": "Culture & History",
    "companion": "family", "pace": "relaxed", "restrictions": "none",
    "purpose": "",
    "day_specs": [
        {"day": 1, "region": "jongno", "interest": "Culture & History"},
        {"day": 2, "region": "hongdae", "interest": "Shopping"},
        {"day": 3, "region": "seongsu", "interest": "Food & Cafes"},
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
    assert "relaxed" in text and "family" in text and "Culture & History" in text


def test_uses_the_traveller_sentence_when_they_wrote_one():
    assert planner._synth_purpose({**BASE, "purpose": "my mother's first trip"}) == \
        "my mother's first trip"
