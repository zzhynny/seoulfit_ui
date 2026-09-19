"""/poi-summary · /poi-detail · /poi-image 자체 점검 — 한국관광공사 TourAPI 경로.

    backend/venv/bin/python -m pytest backend/test_poi_tourapi.py

네트워크를 타지 않는다. tourapi.items 를 갈아끼운다.

이 경로는 '있으면 공사 것, 없으면 기존 것' 이라 조용히 틀리기 쉽다.
  - 이름 정규화가 어긋나면 431건이 통째로 miss 가 되고, 아무도 모르는 채
    Tavily 요금만 계속 나간다.
  - 공사 API 가 죽었을 때 예외가 올라가면 상세 시트가 통째로 500 이 된다.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import api  # noqa: E402
from api import PoiSummaryRequest as R  # noqa: E402

KNOWN = "Gyeongbokgung Palace"  # tour_poi.json 431건 안에 있다


class _FakeRequest:
    base_url = "http://localhost:8000/"


def _with_common(row, calls=None):
    def fake(op, **params):
        if calls is not None:
            calls.append(op)
        return ([row] if row else []), 1
    return fake


def _swap(fn):
    real, api.tourapi.items = api.tourapi.items, fn
    api._COMMON_CACHE.clear()
    return real


def test_the_name_index_actually_matches_app_names():
    """앱이 보내는 영문 이름이 공사 제목 색인에 붙어야 한다.

    붙지 않으면 기능은 멀쩡해 보이고(폴백이 받으니까) 공사 API 는 한 번도
    안 불린다 — 이번 작업이 통째로 무효가 되는 실패 방식이다.
    """
    assert len(api._POI_SNAP) > 400, "색인이 비었다"
    assert api._norm_poi_name(KNOWN) in api._POI_SNAP

    # 공사 제목의 한글 괄호·대소문자·기호가 정규화로 흡수돼야 한다.
    assert api._norm_poi_name("Gyeongbokgung Palace (경복궁)") == api._norm_poi_name(KNOWN)
    assert api._norm_poi_name("gyeongbokgung  palace") == api._norm_poi_name(KNOWN)


def test_summary_prefers_the_official_overview():
    real = _swap(_with_common({"contentid": "1", "overview":
                               "First sentence here. Second one. Third one."}))
    try:
        out = api.poi_summary(R(name=KNOWN, type="palace"))["summary"]
        assert out == "First sentence here. Second one.", "앞 두 문장만 쓴다"
    finally:
        api.tourapi.items = real


def test_detail_uses_official_hours_not_the_llm():
    real = _swap(_with_common({"contentid": "1", "overview": "An old palace."}))
    try:
        out = api.poi_detail(R(name=KNOWN, type="palace"))["detail"]
        snap = api._POI_SNAP[api._norm_poi_name(KNOWN)]
        assert out.startswith("• Hours:"), out[:60]
        assert snap["hours"].split()[0] in out, "스냅샷의 공식 영업시간이 들어가야 한다"
        assert "• Highlight: An old palace." in out
    finally:
        api.tourapi.items = real


def test_unknown_place_falls_through_to_the_existing_path():
    """공사 DB 에 없는 곳은 공사 API 를 부르지도 않는다."""
    calls = []
    real = _swap(_with_common(None, calls))
    try:
        api.poi_summary(R(name="어떤 골목 카페", type="cafe"))
    except Exception:
        pass  # Tavily 키가 없으면 여기서 죽는 게 정상 — 기존 경로로 갔다는 뜻이다.
    finally:
        api.tourapi.items = real
    assert calls == [], "색인에 없는 이름으로 공사 API 를 부르면 안 된다"


def test_tourapi_failure_does_not_break_the_sheet():
    def boom(*a, **k):
        raise RuntimeError("traffic exceeded serviceKey=SECRET")
    real = _swap(boom)
    try:
        assert api._tour_common(KNOWN) is None, "장애는 None 으로 삼켜야 한다"
    finally:
        api.tourapi.items = real


def test_image_uses_the_official_cdn_and_caches():
    calls = []
    real = _swap(_with_common(
        {"contentid": "1", "firstimage": "https://tong.visitkorea.or.kr/x.jpg"}, calls))
    try:
        got = api.poi_image(R(name=KNOWN, type="palace"), _FakeRequest())
        assert got["image_url"] == "https://tong.visitkorea.or.kr/x.jpg"
        api.poi_image(R(name=KNOWN, type="palace"), _FakeRequest())
        assert calls == ["detailCommon2"], f"두 번째는 캐시여야 한다: {calls}"
    finally:
        api.tourapi.items = real


def test_image_falls_back_to_detail_image_when_no_representative_photo():
    def fake(op, **params):
        if op == "detailCommon2":
            return [{"contentid": "1", "firstimage": ""}], 1
        return [{"originimgurl": "https://tong.visitkorea.or.kr/gallery.jpg"}], 1
    real = _swap(fake)
    try:
        got = api.poi_image(R(name=KNOWN, type="palace"), _FakeRequest())
        assert got["image_url"] == "https://tong.visitkorea.or.kr/gallery.jpg"
    finally:
        api.tourapi.items = real


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok  {name}")
    print("[selfcheck] OK")

# ---------------------------------------------------------------------------
# 미쉐린 restaurant.json 경로 — 잠긴 식사 슬롯과 교체 후보가 전부 여기서 온다
# ---------------------------------------------------------------------------

MICHELIN = "Onjium"  # restaurant.json 180건 안에 있다


def test_michelin_names_are_not_in_the_tourapi_index():
    """이 테스트가 깨지면 아래 세 개의 존재 이유가 사라진다.

    180곳 중 공사 DB 에 걸리는 곳이 0곳이라, 미쉐린 색인이 없으면 식당마다
    Tavily 검색 + Gemini 생성이 매번 나간다 — 파일에 영문 리뷰가 있는데도.
    """
    import meal_slots

    names = [r["name"] for r in meal_slots.load_restaurants()]
    assert len(names) == len(api._MICHELIN_SNAP), "이름 정규화가 중복을 접었다"
    hits = [n for n in names if api._norm_poi_name(n) in api._POI_SNAP]
    assert hits == [], f"공사 색인에 걸리는 식당이 생겼다: {hits[:5]}"


def test_summary_uses_the_guide_review_without_calling_tourapi_or_tavily():
    calls = []
    real = _swap(_with_common(None, calls))
    try:
        out = api.poi_summary(R(name=MICHELIN, type="restaurant"))
    finally:
        api.tourapi.items = real

    assert calls == [], "미쉐린 식당으로 공사 API 를 부르면 안 된다"
    # Tavily 키 없이도 통과한다 = _grounded_poi_text 로 안 갔다는 뜻.
    assert "Gyeongbokgung" in out["summary"], out


def test_detail_lists_the_guide_facts_not_the_llm():
    out = api.poi_detail(R(name=MICHELIN, type="restaurant"))["detail"]
    assert "• Michelin: 1 Michelin Star" in out, out
    assert "• Cuisine: Korean" in out, out
    # 한글 등급 키(1스타)가 그대로 새어 나가면 안 된다.
    assert "스타" not in out, out
    # opening_hours 가 있는 행만 Closed 줄을 낸다 -- 없으면 "매일 영업"으로
    # 단정하지 않고 줄 자체를 뺀다.
    assert "• Closed: " in out, out


def test_image_uses_the_guide_cdn():
    out = api.poi_image(R(name=MICHELIN, type="restaurant"), _FakeRequest())
    assert out["image_url"].startswith("https://prod-pics.guide.michelin.com/"), out


def test_a_restaurant_the_guide_does_not_list_still_falls_through():
    calls = []
    real = _swap(_with_common(None, calls))
    try:
        api.poi_summary(R(name="Some Random Diner", type="restaurant"))
    except Exception:
        pass  # Tavily 키가 없으면 여기서 죽는 게 정상 — 기존 경로로 갔다는 뜻이다.
    finally:
        api.tourapi.items = real
