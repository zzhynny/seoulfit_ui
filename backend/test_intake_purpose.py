"""인텍스트 슬롯 변경 — region 이 빠지고 purpose 가 들어온다."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import graph  # noqa: E402


def test_region_is_no_longer_asked():
    assert "region" not in graph.FIELD_ORDER
    assert "region" not in graph.FIELD_QUESTIONS


def test_purpose_is_asked_last():
    assert graph.FIELD_ORDER[-1] == "purpose"
    assert len(graph.FIELD_ORDER) == 6


def test_purpose_is_stored_verbatim_not_normalised():
    out = graph._store("purpose", "travelling with my mother for the first time", {})
    assert out == {"purpose": "travelling with my mother for the first time"}


def test_skipping_purpose_leaves_it_empty():
    assert graph._store("purpose", "MISSING", {}) == {"purpose": ""}
    assert graph._store("purpose", "", {}) == {"purpose": ""}


def test_category_passes_through_when_already_in_vocabulary():
    out = graph._store("category", "Shopping", {})
    assert out == {"category": "Shopping"}


def test_category_multi_value_extraction_takes_the_first_valid_label():
    """'What are your main interests?' is plural, so the LLM extraction can
    reasonably return more than one label. Every downstream consumer (the
    day_specs interest dropdown in Flutter, retrieval.select_anchors'
    interest filter) expects exactly one of graph.INTEREST_LABELS -- an
    off-vocabulary multi-value string would otherwise trip the Flutter
    dropdown's assertion and silently relax select_anchors to
    interest-free for every day."""
    out = graph._store("category", "Shopping, Food & Cafes", {})
    assert out == {"category": "Shopping"}


def test_category_garbage_extraction_falls_back_to_the_default():
    out = graph._store("category", "sightseeing and vibes", {})
    assert out == {"category": graph.DEFAULT_INTEREST}


def test_category_garbage_first_element_also_falls_back():
    # First comma-separated element is itself off-vocabulary -- taking a
    # bad first element would be worse than the shared default.
    out = graph._store("category", "sightseeing, Shopping", {})
    assert out == {"category": graph.DEFAULT_INTEREST}
