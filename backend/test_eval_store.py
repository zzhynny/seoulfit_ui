"""Every generation banks its critic score, and logging can never break one.

CriticAgent scores each itinerary twice (before and after repair) and that number
used to die with the response. These tests pin the two things that make the table
worth having: the scores land in columns you can GROUP BY, and a storage outage
degrades to a missing row rather than a failed trip.

Runs against a temp SQLite file so it needs no DATABASE_URL and no network.

Run:  backend/venv/bin/python backend/test_eval_store.py
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import eval_store  # noqa: E402

STATE = {
    "pace": "relaxed",
    "companion": "family",
    "purpose": "first time with my parents",
    "day_specs": [
        {"day": 1, "region": "jongno", "interest": "Culture & History"},
        {"day": 2, "region": "hongdae", "interest": "Food & Cafes"},
    ],
}
ITINERARY = {"days": [{"day": 1}, {"day": 2}]}
BEFORE = {"overall_score": 0.61, "issues": [{"code": "MISSING_AREA"}]}
AFTER = {
    "overall_score": 0.88,
    "feasibility_score": 0.9,
    "requested_area_coverage_score": 1.0,
    "duplicate_score": 0.8,
    "foreigner_readiness_score": 0.7,
    "issues": [],
}


def _db() -> str:
    return os.path.join(tempfile.mkdtemp(), "evals.db")


def test_scores_land_in_queryable_columns() -> None:
    """The point of columns over a JSON blob: this query must work on both engines."""
    db = _db()
    eval_store.save_eval(STATE, ITINERARY, BEFORE, AFTER, ["swapped X for Y"],
                         thread_id="thread-1", db_path=db)

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT num_days, pace, companion, score_before, score_after, "
        "feasibility, area_score, duplicates, foreigner, repair_count, "
        "issue_count, thread_id FROM itinerary_evals"
    ).fetchone()
    conn.close()

    assert row == (2, "relaxed", "family", 0.61, 0.88,
                   0.9, 1.0, 0.8, 0.7, 1, 0, "thread-1"), row


def test_day_specs_are_stored_for_slicing() -> None:
    """'Is Seongsu weaker than Jongno?' has to be answerable without a migration."""
    db = _db()
    eval_store.save_eval(STATE, ITINERARY, BEFORE, AFTER, [], db_path=db)

    conn = sqlite3.connect(db)
    regions, interests = conn.execute(
        "SELECT regions, interests FROM itinerary_evals"
    ).fetchone()
    conn.close()

    assert '"jongno"' in regions and '"hongdae"' in regions, regions
    assert "Food & Cafes" in interests, interests


def test_full_reports_survive_for_questions_not_yet_asked() -> None:
    db = _db()
    eval_store.save_eval(STATE, ITINERARY, BEFORE, AFTER, ["log line"], db_path=db)

    conn = sqlite3.connect(db)
    report = conn.execute("SELECT report FROM itinerary_evals").fetchone()[0]
    conn.close()

    assert "MISSING_AREA" in report, "before-repair issues must be recoverable"
    assert "log line" in report


def test_worst_returns_the_failure_corpus_lowest_first() -> None:
    db = _db()
    for score in (0.9, 0.3, 0.6):
        eval_store.save_eval(STATE, ITINERARY, BEFORE,
                             {**AFTER, "overall_score": score}, [], db_path=db)

    rows = eval_store.worst(limit=2, db_path=db)
    assert [r["score_after"] for r in rows] == [0.3, 0.6], rows


def test_a_broken_store_never_fails_a_generation() -> None:
    """A directory where the DB file should be — open() cannot succeed."""
    bad = tempfile.mkdtemp()          # a directory, not a file path
    assert eval_store.save_eval(STATE, ITINERARY, BEFORE, AFTER, [], db_path=bad) is None
    assert eval_store.worst(db_path=bad) == []


def test_missing_scores_become_null_not_a_crash() -> None:
    """An older or partial report must still produce a row."""
    db = _db()
    assert eval_store.save_eval(STATE, ITINERARY, {}, {}, [], db_path=db) is not None

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT score_before, score_after, issue_count FROM itinerary_evals"
    ).fetchone()
    conn.close()
    assert row == (None, None, 0), row


def test_node_logs_without_a_thread_id() -> None:
    """LangGraph injects config; a direct call has none and must still work."""
    db = _db()
    assert eval_store.save_eval(STATE, ITINERARY, BEFORE, AFTER, [], db_path=db)

    conn = sqlite3.connect(db)
    assert conn.execute(
        "SELECT thread_id FROM itinerary_evals"
    ).fetchone()[0] is None
    conn.close()


if __name__ == "__main__":
    test_scores_land_in_queryable_columns()
    test_day_specs_are_stored_for_slicing()
    test_full_reports_survive_for_questions_not_yet_asked()
    test_worst_returns_the_failure_corpus_lowest_first()
    test_a_broken_store_never_fails_a_generation()
    test_missing_scores_become_null_not_a_crash()
    test_node_logs_without_a_thread_id()
    print("all eval store self-checks passed")
