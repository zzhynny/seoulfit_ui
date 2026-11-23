"""build_course_data_v7 — 걸러내는 규칙과, 커밋된 v7 이 스크립트 결과와 같은지.

규칙 테스트는 합성 데이터라 v6 이 바뀌어도 흔들리지 않는다. 마지막 테스트는 일부러
실제 파일을 본다: 스크립트나 v6 를 고치고 v7 재생성을 잊으면 여기서 깨진다.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))

import build_course_data_v7 as b


def stop(name, ptype="tourist_spot", lat=37.55, lng=126.98, area=False, order=1):
    return {"sequence_order": order, "poi_name": name, "poi_type": ptype,
            "lat": lat, "lng": lng, "is_area_type": area}


def course(cid, *stops):
    return {"course_id": cid, "course_title": cid, "sequence": list(stops)}


def three_sights(cid="OK", **kw):
    return course(cid, stop("A", "museum", order=1), stop("B", "park", order=2), stop("C", "history", order=3), **kw)


def build_one(c):
    kept, report = b.build([c])
    return kept, report


def test_a_normal_course_is_kept_unchanged():
    kept, report = build_one(three_sights())
    assert [p["poi_name"] for p in kept[0]["sequence"]] == ["A", "B", "C"]
    assert report["counts"] == {"v6": 1, "v7": 1, "dropped": 0, "stops_removed": 0}


def test_generic_stop_is_removed_and_order_renumbered():
    c = course("G", stop("A", "museum", order=1), stop("Karaoke (노래방)", order=2),
               stop("B", "park", order=3), stop("C", "history", order=4))
    kept, report = build_one(c)
    assert [p["poi_name"] for p in kept[0]["sequence"]] == ["A", "B", "C"]
    assert [p["sequence_order"] for p in kept[0]["sequence"]] == [1, 2, 3]
    assert report["trimmed_courses"][0]["removed"] == ["Karaoke (노래방) [generic]"]


def test_a_point_station_goes_but_an_area_station_and_a_station_building_stay():
    seq = [stop("Anguk Station (안국역)"),                                  # 점 → 제거
           stop("Gangnam Station (강남역)", "shopping", area=True),          # 상권 → 유지
           stop("Culture Station Seoul 284 (문화역서울284)", "museum"),      # 건물 → 유지
           stop("Hongik Univ. Station (AREX) (홍대입구역)", "street"),       # 괄호 둘 → 제거
           stop("Some Park (공원)", "park")]                                 # 3곳이 남아야 코스가 산다
    kept, _ = build_one(course("S", *seq))
    names = [p["poi_name"] for p in kept[0]["sequence"]]
    assert names == ["Gangnam Station (강남역)", "Culture Station Seoul 284 (문화역서울284)", "Some Park (공원)"]


def test_thin_courses_are_dropped():
    c = course("T", stop("A", "museum"), stop("B", "park"))
    kept, report = build_one(c)
    assert kept == []
    assert report["dropped_courses"][0]["reasons"] == ["thin"]


def test_food_only_courses_are_dropped_but_markets_count_as_sights():
    food = course("F", stop("R1", "restaurant"), stop("R2", "restaurant"), stop("C1", "cafe"))
    assert build_one(food)[0] == []
    assert build_one(food)[1]["dropped_courses"][0]["reasons"] == ["food_only"]
    market = course("M", stop("R1", "restaurant"), stop("Gwangjang (광장시장)", "market"), stop("P", "park"))
    assert len(build_one(market)[0]) == 1


def test_spread_is_total_path_not_zone_count():
    far = course("X", stop("A", "museum", lat=37.45, lng=126.9), stop("B", "park", lat=37.65, lng=127.1),
                 stop("C", "history", lat=37.45, lng=126.9))      # 왕복 ≈ 50km, 한 점으로 보면 같은 구역
    kept, report = build_one(far)
    assert kept == []
    assert report["dropped_courses"][0]["reasons"] == ["spread"]


def test_thresholds_are_judged_after_generic_stops_are_removed():
    # 4 stops, one generic → 3 sights left → kept. With 3 stops and one generic → 2 left → thin.
    ok = course("A", stop("A", "museum"), stop("Jjimjilbang (찜질방)"), stop("B", "park"), stop("C", "history"))
    assert len(build_one(ok)[0]) == 1
    thin = course("B", stop("A", "museum"), stop("Jjimjilbang (찜질방)"), stop("B", "park"))
    kept, report = build_one(thin)
    assert kept == [] and report["dropped_courses"][0]["stops_before"] == 3
    assert report["dropped_courses"][0]["stops_after"] == 2


def test_committed_v7_is_what_the_script_produces_from_v6():
    v6 = json.loads(b.V6_PATH.read_text(encoding="utf-8"))
    v7 = json.loads(b.V7_PATH.read_text(encoding="utf-8"))
    assert v7 == b.build(v6)[0], "v7 is stale — run scripts/build_course_data_v7.py"


def test_every_v7_course_has_a_description_and_a_vector():
    import numpy as np
    v7 = {c["course_id"] for c in json.loads(b.V7_PATH.read_text(encoding="utf-8"))}
    descriptions = {e["course_id"] for e in json.loads(
        (b.V7_PATH.parent / "course_descriptions.json").read_text(encoding="utf-8"))["courses"]}
    vectors = {str(x) for x in np.load(b.V7_PATH.parent / "course_vectors.npz")["ids"]}
    assert v7 <= descriptions and v7 <= vectors
