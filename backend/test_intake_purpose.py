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


def test_purpose_is_stored_verbatim_not_normalised():
    out = graph._store("purpose", "travelling with my mother for the first time", {})
    assert out == {"purpose": "travelling with my mother for the first time"}


def test_skipping_purpose_leaves_it_empty():
    assert graph._store("purpose", "MISSING", {}) == {"purpose": ""}
    assert graph._store("purpose", "", {}) == {"purpose": ""}
