"""/nearby-poi 자체 점검 — locationBasedList2 실시간 조회와 스냅샷 폴백.

    backend/venv/bin/python -m pytest backend/test_nearby_poi_live.py

네트워크를 타지 않는다. tourapi.items 를 갈아끼워 응답을 만든다.

조용히 틀리는 것들을 잡는다.
  - mapX/mapY 를 뒤집는 것. 공사 API 는 X 가 경도인데 위경도 순서에 익숙하면
    반대로 넣게 되고, 그래도 예외는 안 나고 엉뚱한 동네 POI 가 나온다.
  - 공사 API 가 죽었을 때 빈 화면이 되는 것. 심사 중 쿼터가 끊겨도 서야 한다.
  - 좌표가 조금 움직일 때마다 새로 호출하는 것 (쿼터).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import live_help as L  # noqa: E402

_GYEONGBOK = (37.5796, 126.9769)


def _row(cid="1", title="Some Place (어떤 곳)", dist=300, cat="VE", **kw):
    return {"contentid": cid, "title": title, "lclsSystm1": cat, "addr1": "Seoul",
            "mapx": "126.9769", "mapy": "37.5796", "dist": str(dist),
            "firstimage": "", **kw}


def _with_api(rows, capture=None):
    """tourapi.items 를 rows 를 주는 가짜로 바꾼다. capture 에 파라미터를 남긴다."""
    def fake(op, **params):
        if capture is not None:
            capture.append((op, params))
        return list(rows), len(rows)
    return fake


def _run(rows=None, *, fail=False, capture=None, **req_kw):
    L._POI_CACHE.clear()
    real = L.tourapi.items
    if fail:
        def boom(*a, **k):
            raise RuntimeError("traffic exceeded serviceKey=SECRET123")
        L.tourapi.items = boom
    else:
        L.tourapi.items = _with_api(rows or [], capture)
    try:
        lat, lng = _GYEONGBOK
        return L.nearby_poi(L.NearbyPoiRequest(lat=lat, lng=lng, **req_kw))["pois"]
    finally:
        L.tourapi.items = real


def test_longitude_goes_in_mapx():
    """공사 API 는 mapX 가 경도, mapY 가 위도다."""
    capture = []
    _run([_row()], capture=capture)
    op, params = capture[0]
    assert op == "locationBasedList2"
    lat, lng = _GYEONGBOK
    assert params["mapX"] == lng, f"mapX 는 경도여야 한다 (got {params['mapX']})"
    assert params["mapY"] == lat, f"mapY 는 위도여야 한다 (got {params['mapY']})"
    assert params["radius"] == L._RADIUS_M


def test_detail_fields_come_from_the_snapshot():
    """목록 응답에 없는 상세는 contentid 로 사전 수집분에서 채운다."""
    known = L._TOUR_POIS[0]
    [row] = _run([_row(cid=known["id"])])
    assert row["overview"] == known["overview"], "스냅샷의 소개글이 붙어야 한다"

    [unknown] = _run([_row(cid="nonexistent-id")])
    assert unknown["overview"] == "", "모르는 POI 는 빈 문자열 (앱이 줄을 숨긴다)"
    assert set(L._DETAIL_FIELDS) <= set(unknown), "상세 키는 항상 있어야 한다"


def test_falls_back_to_the_snapshot_when_tourapi_fails():
    rows = _run(fail=True)
    assert rows, "공사 API 가 죽어도 화면은 서야 한다"
    assert rows[0]["distance_m"] <= L._RADIUS_M
    assert rows == sorted(rows, key=lambda p: p["distance_m"]), "거리순이어야 한다"


def test_nearby_coordinates_share_one_call():
    """110m 안쪽으로 움직이는 동안은 캐시를 쓴다."""
    capture = []
    L._POI_CACHE.clear()
    real, L.tourapi.items = L.tourapi.items, _with_api([_row()], capture)
    try:
        lat, lng = _GYEONGBOK
        L.nearby_poi(L.NearbyPoiRequest(lat=lat, lng=lng))
        L.nearby_poi(L.NearbyPoiRequest(lat=lat + 0.0002, lng=lng + 0.0002))
        assert len(capture) == 1, f"같은 자리에서 {len(capture)}회 호출했다"

        L.nearby_poi(L.NearbyPoiRequest(lat=lat + 0.02, lng=lng))  # 약 2km
        assert len(capture) == 2, "멀리 가면 새로 받아야 한다"
    finally:
        L.tourapi.items = real


def test_category_filters_without_refetching():
    capture = []
    L._POI_CACHE.clear()
    real, L.tourapi.items = L.tourapi.items, _with_api(
        [_row("1", cat="VE"), _row("2", cat="EX"), _row("3", cat="VE")], capture)
    try:
        lat, lng = _GYEONGBOK
        assert len(L.nearby_poi(L.NearbyPoiRequest(lat=lat, lng=lng))["pois"]) == 3
        ve = L.nearby_poi(L.NearbyPoiRequest(lat=lat, lng=lng, category="VE"))["pois"]
        assert len(ve) == 2, "칩은 받아둔 목록을 거른다"
        assert len(capture) == 1, "칩 전환이 재호출을 만들면 안 된다"
    finally:
        L.tourapi.items = real


def test_want_caps_the_response():
    rows = _run([_row(str(i)) for i in range(50)], want=5)
    assert len(rows) == 5


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok  {name}")
    print("[selfcheck] OK")
