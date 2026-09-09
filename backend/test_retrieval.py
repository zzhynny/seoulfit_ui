"""retrieval.select_anchors — 실제 125행 데이터로. 임베딩 호출 없음."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import retrieval  # noqa: E402


def spec(region, interest, day=1):
    return {"day": day, "region": region, "interest": interest}


def test_region_filter_keeps_only_courses_touching_that_area():
    pool = retrieval.filter_pool("hongdae")
    assert len(pool) == 24


def test_interest_filter_narrows_further():
    pool = retrieval.filter_pool("hongdae", "Shopping")
    assert len(pool) == 8
    assert all("Shopping" in c["interests"] for c in pool)


def test_anchors_are_deduped_by_base_course():
    # 24 rows, 23 distinct base courses — VS_MVP_015 appears twice in the Hongdae pool.
    sel = retrieval.select_anchors(spec("hongdae", None), k=100)
    assert len(sel.courses) == 23
    assert sel.relaxed is None


def test_relaxes_interest_when_pool_is_too_thin():
    # 신촌 x Shopping 은 1개뿐 — 60개 조합 중 유일하게 k=3 을 못 채운다.
    sel = retrieval.select_anchors(spec("sinchon", "Shopping"), k=3)
    assert sel.relaxed == "interest"
    assert len(sel.courses) == 3


def test_no_anchor_when_region_has_nothing():
    sel = retrieval.select_anchors(spec("nowhere-at-all", "Shopping"), k=3)
    assert sel.courses == []
    assert sel.relaxed == "none_available"


def test_one_row_per_base_course_within_a_day():
    sel = retrieval.select_anchors(spec("jongno", "Culture & History"), k=100)
    bases = [retrieval.base_id(c["course_id"]) for c in sel.courses]
    assert len(bases) == len(set(bases))


def test_exclude_drops_courses_used_on_earlier_days():
    first = retrieval.select_anchors(spec("jongno", "Culture & History"), k=3)
    used = {retrieval.base_id(c["course_id"]) for c in first.courses}
    second = retrieval.select_anchors(
        spec("jongno", "Culture & History", day=2), k=3, exclude=used
    )
    assert not used & {retrieval.base_id(c["course_id"]) for c in second.courses}


def test_exclude_is_released_rather_than_starving_a_thin_region():
    # 신촌 풀은 5개. 4개를 제외하면 k=3 을 못 채우므로 제외를 푼다.
    pool = retrieval.select_anchors(spec("sinchon", None), k=100).courses
    used = {retrieval.base_id(c["course_id"]) for c in pool[:4]}
    sel = retrieval.select_anchors(spec("sinchon", None), k=3, exclude=used)
    assert len(sel.courses) == 3


def test_every_course_has_description_fields_joined():
    for c in retrieval.load_courses():
        assert c["interests"], c["course_id"]
        assert c["purpose"], c["course_id"]
