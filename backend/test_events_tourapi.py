"""POST /events 자체 점검 — 한국관광공사 TourAPI 두 오퍼레이션의 병합과 칩 필터.

    backend/venv/bin/python -m pytest backend/test_events_tourapi.py

네트워크를 타지 않는다. 실제 호출까지 확인하려면 `python api.py` 의 selfcheck 를 쓴다.

여기서 잡으려는 것은 조용히 틀리는 세 가지다.
  - 축제와 상설 목록이 겹칠 때 날짜 있는 쪽이 밀려나는 것
  - 이미 끝난 축제가 그리드에 남는 것
  - 칩 라벨이 Flutter 의 kEventCategories 와 어긋나는 것 (다른 언어라 손으로 맞춘다)
"""

from __future__ import annotations

import datetime
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import api  # noqa: E402

_TODAY = datetime.date.today()


def _d(offset: int) -> str:
    return (_TODAY + datetime.timedelta(days=offset)).strftime("%Y%m%d")


def _row(cid, chip="EV01", title="Some Event (행사)", start=None, end=None, **kw):
    r = {"contentid": cid, "lclsSystm2": chip, "title": title,
         "addr1": "1 Sejong-daero, Jung-gu, Seoul", "firstimage": "", **kw}
    if start:
        r["eventstartdate"], r["eventenddate"] = start, end
    return r


def _fetch_with(festivals, standing):
    """tourapi.items 를 갈아끼우고 _fetch_events 를 돌린다."""
    def fake(op, **params):
        return (festivals if op == "searchFestival2" else standing), 0

    real, api.tourapi.items = api.tourapi.items, fake
    try:
        return api._fetch_events()
    finally:
        api.tourapi.items = real


def test_finished_festivals_are_dropped():
    rows = _fetch_with(
        [_row("1", start=_d(-30), end=_d(-1)),    # 어제 끝남
         _row("2", start=_d(-30), end=_d(0)),     # 오늘까지 — 남아야 한다
         _row("3", start=_d(3), end=_d(5))],      # 예정
        [],
    )
    assert {r["name"] for r in rows} == {"Some Event"}
    assert len(rows) == 2, f"expected 2 live festivals, got {len(rows)}"


def test_dedupe_keeps_the_dated_row():
    """같은 contentid 가 양쪽에 있으면 날짜가 붙은 축제 쪽을 남긴다."""
    rows = _fetch_with(
        [_row("9", start=_d(1), end=_d(2))],
        [_row("9"), _row("10")],
    )
    assert len(rows) == 2, "contentid 9 should collapse to one row"
    dated = next(r for r in rows if r["landing_url"].endswith("9"))
    assert dated["date"], "the dated (festival) row must win the merge"


def test_chip_filter_partitions_and_hides_internals():
    rows = _fetch_with([], [_row("1", "EV01"), _row("2", "EV02"), _row("3", "EV02"),
                            _row("4", "EV03")])

    assert len(api._chip_filter(rows, "All")) == 4
    assert len(api._chip_filter(rows, "Performances")) == 2
    assert len(api._chip_filter(rows, "")) == 4, "빈 카테고리는 전체여야 한다"
    assert len(api._chip_filter(rows, "Nonsense")) == 4, "모르는 라벨도 전체로 떨어진다"

    counts = sum(len(api._chip_filter(rows, c)) for c in api._EV_CHIP)
    assert counts == len(rows), "칩들이 목록을 정확히 분할해야 한다"

    assert "_chip" not in api._chip_filter(rows, "All")[0], "내부 필드가 응답에 새면 안 된다"


def test_date_range_formatting():
    [row] = _fetch_with([_row("1", start="20261002", end="20261004")], [])
    assert row["date"] == "Oct 02, 2026 - Oct 04, 2026"

    [same] = _fetch_with([_row("1", start="20261002", end="20261002")], [])
    assert same["date"] == "Oct 02, 2026", "하루짜리는 범위로 쓰지 않는다"

    [undated] = _fetch_with([], [_row("1")])
    assert undated["date"] == "", "상설 항목은 날짜가 없다"


def test_landing_url_uses_the_contentid_scheme():
    """카드 탭이 열 주소. 한때 contentsView.do?vcontsId= 였고 전건 400 이었다.

    vcontsId 는 공사 API 의 contentid 와 다른 ID 체계다. 그런데 400 페이지도
    브라우저에서는 그냥 열리므로 앱에서는 아무 오류로도 안 보였다 — 탭하면
    오류 페이지가 뜰 뿐이었다. 그래서 모양을 여기서 못박는다. 실제로 200 이
    오는지는 `python api.py` selfcheck 가 네트워크로 확인한다.
    """
    [row] = _fetch_with([], [_row("3544280")])
    assert "vcontsId" not in row["landing_url"], "vcontsId 체계는 400 을 낸다"
    assert row["landing_url"].endswith("cid=3544280"), row["landing_url"]


def test_detail_fields_ride_along_with_the_list():
    """상세 시트가 쓰는 필드가 목록 응답에 실려야 한다.

    contentid 가 없으면 /event-detail 을 부를 수 없고, lat/lng 가 없으면
    시트의 카카오맵 버튼이 사라진다. 셋 다 이미 공사 응답에 있는 값이라
    빠뜨려도 조용하다.
    """
    [row] = _fetch_with([], [_row("77", mapx="127.001", mapy="37.566")])
    assert row["contentid"] == "77"
    assert (row["lat"], row["lng"]) == (37.566, 127.001), "mapy=위도, mapx=경도"

    [nocoord] = _fetch_with([], [_row("78", mapx="", mapy="")])
    assert nocoord["lat"] is None and nocoord["lng"] is None, "빈 좌표는 None"


def test_event_detail_survives_a_dead_upstream():
    """공사 API 가 죽어도 빈 칸을 주지 시트를 깨지 않는다."""
    def boom(op, **params):
        raise RuntimeError("upstream down")

    real, api.tourapi.items = api.tourapi.items, boom
    try:
        detail = api._event_detail("1234")
    finally:
        api.tourapi.items = real

    assert detail == {k: "" for k in detail}, "전 필드가 빈 문자열이어야 한다"
    assert "1234" not in api._EVENT_DETAIL_CACHE, "빈손을 24시간 캐시하면 안 된다"


def test_homepage_becomes_launchable():
    """공사 homepage 는 스킴 없이 오고, 여러 줄인 것도 있다."""
    assert api._first_url("www.kh.or.kr") == "https://www.kh.or.kr"
    assert api._first_url("https://a.com") == "https://a.com", "스킴이 잘리면 안 된다"
    assert api._first_url("Website: www.siwf.or.kr\nInstagram: x") == "https://www.siwf.or.kr"
    assert api._first_url("") == ""


def test_chip_labels_match_the_flutter_app():
    """백엔드의 칩 라벨과 lib/models/event.dart 의 kEventCategories 가 같아야 한다.

    둘이 어긋나도 예외는 안 난다 — 칩이 조용히 전체 목록을 보여줄 뿐이라
    눈으로는 못 잡는다.
    """
    dart = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "lib", "models", "event.dart")
    src = open(dart, encoding="utf-8").read()
    listed = re.search(r"kEventCategories\s*=\s*\[(.*?)\]", src, re.S).group(1)
    labels = re.findall(r"'([^']+)'", listed)

    assert labels[0] == "All", "첫 칩은 All 이어야 한다 (기본 탭)"
    assert labels[1:] == list(api._EV_CHIP), f"칩이 어긋났다: {labels[1:]} vs {list(api._EV_CHIP)}"

    default = re.search(r"kDefaultEventCategory\s*=\s*'([^']+)'", src).group(1)
    assert default in labels, f"기본 칩 {default!r} 이 목록에 없다"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok  {name}")
    print("[selfcheck] OK")
