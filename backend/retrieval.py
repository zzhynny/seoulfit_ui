"""코스 앵커 선택 — 지역·관심사로 거르고, 여행 목적과의 유사도로 순위를 매긴다.

이 파일 전까지 순위를 정하는 건 임베딩 코사인 하나였고, 지역은 `0 if in_area
else 1` 이라는 이진 정렬 키로 앞뒤만 갈랐다. 사용자에게 받은 여섯 슬롯 중 검색에
닿는 건 둘뿐이었다.

여기서는 순서가 뒤집힌다. 지역과 관심사는 사용자가 날짜별로 정한 하드 필터이고,
임베딩은 그 필터가 남긴 20~74개 안에서 순위만 정한다. 그래서 벡터가 없어도
(크레딧 소진, 인덱스 미빌드) 일정은 나온다 — 순위가 없을 뿐이다.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, NamedTuple

import numpy as np

from geo import area_matches_requested, infer_area_from_fields
from langsmith import traceable

_HERE = Path(__file__).resolve().parent
COURSE_DATA = _HERE / "dataset" / "course_data_v6.json"
DESCRIPTIONS = _HERE / "dataset" / "course_descriptions.json"
VECTORS = _HERE / "dataset" / "course_vectors.npz"

DEFAULT_K = 3

# Day Planner 화면이 여는 기본 지역 순서 -- 코스 풀이 넓은 곳부터 두어 어느
# 날도 앵커가 비지 않게 하고, 도심에서 시작해 밖으로 나가는 순서로 배열했다.
# 이 12개가 앱이 실제로 제시하는 전체 지역 어휘이기도 하다 (graph.py의
# DAY_PLAN_REGIONS와 lib/models/travel_state.dart의 kRegionLabels가 이 목록과
# 같은 키·순서를 쓴다) -- POST /day-plan은 이 목록으로 region을 검증하므로,
# 여기 없는 geo.SEOUL_AREA_CENTERS의 나머지 21개 키(코스 풀이 옅은 외곽
# 자치구 등)는 절대 통과하지 못한다.
DAY_PLAN_REGION_ORDER = [
    "jongno", "myeongdong", "hongdae", "gangnam",
    "seongsu", "itaewon", "bukchon",
    "insadong", "mapo", "dongdaemun", "sinchon", "apgujeong",
]


class Selection(NamedTuple):
    courses: list[dict[str, Any]]
    relaxed: str | None       # None | "interest" | "none_available"
    sims: dict[str, float]    # course_id -> 코사인. 벡터가 없으면 빈 dict


def base_id(course_id: str) -> str:
    """'VS_MVP_011_DAY2' -> 'VS_MVP_011'. 멀티데이 코스의 원본 식별자."""
    return re.sub(r"_DAY.*$", "", course_id)


_courses: list[dict[str, Any]] | None = None


def load_courses() -> list[dict[str, Any]]:
    """코스 데이터에 설명·태그를 course_id 로 병합해 돌려준다 (프로세스당 1회)."""
    global _courses
    if _courses is not None:
        return _courses

    raw = json.loads(COURSE_DATA.read_text(encoding="utf-8"))
    doc = json.loads(DESCRIPTIONS.read_text(encoding="utf-8"))
    by_id = {e["course_id"]: e for e in doc["courses"]}

    merged = []
    for c in raw:
        d = by_id.get(c["course_id"])
        if d is None:
            # 설명이 없는 코스는 필터를 통과할 수 없으니 넣지 않는다. 조용히
            # 순위만 밀리는 것보다 개수가 어긋나는 편이 눈에 띈다.
            print(f"[retrieval] no description for {c['course_id']} — skipped")
            continue
        merged.append({**c, "interests": d["interests"], "purpose": d["purpose"],
                       "description": d["description"], "constraints": d.get("constraints") or []})
    _courses = merged
    return _courses


def _in_region(course: dict[str, Any], region: str) -> bool:
    """POI 가 하나라도 그 지역(인접 포함)이면 통과.

    비율 임계값은 두지 않는다. `>0` 과 `>=10%` 가 12개 지역 전부에서 같은 결과를
    냈다 — 코스당 POI 가 4~8개라 하나만 맞아도 이미 12~25% 다.
    """
    for p in course["sequence"]:
        area = infer_area_from_fields(
            name=p.get("poi_name", ""),
            address=p.get("address_en") or p.get("address_ko") or "",
            lat=p.get("lat"), lng=p.get("lng"),
        )
        if area_matches_requested(area, region):
            return True
    return False


def _dedupe_by_base(courses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for c in courses:
        b = base_id(c["course_id"])
        if b in seen:
            continue
        seen.add(b)
        out.append(c)
    return out


def filter_pool(region: str, interest: str | None = None) -> list[dict[str, Any]]:
    """The courses that pass the filters, before dedupe, ranking or relaxation.

    select_anchors relaxes the interest filter when the pool cannot fill k, which
    makes it the wrong place to ask "how many courses match?". This answers that
    question directly.
    """
    in_region = [c for c in load_courses() if _in_region(c, region)]
    if interest:
        return [c for c in in_region if interest in c["interests"]]
    return in_region


@traceable(
    run_type="retriever",
    name="select_anchors",
    # `vectors` is the whole 125x3072 matrix (8.7MB as JSON) and purpose_vec is
    # another 69KB -- per call, per day. Neither is readable; drop both.
    process_inputs=lambda i: {
        "day": (i.get("day_spec") or {}).get("day"),
        "region": (i.get("day_spec") or {}).get("region"),
        "interest": (i.get("day_spec") or {}).get("interest"),
        "has_query_vec": (i.get("day_spec") or {}).get("purpose_vec") is not None,
        "exclude": sorted(i.get("exclude") or ()),
    },
    # Selection is a NamedTuple -- without this it serialises as a positional
    # tuple holding three full course dicts (~10KB). `relaxed` is the field that
    # currently only reaches stdout.
    process_outputs=lambda o: {
        "relaxed": o.relaxed,
        "course_ids": [c["course_id"] for c in o.courses],
        "top_sims": dict(sorted(o.sims.items(), key=lambda kv: -kv[1])[:5]),
    },
)
def select_anchors(
    day_spec: dict[str, Any],
    k: int = DEFAULT_K,
    *,
    exclude: Iterable[str] = (),
    vectors=None,
) -> Selection:
    """하루치 앵커 코스를 고른다.

    day_spec = {"day": int, "region": str, "interest": str | None, "purpose_vec": ndarray | None}
    exclude  = 앞선 날에 이미 쓴 base course id
    vectors  = (ids, matrix) 또는 None. None 이면 유사도 정렬 없이 필터 결과.
    """
    region = day_spec["region"]
    interest = day_spec.get("interest")
    excluded = set(exclude)

    in_region = filter_pool(region)
    if not in_region:
        return Selection([], "none_available", {})

    def finish(pool, relaxed):
        pool = _dedupe_by_base(pool)
        kept = [c for c in pool if base_id(c["course_id"]) not in excluded]
        # exclude 는 최선 노력이다. 얇은 지역에서는 앞선 날들이 후보를 다 써버릴
        # 수 있다 — 신촌은 풀이 5개다. k 를 못 채우면 제외를 푼다.
        if len(kept) < k:
            kept = pool
        ranked, sims = _rank(kept, day_spec.get("purpose_vec"), vectors)
        return Selection(ranked[:k], relaxed, sims)

    if interest:
        matched = [c for c in in_region if interest in c["interests"]]
        if len(_dedupe_by_base(matched)) >= k:
            return finish(matched, None)
        # 지역은 절대 풀지 않는다. 지역이 틀린 앵커는 하루 동선 전체를 망가뜨린다
        # — 프롬프트가 앵커 순서를 그날의 뼈대로 쓰라고 지시하기 때문이다.
        return finish(in_region, "interest")

    return finish(in_region, None)


def _rank(pool, query_vec, vectors):
    """유사도 순 정렬. 벡터가 없으면 입력 순서 그대로."""
    if vectors is None or query_vec is None or not pool:
        return pool, {}
    ids, matrix = vectors
    index = {cid: i for i, cid in enumerate(ids)}
    rows, have = [], []
    for c in pool:
        i = index.get(c["course_id"])
        if i is not None:
            rows.append(i)
            have.append(c)
    if not rows:
        return pool, {}
    scores = matrix[rows] @ query_vec
    sims = {c["course_id"]: float(s) for c, s in zip(have, scores)}
    order = sorted(have, key=lambda c: sims[c["course_id"]], reverse=True)
    missing = [c for c in pool if c["course_id"] not in sims]
    return order + missing, sims


@lru_cache(maxsize=1)
def load_vectors() -> tuple[list[str], "np.ndarray"] | None:
    """dataset/course_vectors.npz 를 읽어 (ids, matrix) 로 돌려준다.

    없으면 None — 호출자는 유사도 정렬만 건너뛰고 필터 결과로 계속 간다.
    FAISS 를 쓰지 않는다: 125개는 전수 내적이 근사보다 빠르고 정확하며, 무엇보다
    필터가 남긴 부분집합에만 점수를 매겨야 하는데 FAISS 는 그걸 못 한다.
    """
    if not VECTORS.exists():
        print(f"[retrieval] {VECTORS.name} not found — ranking disabled, filters still apply")
        return None
    z = np.load(VECTORS, allow_pickle=False)
    ids = [str(x) for x in z["ids"]]
    # 벡터가 없는 코스는 조용히 순위에서 빠진다. purpose 를 고치고 재빌드를
    # 잊었을 때 알아차릴 유일한 지점이라 여기서 소리를 낸다.
    if missing := {c["course_id"] for c in load_courses()} - set(ids):
        print(f"[retrieval] {len(missing)} courses have no vector — "
              f"they will not be ranked. Re-run build_vectors.py")
    return ids, z["vectors"]
