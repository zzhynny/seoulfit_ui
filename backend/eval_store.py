"""Itinerary quality log — one row per generation.

CriticAgent already scores every itinerary it produces, twice (before and after
repair). Until now that score was attached to the response and then thrown away,
so there was no way to answer "are we getting better?" or "which inputs produce
bad trips?" other than by feel. This keeps it.

Storage mirrors checkin_store exactly: Postgres in production (Render injects
DATABASE_URL), a local SQLite file otherwise, ANSI-plain SQL so one statement
works on both engines.

The columns are the ones worth grouping by -- `WHERE pace = 'relaxed'`,
`GROUP BY num_days`. Anything not worth a column is still in `report`, which
holds both critic reports whole, so a new question needs no migration.

ponytail: append-only, no retention job. Rows are ~2-10KB, so a year of a
thousand trips a month is tens of MB. Add a purge when that stops being true.
"""
import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_backend_logged = False

_DEFAULT_SQLITE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "evals.db"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS itinerary_evals (
    eval_id      TEXT PRIMARY KEY,
    created_at   TEXT NOT NULL,
    thread_id    TEXT,
    num_days     INTEGER,
    pace         TEXT,
    companion    TEXT,
    purpose      TEXT,
    regions      TEXT,
    interests    TEXT,
    score_before REAL,
    score_after  REAL,
    feasibility  REAL,
    area_score   REAL,
    duplicates   REAL,
    foreigner    REAL,
    repair_count INTEGER,
    issue_count  INTEGER,
    report       TEXT NOT NULL
)
"""

_INSERT = """
INSERT INTO itinerary_evals (
    eval_id, created_at, thread_id, num_days, pace, companion, purpose,
    regions, interests, score_before, score_after, feasibility, area_score,
    duplicates, foreigner, repair_count, issue_count, report
) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
"""

# Worst-first: the failure corpus is the reason this table exists.
_WORST = """
SELECT eval_id, created_at, num_days, pace, purpose, regions, interests,
       score_before, score_after, repair_count, issue_count
FROM itinerary_evals
ORDER BY score_after ASC, created_at DESC
LIMIT {p}
"""


def _connect(db_path: str | None):
    """Return (connection, placeholder) — same rules as checkin_store."""
    global _backend_logged
    url = os.getenv("DATABASE_URL")
    if url and db_path is None:
        if not _backend_logged:
            logger.info("eval_store: using Postgres via DATABASE_URL")
            _backend_logged = True
        import psycopg  # lazy, so dev without the driver still runs
        return psycopg.connect(url), "%s"
    path = db_path or _DEFAULT_SQLITE
    if not _backend_logged:
        logger.info("eval_store: using SQLite at %s", path)
        _backend_logged = True
    return sqlite3.connect(path, timeout=30), "?"


def _f(report: dict, key: str) -> float | None:
    value = report.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def save_eval(
    state: dict,
    itinerary: dict,
    before: dict,
    after: dict,
    repair_logs: list,
    thread_id: str | None = None,
    db_path: str | None = None,
) -> str | None:
    """Record one generation. Returns the eval_id, or None on any failure.

    Never raises. This runs inside critic_repair_node, whose own except clause
    turns anything thrown into a user-facing "Critic-Repair failed" message --
    a logging table must not be able to fail a traveller's itinerary.
    """
    try:
        day_specs = state.get("day_specs") or []
        eval_id = str(uuid.uuid4())
        row = (
            eval_id,
            datetime.now(timezone.utc).isoformat(),
            thread_id,
            # From the itinerary itself, not the travel_dates text: this is what
            # the traveller actually received.
            len(itinerary.get("days") or []),
            state.get("pace"),
            state.get("companion"),
            state.get("purpose"),
            json.dumps([s.get("region") for s in day_specs], ensure_ascii=False),
            # The Day Planner's per-day notes. This column held the per-day
            # interest before notes replaced it; the name stayed so the table
            # needs no migration.
            json.dumps([s.get("note") or "" for s in day_specs], ensure_ascii=False),
            _f(before, "overall_score"),
            _f(after, "overall_score"),
            _f(after, "feasibility_score"),
            _f(after, "requested_area_coverage_score"),
            _f(after, "duplicate_score"),
            _f(after, "foreigner_readiness_score"),
            len(repair_logs or []),
            len(after.get("issues") or []),
            json.dumps({"before": before, "after": after,
                        "repair_log": repair_logs}, ensure_ascii=False),
        )

        conn, ph = _connect(db_path)
        try:
            with conn:
                cur = conn.cursor()
                cur.execute(_SCHEMA)
                cur.execute(_INSERT.format(p=ph), row)
        finally:
            conn.close()
        return eval_id
    except Exception:
        logger.exception("eval_store: save_eval failed")
        return None


def worst(limit: int = 20, db_path: str | None = None) -> list[dict]:
    """The lowest-scoring generations — your failure corpus, newest first
    within a tie. Read by the self-check and by offline analysis."""
    columns = ("eval_id", "created_at", "num_days", "pace", "purpose",
               "regions", "interests", "score_before", "score_after",
               "repair_count", "issue_count")
    try:
        conn, ph = _connect(db_path)
        try:
            cur = conn.cursor()
            cur.execute(_SCHEMA)
            cur.execute(_WORST.format(p=ph), (limit,))
            rows = cur.fetchall()
        finally:
            conn.close()
    except Exception:
        logger.exception("eval_store: worst failed")
        return []
    return [dict(zip(columns, r)) for r in rows]
