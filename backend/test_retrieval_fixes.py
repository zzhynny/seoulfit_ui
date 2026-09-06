"""TDD self-checks for the three retrieval fixes. No framework, no live network.

  1. geo: Yongsan is a recognized area (alias + center).
  2. rag.segment_k: retrieval breadth scales with a segment's day count.
  3. rag.rerank_courses_by_area: courses whose POIs sit in the requested area
     are ordered first, stably.
  4. planner.build_google_supplement_for_area: an off-category purpose (K-beauty)
     now pulls purpose-matching POIs via a generic text search (network seams
     monkeypatched — the one unavoidable mock).

Run: backend/venv/bin/python test_retrieval_fixes.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import geo  # noqa: E402


def test_yongsan_recognized():
    assert "yongsan" in geo.extract_requested_areas("Hongdae, Itaewon, and Yongsan"), \
        "Yongsan should be extracted from a request string"
    assert geo.infer_area(text="서울특별시 용산구 한강대로 405") == "yongsan", \
        "a Yongsan-gu address should infer the 'yongsan' area"
    assert geo.area_matches_requested("itaewon", "yongsan"), \
        "Itaewon (in Yongsan-gu) should satisfy a Yongsan request"


def test_segment_k_scales_with_days():
    import rag
    assert rag.segment_k(1) == 2, "1-day segment -> k=2 (day+1, floor 2)"
    assert rag.segment_k(4) == 5, "4-day segment -> k=5"
    assert rag.segment_k(5) == 6, "5-day segment -> k=6"
    assert rag.segment_k(10) == 6, "long segment clamps at k=6"
    assert rag.segment_k(0) == 2, "0/None-day segment floors at k=2"


def _course(cid, area_poi):
    """A course whose single POI lives at the given (name/address/lat/lng)."""
    return {"course_id": cid, "sequence": [area_poi]}


def test_area_rerank_orders_matching_first():
    import rag
    seongsu_poi = {"poi_name": "Seongsu Cafe", "address_en": "Seongdong-gu, Seoul",
                   "lat": 37.5447, "lng": 127.0558}
    gangnam_poi = {"poi_name": "Gangnam Store", "address_en": "Gangnam-gu, Seoul",
                   "lat": 37.4979, "lng": 127.0276}
    off = _course("OFF", gangnam_poi)
    hit = _course("HIT", seongsu_poi)

    ranked = rag.rerank_courses_by_area([off, hit], "seongsu")
    assert [c["course_id"] for c in ranked] == ["HIT", "OFF"], \
        "in-area course must come first"

    # stability: two in-area courses keep their original relative order
    hit2 = _course("HIT2", seongsu_poi)
    ranked2 = rag.rerank_courses_by_area([hit, hit2], "seongsu")
    assert [c["course_id"] for c in ranked2] == ["HIT", "HIT2"], \
        "equal (both in-area) courses keep input order"


def test_generic_supplement_for_offcategory_purpose():
    import planner
    orig_nearby, orig_text = planner.fetch_nearby_places, planner.fetch_text_places
    BEAUTY = {"poi_name": "Olive Young Seongsu", "poi_type": "tourist_spot",
              "lat": 37.5447, "lng": 127.0558, "source": "Google Places Text"}

    def fake_nearby(*, place_type, **kw):
        if place_type == "restaurant":
            return [{"poi_name": f"Rest {i}", "poi_type": "restaurant",
                     "lat": 37.54, "lng": 127.05} for i in range(3)]
        return []

    def fake_text(*, query, **kw):
        return [dict(BEAUTY)] if "k-beauty" in query.lower() else []

    planner.fetch_nearby_places = fake_nearby
    planner.fetch_text_places = fake_text
    try:
        out = planner.build_google_supplement_for_area(
            area="seongsu", purpose="K-beauty and skincare", api_key="x")
    finally:
        planner.fetch_nearby_places, planner.fetch_text_places = orig_nearby, orig_text

    names = {p.get("poi_name") for p in out}
    assert "Olive Young Seongsu" in names, \
        "off-category purpose should pull a purpose-matching POI via generic text search"


def main():
    tests = [
        test_yongsan_recognized,
        test_segment_k_scales_with_days,
        test_area_rerank_orders_matching_first,
        test_generic_supplement_for_offcategory_purpose,
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
