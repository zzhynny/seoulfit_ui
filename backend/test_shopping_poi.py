"""build_shopping_poi.py 와 /nearby-shopping 자체 점검.

    backend/venv/bin/python backend/test_shopping_poi.py

네트워크를 타지 않는다 — 원본 덤프도 산출물도 로컬 파일이다.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))

import build_shopping_poi as B  # noqa: E402
import live_help  # noqa: E402

# CSS 가 설명문에 새면 이런 낱말이 남는다.
_CSS = re.compile(r"box-sizing|overflow-x|::-webkit|scrollbar-width|!important")


def _row(**kw):
    """detail 이 붙은 원본 한 줄을 만든다."""
    d = {
        "cid": kw.get("cid", "ENP1"),
        "post_sj": kw.get("title", "Some Shop"),
        "cate_depth": kw.get("depth", "Shopping > Traditional Markets"),
        "main_img": kw.get("image", "https://x/a.jpg"),
        "sumry": kw.get("sumry", "one line"),
        "post_desc": kw.get("desc", "<p>Body</p>"),
        "extra": kw.get("extra", {}),
        "traffic": kw.get("traffic", {"adres": "1 Sejong-daero, Jongno-gu, Seoul",
                                      "map_position_x": "126.98",
                                      "map_position_y": "37.56"}),
    }
    return {"cid": d["cid"], "cate_depth": d["cate_depth"], "detail": d}


def test_clean_html_drops_style_blocks_not_just_tags():
    """310건 중 190건이 post_desc 안에 <style> 을 물고 있다. 태그만 걷어내면
    CSS 본문이 그대로 설명문에 남는다."""
    raw = ('<div class="se-contents"><style type="text/css">'
           '.se-contents .se-scrollbox{overflow-x: auto;}</style>'
           '<p>Real body text.</p></div>')
    out = B.clean_html(raw)
    assert "Real body text." in out
    assert not _CSS.search(out), out


def test_clean_html_keeps_paragraph_breaks():
    assert B.clean_html("<p>One</p><p>Two</p>").splitlines()[0] == "One"


def test_clean_html_decodes_entities():
    assert B.clean_html("<p>Tom &amp; Jerry</p>") == "Tom & Jerry"


def test_clean_address_drops_the_korean_suffix():
    assert (B.clean_address("396, Gangnam-daero, Gangnam-gu, Seoul, Korea (강남역)")
            == "396, Gangnam-daero, Gangnam-gu, Seoul, Korea")


def test_one_line_folds_crlf():
    assert B.one_line("10:00~19:00\r\nClosed Monday") == "10:00~19:00 Closed Monday"


def test_build_maps_every_subcategory():
    rows = [_row(cid=str(i), depth=d) for i, d in enumerate(B.CATEGORIES)]
    got = {p["category"] for p in B.build(rows)}
    assert got == set(B.CATEGORIES.values()), got


def test_build_files_bare_shopping_under_specialty():
    """하위 분류 없이 대분류만 달린 48건. 전부 편집숍이라 SP 로 넣는다."""
    out = B.build([_row(depth="Shopping", title="10 Corso Como Seoul")])
    assert [p["category"] for p in out] == ["SP"]


def test_build_skips_rows_without_coordinates():
    out = B.build([_row(traffic={"adres": "somewhere"})])
    assert out == [], "a row with no lat/lng cannot be mapped or ranked"


def test_build_skips_rows_with_no_detail():
    assert B.build([{"cid": "x", "cate_depth": "Shopping"}]) == []


def test_build_rewrites_plain_http_images():
    out = B.build([_row(image="http://api.visitseoul.net/a.jpg")])
    assert out[0]["image"].startswith("https://")


def test_build_reads_hours_and_subway_from_their_nests():
    out = B.build([_row(
        extra={"cmmn_use_time": "10:30~20:00\r\n", "cmmn_telno": "02-1234-5678"},
        traffic={"map_position_x": "126.9", "map_position_y": "37.5",
                 "adres": "a", "subway_info": "Line 4 Hoehyeon Exit 7\r\n"})])
    assert out[0]["hours"] == "10:30~20:00"
    assert out[0]["tel"] == "02-1234-5678"
    assert out[0]["subway"] == "Line 4 Hoehyeon Exit 7"


def test_shipped_dataset_is_clean():
    d = live_help._SHOPPING_POIS
    assert len(d) == 310, f"expected the full Visit Seoul set, got {len(d)}"
    assert not [p for p in d if not (p["lat"] and p["lng"])]
    assert not [p for p in d if p["image"].startswith("http://")]
    assert not [p for p in d if _CSS.search(p["overview"])], "CSS leaked into overview"
    assert not [p for p in d if re.search(r"[가-힣]", p["title"])]
    assert not [p for p in d if re.search(r"[가-힣]", p["address"])]
    assert {p["category"] for p in d} <= set(B.CATEGORIES.values())


def test_shipped_dataset_category_counts():
    """칩이 비지 않는지. 얇은 칩(DF/SW)도 최소 한 건은 있어야 한다."""
    counts = {}
    for p in live_help._SHOPPING_POIS:
        counts[p["category"]] = counts.get(p["category"], 0) + 1
    assert counts == {"SP": 220, "TM": 35, "MO": 29, "DS": 18, "DF": 5, "SW": 3}, counts


def test_nearby_shopping_sorts_by_distance_and_caps_want():
    res = live_help.nearby_shopping(
        live_help.NearbyShoppingRequest(lat=37.5636, lng=126.9827, want=5))
    pois = res["pois"]
    assert len(pois) == 5
    assert [p["distance_m"] for p in pois] == sorted(p["distance_m"] for p in pois)
    assert pois[0]["distance_m"] < 500, "nothing near Myeongdong is suspicious"
    for p in pois:
        assert {"id", "title", "category", "address", "lat", "lng", "image",
                "summary", "overview", "hours", "tel", "homepage", "subway",
                "distance_m"} <= set(p)


def test_nearby_shopping_category_filter_is_exclusive():
    res = live_help.nearby_shopping(
        live_help.NearbyShoppingRequest(lat=37.5636, lng=126.9827,
                                        category="TM", want=10))
    assert res["pois"], "Traditional Markets must return something in Seoul"
    assert {p["category"] for p in res["pois"]} == {"TM"}


def test_nearby_shopping_does_not_mutate_the_loaded_dataset():
    """dict(p, distance_m=...) 가 사본을 만드는지. 원본에 거리가 눌러붙으면
    다음 요청이 남의 위치 기준 거리를 돌려준다."""
    live_help.nearby_shopping(
        live_help.NearbyShoppingRequest(lat=37.5, lng=127.0, want=3))
    assert not [p for p in live_help._SHOPPING_POIS if "distance_m" in p]


if __name__ == "__main__":
    test_clean_html_drops_style_blocks_not_just_tags()
    test_clean_html_keeps_paragraph_breaks()
    test_clean_html_decodes_entities()
    test_clean_address_drops_the_korean_suffix()
    test_one_line_folds_crlf()
    test_build_maps_every_subcategory()
    test_build_files_bare_shopping_under_specialty()
    test_build_skips_rows_without_coordinates()
    test_build_skips_rows_with_no_detail()
    test_build_rewrites_plain_http_images()
    test_build_reads_hours_and_subway_from_their_nests()
    test_shipped_dataset_is_clean()
    test_shipped_dataset_category_counts()
    test_nearby_shopping_sorts_by_distance_and_caps_want()
    test_nearby_shopping_category_filter_is_exclusive()
    test_nearby_shopping_does_not_mutate_the_loaded_dataset()
    print("shopping_poi self-check ok")
