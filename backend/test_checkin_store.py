"""Self-check for checkin_store: round-trip, upsert, and failure isolation.

Runs against a temp SQLite file so it needs no DATABASE_URL and no network.
The same SQL runs against Postgres in production — the only difference is the
parameter placeholder, which _connect() supplies.

Run:  backend/venv/bin/python backend/test_checkin_store.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from checkin_store import save_checkin, load_checkin  # noqa: E402

ITIN = {"planned": {"1": ["Gyeongbokgung", "Tosokchon"]}, "feasibility_score": 0.92}
DAYS = {"1": {"visited": ["Gyeongbokgung"], "misses": {"Tosokchon": "time"}}}


def test_round_trip(db):
    assert save_checkin("trip-a", "dev-1", ITIN, DAYS, db_path=db) is True
    row = load_checkin("trip-a", db_path=db)
    assert row is not None, "saved row should load back"
    assert row["device_id"] == "dev-1"
    assert row["itinerary"] == ITIN, row["itinerary"]
    assert row["days"] == DAYS, row["days"]
    assert row["updated_at"]


def test_upsert_replaces_not_duplicates(db):
    save_checkin("trip-b", "dev-1", ITIN, {"1": {"visited": [], "misses": {}}}, db_path=db)
    save_checkin("trip-b", "dev-1", ITIN, DAYS, db_path=db)
    row = load_checkin("trip-b", db_path=db)
    assert row["days"] == DAYS, "second save must overwrite the first"


def test_missing_trip_is_none(db):
    assert load_checkin("trip-nope", db_path=db) is None


def test_unicode_survives(db):
    days = {"1": {"visited": ["경복궁"], "misses": {"토속촌": "stamina"}}}
    save_checkin("trip-c", "dev-1", ITIN, days, db_path=db)
    assert load_checkin("trip-c", db_path=db)["days"] == days


def test_other_device_cannot_overwrite(db):
    """trip_id comes from an unauthenticated client, so a second device
    reusing someone's trip_id must be refused, not silently applied."""
    assert save_checkin("trip-e", "dev-1", ITIN, DAYS, db_path=db) is True
    hijack = {"1": {"visited": ["ATTACKER"], "misses": {}}}
    assert save_checkin("trip-e", "dev-2", ITIN, hijack, db_path=db) is False
    row = load_checkin("trip-e", db_path=db)
    assert row["device_id"] == "dev-1", "owner must not change"
    assert row["days"] == DAYS, "attacker payload must not be stored"
    # The real owner can still update its own row.
    assert save_checkin("trip-e", "dev-1", ITIN, hijack, db_path=db) is True
    assert load_checkin("trip-e", db_path=db)["days"] == hijack


def test_bad_path_returns_false_not_raises():
    ok = save_checkin("trip-d", "dev-1", ITIN, DAYS, db_path="/nonexistent-dir/x.db")
    assert ok is False, "storage failure must be reported, not raised"


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "test.db")
        test_round_trip(db)
        test_upsert_replaces_not_duplicates(db)
        test_missing_trip_is_none(db)
        test_unicode_survives(db)
        test_other_device_cannot_overwrite(db)
        test_bad_path_returns_false_not_raises()
    print("checkin_store: all checks passed")
