"""Self-check for closure_check.py. No framework, no live network — the Gemini
call seam (_call_with_timeout) is monkeypatched with fake grounded responses,
following the same pattern as test_gemini_retry.py.

Run: backend/venv/Scripts/python.exe test_closure_check.py
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import closure_check as cc


# ──────────────────────────────────────────
# Fake Gemini response builders
# ──────────────────────────────────────────
def _chunk(uri: str):
    return SimpleNamespace(web=SimpleNamespace(uri=uri))


def _support(start: int, end: int, chunk_indices: list[int]):
    return SimpleNamespace(
        segment=SimpleNamespace(start_index=start, end_index=end),
        grounding_chunk_indices=chunk_indices,
    )


def _response(text: str, supports=None, chunks=None):
    grounding_metadata = SimpleNamespace(
        grounding_supports=supports or [],
        grounding_chunks=chunks or [],
    )
    candidate = SimpleNamespace(grounding_metadata=grounding_metadata)
    return SimpleNamespace(text=text, candidates=[candidate])


# ──────────────────────────────────────────
# Tests
# ──────────────────────────────────────────
def test_confirmed_with_matching_grounding_span():
    body1 = '{"status": "confirmed_closed", "source_note": "Closed every Tuesday."}'
    body2 = '{"status": "unknown", "source_note": ""}'
    text = f"###ITEM1### {body1}\n###ITEM2### {body2}"
    start1 = text.index(body1)
    end1 = start1 + len(body1)
    resp = _response(
        text,
        supports=[_support(start1, end1, [0])],
        chunks=[_chunk("https://example.com/gyeongbokgung-hours")],
    )
    items = [
        ("Gyeongbokgung Palace", "Seoul", "2026-09-01"),
        ("Some Cafe", "Seoul", "2026-09-01"),
    ]
    results = cc._parse_and_validate_batch(resp, items)
    assert results[0]["status"] == "confirmed_closed"
    assert results[0]["source_url"] == "https://example.com/gyeongbokgung-hours"
    assert results[1]["status"] == "unknown"
    assert results[1]["source_url"] is None


def test_start_index_none_means_zero_not_missing():
    """Regression: Gemini omits segment.start_index (leaves it None) when a
    segment starts at position 0 — this must NOT be treated as 'no position
    info' and skipped. Caught via a live API call where item 1's grounding
    segment had start_index=None, end_index=157."""
    body = '{"status": "confirmed_closed", "source_note": "Closed on Tuesdays."}'
    text = f"###ITEM1### {body}"
    end_of_body = text.index(body) + len(body)
    resp = _response(
        text,
        supports=[_support(0, end_of_body, [0])],  # emulate start_index=None -> our _support always sets int, so...
        chunks=[_chunk("https://example.com/hours")],
    )
    # Directly emulate the None case the SDK actually returns:
    resp.candidates[0].grounding_metadata.grounding_supports[0].segment.start_index = None
    items = [("Gyeongbokgung Palace", "Seoul", "2026-09-01")]
    results = cc._parse_and_validate_batch(resp, items)
    assert results[0]["status"] == "confirmed_closed", \
        "start_index=None (meaning 0) must still count as valid grounding overlap"
    assert results[0]["source_url"] == "https://example.com/hours"


def test_retry_recovers_when_first_response_has_empty_chunks():
    """First live call comes back with empty grounding_chunks (the observed
    API flakiness) but a claimed confirmed_closed; the retry call comes back
    with real chunks. Final result must use the retry's grounding, not give up
    after the first empty one."""
    body = '{"status": "confirmed_closed", "source_note": "Closed on Tuesdays."}'
    empty_grounding_resp = _response(f"###ITEM1### {body}", supports=[], chunks=[])

    start = f"###ITEM1### {body}".index(body)
    end = start + len(body)
    good_resp = _response(
        f"###ITEM1### {body}",
        supports=[_support(start, end, [0])],
        chunks=[_chunk("https://example.com/hours")],
    )

    calls = {"n": 0}

    def fake_call(items, timeout):
        calls["n"] += 1
        return empty_grounding_resp if calls["n"] == 1 else good_resp

    orig = cc._call_with_timeout
    cc._call_with_timeout = fake_call
    try:
        response = cc._call_with_retry_on_empty_grounding(
            [("Gyeongbokgung Palace", "Seoul", "2026-09-01")], 10.0
        )
        assert calls["n"] == 2, "must retry exactly once when first response has empty chunks"
        results = cc._parse_and_validate_batch(response, [("Gyeongbokgung Palace", "Seoul", "2026-09-01")])
        assert results[0]["status"] == "confirmed_closed"
        assert results[0]["source_url"] == "https://example.com/hours"
    finally:
        cc._call_with_timeout = orig


def test_retry_stops_after_one_attempt_and_validation_stays_strict():
    """Both the original call and the retry come back with empty chunks.
    Must call exactly twice (not loop forever), and the validation rule must
    still force a claimed confirmed_open down to unknown — retrying for API
    flakiness must never weaken the 'no evidence -> unknown' guarantee."""
    body = '{"status": "confirmed_open", "source_note": "Open today."}'
    always_empty = _response(f"###ITEM1### {body}", supports=[], chunks=[])

    calls = {"n": 0}

    def fake_call(items, timeout):
        calls["n"] += 1
        return always_empty

    orig = cc._call_with_timeout
    cc._call_with_timeout = fake_call
    try:
        response = cc._call_with_retry_on_empty_grounding(
            [("Ghost Place", "Nowhere", "2026-09-01")], 10.0
        )
        assert calls["n"] == 2, "exactly one retry (2 total calls), no more"
        results = cc._parse_and_validate_batch(response, [("Ghost Place", "Nowhere", "2026-09-01")])
        assert results[0]["status"] == "unknown", \
            "validation must still force unknown after retry exhausted — never relaxed"
    finally:
        cc._call_with_timeout = orig


def test_no_retry_when_first_response_already_grounded():
    """If the first call already has grounding chunks, don't waste a second
    call — retry is only for the empty-chunks flakiness case."""
    body = '{"status": "confirmed_closed", "source_note": "Closed."}'
    text = f"###ITEM1### {body}"
    start, end = text.index(body), text.index(body) + len(body)
    good_resp = _response(text, supports=[_support(start, end, [0])], chunks=[_chunk("https://x")])

    calls = {"n": 0}

    def fake_call(items, timeout):
        calls["n"] += 1
        return good_resp

    orig = cc._call_with_timeout
    cc._call_with_timeout = fake_call
    try:
        cc._call_with_retry_on_empty_grounding([("A", "addr", "2026-09-01")], 10.0)
        assert calls["n"] == 1, "must not retry when the first response already has grounding"
    finally:
        cc._call_with_timeout = orig


def test_confirmed_without_grounding_is_downgraded():
    """Model claims confirmed_* but no grounding chunk actually backs that span
    -> must be forced to unknown (the core validation rule)."""
    body = '{"status": "confirmed_open", "source_note": "It is open today."}'
    text = f"###ITEM1### {body}"
    resp = _response(text, supports=[], chunks=[])  # no grounding at all
    items = [("Ghost Palace", "Nowhere", "2099-01-01")]
    results = cc._parse_and_validate_batch(resp, items)
    assert results[0]["status"] == "unknown", "no grounding evidence must force unknown"
    assert results[0]["source_url"] is None
    assert results[0]["source_note"] == ""


def test_malformed_item_does_not_affect_others():
    body_bad = '{"status": "confirmed_closed", '  # truncated / invalid JSON
    body_good = '{"status": "unknown", "source_note": ""}'
    text = f"###ITEM1### {body_bad}\n###ITEM2### {body_good}"
    resp = _response(text)
    items = [("A", "addr", "2026-09-01"), ("B", "addr", "2026-09-01")]
    results = cc._parse_and_validate_batch(resp, items)
    assert results[0]["status"] == "unknown", "malformed item must fall back to unknown"
    assert results[1]["status"] == "unknown"


def test_out_of_enum_status_forced_unknown():
    body = '{"status": "probably_closed", "source_note": "guessing"}'
    text = f"###ITEM1### {body}"
    resp = _response(text)
    items = [("A", "addr", "2026-09-01")]
    results = cc._parse_and_validate_batch(resp, items)
    assert results[0]["status"] == "unknown", "schema-violating status must be forced unknown"


def test_cache_roundtrip_and_ttl_expiry():
    key = cc._cache_key("Test POI", "Test Address", "2026-09-01")
    cc._CACHE.pop(key, None)
    assert cc._cache_get(key) is None

    result = {"poi_name": "Test POI", "visit_date": "2026-09-01", "status": "confirmed_closed",
              "source_url": "https://x", "source_note": "n", "checked_at": "now"}
    cc._cache_put(key, result)
    cached = cc._cache_get(key)
    assert cached is not None and cached["status"] == "confirmed_closed"

    # force-expire and confirm it's gone
    expires_at, stored = cc._CACHE[key]
    cc._CACHE[key] = (time.time() - 1, stored)
    assert cc._cache_get(key) is None, "expired entry must not be returned"


def test_check_batch_uses_cache_without_calling_api():
    calls = {"n": 0}

    def fake_call(items, timeout):
        calls["n"] += 1
        raise AssertionError("should not be called — cache should have served this")

    orig = cc._call_with_timeout
    cc._call_with_timeout = fake_call
    try:
        key = cc._cache_key("Cached Place", "Addr", "2026-09-01")
        cc._cache_put(key, {"poi_name": "Cached Place", "visit_date": "2026-09-01",
                             "status": "confirmed_open", "source_url": "https://y",
                             "source_note": "n", "checked_at": "now"})
        out = cc.check_batch([("Cached Place", "Addr", "2026-09-01")])
        assert out[0]["status"] == "confirmed_open"
        assert calls["n"] == 0, "cached item must not trigger an API call"
    finally:
        cc._call_with_timeout = orig


def test_check_batch_api_failure_falls_back_to_unknown_never_raises():
    def boom(items, timeout):
        raise RuntimeError("simulated network failure")

    orig = cc._call_with_timeout
    cc._call_with_timeout = boom
    try:
        items = [(f"Uncached Place {i}", "Addr", "2026-09-01") for i in range(3)]
        out = cc.check_batch(items)  # must not raise
        assert len(out) == 3
        assert all(r["status"] == "unknown" for r in out)
    finally:
        cc._call_with_timeout = orig


def test_check_batch_preserves_input_order_across_batches():
    def fake_call(items, timeout):
        text = "\n".join(
            f'###ITEM{i+1}### {{"status": "unknown", "source_note": ""}}'
            for i in range(len(items))
        )
        return _response(text)

    orig = cc._call_with_timeout
    cc._call_with_timeout = fake_call
    try:
        # more than one batch_size worth, to exercise chunking + reassembly order
        items = [(f"Place {i}", "Addr", "2026-09-01") for i in range(10)]
        out = cc.check_batch(items, batch_size=3)
        assert [r["poi_name"] for r in out] == [f"Place {i}" for i in range(10)]
    finally:
        cc._call_with_timeout = orig


def main():
    tests = [
        test_confirmed_with_matching_grounding_span,
        test_start_index_none_means_zero_not_missing,
        test_retry_recovers_when_first_response_has_empty_chunks,
        test_retry_stops_after_one_attempt_and_validation_stays_strict,
        test_no_retry_when_first_response_already_grounded,
        test_confirmed_without_grounding_is_downgraded,
        test_malformed_item_does_not_affect_others,
        test_out_of_enum_status_forced_unknown,
        test_cache_roundtrip_and_ttl_expiry,
        test_check_batch_uses_cache_without_calling_api,
        test_check_batch_api_failure_falls_back_to_unknown_never_raises,
        test_check_batch_preserves_input_order_across_batches,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
