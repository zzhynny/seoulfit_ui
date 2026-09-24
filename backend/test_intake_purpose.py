"""인텍스트 슬롯 변경 — region 과 category(관심사)가 빠지고 purpose 가 들어온다."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import graph  # noqa: E402


def test_region_is_no_longer_asked():
    assert "region" not in graph.FIELD_ORDER
    assert "region" not in graph.FIELD_QUESTIONS


def test_interest_is_not_asked_in_chat():
    # The Day Planner asks an interest for every day, so a trip-wide "main
    # interests?" question right after the dates was the same question twice.
    assert "category" not in graph.FIELD_ORDER
    assert "category" not in graph.FIELD_QUESTIONS
    assert "category" not in graph.FIELD_LABELS


def test_purpose_is_asked_last():
    assert graph.FIELD_ORDER[-1] == "purpose"
    assert len(graph.FIELD_ORDER) == 5


def _gemini_says(monkeypatch, payload):
    """Stub the one Gemini seam; returns the prompts it was asked."""
    import json
    prompts = []
    monkeypatch.setattr(graph, "_gemini_raw",
                        lambda prompt: prompts.append(prompt) or json.dumps(payload))
    return prompts


def test_purpose_is_stored_verbatim_not_normalised(monkeypatch):
    _gemini_says(monkeypatch, {"keywords": []})
    out = graph._store("purpose", "travelling with my mother for the first time", {})
    assert out == {"purpose": "travelling with my mother for the first time",
                   "purpose_keywords": []}


def test_skipping_purpose_leaves_it_empty(monkeypatch):
    prompts = _gemini_says(monkeypatch, {"keywords": [{"phrase": "x", "poi_type": "cafe"}]})
    assert graph._store("purpose", "MISSING", {}) == {"purpose": "", "purpose_keywords": []}
    assert graph._store("purpose", "", {}) == {"purpose": "", "purpose_keywords": []}
    assert prompts == [], "an empty purpose must not cost a Gemini call"


def test_named_places_become_at_most_two_typed_keywords(monkeypatch):
    _gemini_says(monkeypatch, {"keywords": [
        {"phrase": "rooftop bars", "poi_type": "tourist_spot"},
        {"phrase": "BTS merch", "poi_type": "kpop_landmark"},
        {"phrase": "hanbok rental", "poi_type": "tourist_spot"},
    ]})
    kws = graph._extract_purpose_keywords("BTS fan, want rooftop bars and hanbok photos")
    # The cap is a cap on Google calls: each keyword is one search per area.
    assert kws == [{"phrase": "rooftop bars", "poi_type": "tourist_spot"},
                   {"phrase": "BTS merch", "poi_type": "kpop_landmark"}], kws


def test_bad_model_output_is_cleaned_not_trusted(monkeypatch):
    _gemini_says(monkeypatch, {"keywords": [
        {"phrase": "coffee roasteries", "poi_type": "bakery"},   # unknown type
        {"phrase": "", "poi_type": "cafe"},                      # empty phrase
        "rooftop bars",                                           # not an object
    ]})
    assert graph._extract_purpose_keywords("coffee trip") == [
        {"phrase": "coffee roasteries", "poi_type": "tourist_spot"}]

    _gemini_says(monkeypatch, {"keywords": "rooftop bars"})
    assert graph._extract_purpose_keywords("coffee trip") == []


def test_a_failed_call_means_no_keywords_not_a_failed_turn(monkeypatch):
    def boom(prompt):
        raise RuntimeError("429 rate limited")
    monkeypatch.setattr(graph, "_gemini_raw", boom)
    assert graph._extract_purpose_keywords("rooftop bars in Seoul") == []


def test_restrictions_carry_the_diet_that_controls_meals():
    assert graph._store("restrictions", "I'm vegetarian", {}) == {
        "restrictions": "I'm vegetarian", "diet": "vegetarian"}
    assert graph._store("restrictions", "nut allergy", {})["diet"] is None
