"""TDD self-checks for the remaining retrieval fixes. No framework, no live network.

  1. geo: Yongsan is a recognized area (alias + center).
  2. planner.build_google_supplement_for_area: an off-category purpose (K-beauty)
     now pulls purpose-matching POIs via a generic text search (network seams
     monkeypatched — the one unavoidable mock).

rag.segment_k and rag.rerank_courses_by_area were deleted in the retrieval
redesign (Task 6) -- their job (breadth-by-day-count, area-based re-rank of
vector-search hits) is superseded by retrieval.select_anchors's hard region
filter (retrieval.filter_pool / retrieval._in_region), so the tests that
covered them were removed rather than ported.

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
