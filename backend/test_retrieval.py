"""retrieval.select_anchors — 실제 125행 데이터로. 임베딩 호출 없음."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import retrieval  # noqa: E402


def spec(region, day=1):
    return {"day": day, "region": region}


def test_region_filter_keeps_only_courses_touching_that_area():
    # Hongdae · Sinchon · Mapo 구역. Sinchon 이 구역에 들어오며 24 -> 27.
    pool = retrieval.filter_pool("hongdae")
    assert len(pool) == 27


def test_the_hongdae_zone_includes_sinchon_only_courses():
    hongdae = {c["course_id"] for c in retrieval.filter_pool("hongdae")}
    assert {c["course_id"] for c in retrieval.filter_pool("sinchon")} <= hongdae


def test_anchors_are_deduped_by_base_course():
    # VS_MVP_015 appears twice in the Hongdae pool.
    sel = retrieval.select_anchors(spec("hongdae"), k=100)
    bases = [retrieval.base_id(c["course_id"]) for c in sel.courses]
    assert len(sel.courses) == 24 and len(set(bases)) == 24   # 27 rows, 24 courses
    assert sel.relaxed is None


def test_no_anchor_when_region_has_nothing():
    sel = retrieval.select_anchors(spec("nowhere-at-all"), k=3)
    assert sel.courses == []
    assert sel.relaxed == "none_available"


def test_one_row_per_base_course_within_a_day():
    sel = retrieval.select_anchors(spec("jongno"), k=100)
    bases = [retrieval.base_id(c["course_id"]) for c in sel.courses]
    assert len(bases) == len(set(bases))


def test_exclude_drops_courses_used_on_earlier_days():
    first = retrieval.select_anchors(spec("jongno"), k=3)
    used = {retrieval.base_id(c["course_id"]) for c in first.courses}
    second = retrieval.select_anchors(
        spec("jongno", day=2), k=3, exclude=used
    )
    assert not used & {retrieval.base_id(c["course_id"]) for c in second.courses}


def test_exclude_is_released_rather_than_starving_a_thin_region():
    # 잠실 풀은 11개. 10개를 제외하면 k=3 을 못 채우므로 제외를 푼다.
    pool = retrieval.select_anchors(spec("jamsil"), k=100).courses
    used = {retrieval.base_id(c["course_id"]) for c in pool[:-1]}
    sel = retrieval.select_anchors(spec("jamsil"), k=3, exclude=used)
    assert len(sel.courses) == 3


def test_every_course_has_description_fields_joined():
    for c in retrieval.load_courses():
        assert c["interests"], c["course_id"]
        assert c["purpose"], c["course_id"]


import numpy as np  # noqa: E402


def _fake_vectors(course_ids, favourite):
    """favourite 만 질의와 같은 방향이고 나머지는 직교하는 단위 벡터들."""
    dim = 4
    matrix = np.zeros((len(course_ids), dim), dtype="float32")
    for i, cid in enumerate(course_ids):
        matrix[i, 1] = 1.0
    matrix[course_ids.index(favourite)] = np.array([1, 0, 0, 0], dtype="float32")
    return course_ids, matrix


def test_similarity_orders_the_filtered_pool():
    pool = retrieval.select_anchors(spec("jongno"), k=100).courses
    ids = [c["course_id"] for c in pool]
    favourite = ids[-1]                      # 필터 순서상 맨 뒤였던 코스
    q = np.array([1, 0, 0, 0], dtype="float32")

    sel = retrieval.select_anchors(
        {**spec("jongno"), "purpose_vec": q},
        k=3, vectors=_fake_vectors(ids, favourite),
    )
    assert sel.courses[0]["course_id"] == favourite
    assert sel.sims[favourite] == 1.0


def test_no_vectors_still_returns_k_courses():
    sel = retrieval.select_anchors(spec("jongno"), k=3, vectors=None)
    assert len(sel.courses) == 3
    assert sel.sims == {}


def test_load_vectors_returns_none_when_file_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(retrieval, "VECTORS", tmp_path / "nope.npz")
    assert retrieval.load_vectors.__wrapped__() is None
