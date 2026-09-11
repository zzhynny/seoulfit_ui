# 검색 재설계 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 코스 검색을 필터 우선으로 뒤집는다 — 지역·관심사는 사용자가 날짜별로 정한 하드 필터, 순위는 여행 목적과 코스 `purpose`의 임베딩 유사도.

**Architecture:** 새 모듈 `backend/retrieval.py`가 필터·완화·정렬을 전담하고 공개 함수는 `select_anchors` 하나다. 벡터는 FAISS 대신 `.npz` 행렬 하나로 두고 필터가 남긴 부분집합에만 내적을 건다. 날짜별 지역·관심사는 새 Flutter 화면이 받아 `POST /day-plan`으로 체크포인트에 쓴다.

**Tech Stack:** Python 3.11 / FastAPI / LangGraph (MemorySaver 체크포인트) / numpy / Flutter

**Spec:** `docs/superpowers/specs/2026-09-09-retrieval-redesign-design.md`

## Global Constraints

- 작업 디렉터리는 `/Users/jameslee/cj_final/seoulfit_ui`. Python은 **`./backend/venv/bin/python`으로만** 실행한다. `backend/venv/bin/uvicorn` 등 스크립트는 shebang이 옛 경로를 물고 있어 깨진다 — 항상 `python -m`.
- 테스트: `cd backend && ./venv/bin/python -m pytest -q --ignore=test_reorder_supplements.py --ignore=test_checkin_store.py`. 이 두 파일은 선재 실패이며 이번 작업과 무관하다 (전자는 `seoulfit_ui/benchmark/`가 없어 glob 0건, 후자는 `db` fixture를 줄 `conftest.py`가 없음). **기준선은 67 passed.**
- Flutter: `/opt/homebrew/bin/flutter analyze lib/` 가 `No issues found!` 여야 한다.
- 관심사 어휘 5개는 **글자 하나까지 고정**이며 세 곳(`graph.FIELD_EXTRACT`, Flutter 칩, `course_descriptions.json`의 `interests`)이 정확히 같은 문자열을 쓴다: `Culture & History`, `Food & Cafes`, `Shopping`, `K-POP & Hallyu`, `Nature & Relaxation`.
- 지역 키는 `geo.SEOUL_AREA_CENTERS`의 소문자 키다. 앱이 제시하는 12개: `jongno, gangnam, myeongdong, hongdae, seongsu, itaewon, bukchon, mapo, insadong, dongdaemun, sinchon, apgujeong`.
- `k = 3` 고정.
- Gemini 크레딧이 현재 소진 상태(`429 RESOURCE_EXHAUSTED`)다. Task 3의 배치 실행과 Task 6의 런타임 임베딩은 충전 후에만 검증 가능하다. 나머지 태스크는 전부 크레딧 없이 진행·테스트된다.
- 커밋 메시지는 영어. 끝에 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## 파일 구조

| 파일 | 책임 |
|---|---|
| `backend/retrieval.py` (신규) | 코스+설명 조인, 지역/관심사 필터, 완화 사다리, 유사도 정렬, 벡터 로드. 공개: `select_anchors`, `load_vectors`, `DAY_PLAN_REGION_ORDER` |
| `backend/test_retrieval.py` (신규) | 위 전부를 실데이터 125행으로 검증. 임베딩 호출 0회 |
| `backend/build_vectors.py` (신규) | 코스 `purpose` 125개 임베딩 → `dataset/course_vectors.npz` |
| `backend/test_build_vectors.py` (신규) | 정규화·저장·로드 왕복. 임베딩 함수는 주입 |
| `backend/graph.py` (수정) | `region` 질문 제거, `purpose` 질문 추가, `day_plan` 단계 + 기본값 |
| `backend/state.py` (수정) | `purpose`, `day_specs` 추가 |
| `backend/api.py` (수정) | `POST /day-plan`, `StateResponse`에 `purpose`·`day_specs` |
| `backend/test_day_plan.py` (신규) | 기본값 생성, 입력 검증, 왕복 |
| `backend/planner.py` (수정) | `retrieve_node`가 `select_anchors`를 쓰도록, `requested_areas`를 `day_specs`에서 |
| `backend/rag.py` (수정) | FAISS·구간분할·dead code 제거 |
| `lib/models/travel_state.dart` (수정) | `purpose`, `daySpecs` |
| `lib/services/api_service.dart` (수정) | `postDayPlan` |
| `lib/screens/trip/day_planner_screen.dart` (신규) | 날짜별 지역·관심사 화면 |
| `test/day_planner_test.dart` (신규) | 화면 위젯 테스트 |

---

### Task 1: `retrieval.py` — 필터와 완화 (임베딩 없이)

**Files:**
- Create: `backend/retrieval.py`
- Test: `backend/test_retrieval.py`

**Interfaces:**
- Consumes: `geo.area_matches_requested`, `geo.infer_area_from_fields`, `dataset/course_data_v6.json`, `dataset/course_descriptions.json`
- Produces:
  - `Selection` — `NamedTuple(courses: list[dict], relaxed: str | None, sims: dict[str, float])`
  - `select_anchors(day_spec: dict, k: int = 3, *, exclude: Iterable[str] = (), vectors=None) -> Selection`
  - `base_id(course_id: str) -> str`
  - `load_courses() -> list[dict]` — 코스에 `interests`/`purpose`/`description`이 병합된 상태

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/test_retrieval.py`:

```python
"""retrieval.select_anchors — 실제 125행 데이터로. 임베딩 호출 없음."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import retrieval  # noqa: E402


def spec(region, interest, day=1):
    return {"day": day, "region": region, "interest": interest}


def test_region_filter_keeps_only_courses_touching_that_area():
    sel = retrieval.select_anchors(spec("hongdae", None), k=100)
    assert len(sel.courses) == 24
    assert sel.relaxed is None


def test_interest_filter_narrows_further():
    sel = retrieval.select_anchors(spec("hongdae", "Shopping"), k=100)
    assert len(sel.courses) == 8
    assert all("Shopping" in c["interests"] for c in sel.courses)


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
```

- [ ] **Step 2: 실패를 확인한다**

```bash
cd backend && ./venv/bin/python -m pytest test_retrieval.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named 'retrieval'`

- [ ] **Step 3: `backend/retrieval.py`를 쓴다**

```python
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
from pathlib import Path
from typing import Any, Iterable, NamedTuple

from geo import area_matches_requested, infer_area_from_fields

_HERE = Path(__file__).resolve().parent
COURSE_DATA = _HERE / "dataset" / "course_data_v6.json"
DESCRIPTIONS = _HERE / "dataset" / "course_descriptions.json"
VECTORS = _HERE / "dataset" / "course_vectors.npz"

DEFAULT_K = 3

# Day Planner 화면이 여는 기본 지역 순서. 코스 풀이 넓은 곳부터 두어 어느 날도
# 앵커가 비지 않게 하고, 도심에서 시작해 밖으로 나가는 순서로 배열했다.
DAY_PLAN_REGION_ORDER = [
    "jongno", "myeongdong", "hongdae", "gangnam",
    "seongsu", "itaewon", "bukchon",
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

    in_region = [c for c in load_courses() if _in_region(c, region)]
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
```

- [ ] **Step 4: 통과를 확인한다**

```bash
cd backend && ./venv/bin/python -m pytest test_retrieval.py -q
```
Expected: 8 passed

- [ ] **Step 5: 전체 회귀**

```bash
cd backend && ./venv/bin/python -m pytest -q --ignore=test_reorder_supplements.py --ignore=test_checkin_store.py
```
Expected: 75 passed (기준선 67 + 신규 8)

- [ ] **Step 6: 커밋**

```bash
git add backend/retrieval.py backend/test_retrieval.py
git commit -m "Filter courses by region and interest before ranking them

Anchor selection ranked by one cosine score and then partitioned the
result with a binary in-area key, so a course with one Hongdae POI out of
twenty sorted level with one that is entirely Hongdae.

Region and interest are now filters the caller sets per day. No ratio
threshold: >0 and >=10% return identical pools across all twelve regions,
because a course holds four to eight POIs and one match is already 12-25%.

Interest relaxes when the pool cannot fill k; region never does. An anchor
from the wrong district breaks the whole day, since the prompt tells the
model to use the anchor's order as that day's backbone.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: 유사도 정렬과 벡터 로드

**Files:**
- Modify: `backend/retrieval.py` (`load_vectors` 추가)
- Modify: `backend/test_retrieval.py` (정렬 테스트 추가)

**Interfaces:**
- Consumes: Task 1의 `select_anchors`, `Selection`
- Produces: `load_vectors() -> tuple[list[str], np.ndarray] | None`

- [ ] **Step 1: 실패하는 테스트를 추가한다**

`backend/test_retrieval.py` 끝에 붙인다:

```python
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
    pool = retrieval.select_anchors(spec("jongno", "Culture & History"), k=100).courses
    ids = [c["course_id"] for c in pool]
    favourite = ids[-1]                      # 필터 순서상 맨 뒤였던 코스
    q = np.array([1, 0, 0, 0], dtype="float32")

    sel = retrieval.select_anchors(
        {**spec("jongno", "Culture & History"), "purpose_vec": q},
        k=3, vectors=_fake_vectors(ids, favourite),
    )
    assert sel.courses[0]["course_id"] == favourite
    assert sel.sims[favourite] == 1.0


def test_no_vectors_still_returns_k_courses():
    sel = retrieval.select_anchors(spec("jongno", "Culture & History"), k=3, vectors=None)
    assert len(sel.courses) == 3
    assert sel.sims == {}


def test_load_vectors_returns_none_when_file_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(retrieval, "VECTORS", tmp_path / "nope.npz")
    assert retrieval.load_vectors.__wrapped__() is None
```

- [ ] **Step 2: 실패를 확인한다**

```bash
cd backend && ./venv/bin/python -m pytest test_retrieval.py -q
```
Expected: FAIL — `AttributeError: module 'retrieval' has no attribute 'load_vectors'`

- [ ] **Step 3: `load_vectors`를 구현한다**

`backend/retrieval.py`의 import에 추가:

```python
from functools import lru_cache

import numpy as np
```

파일 끝에 추가:

```python
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
    return [str(x) for x in z["ids"]], z["vectors"]
```

- [ ] **Step 4: 통과를 확인한다**

```bash
cd backend && ./venv/bin/python -m pytest test_retrieval.py -q
```
Expected: 11 passed

- [ ] **Step 5: 커밋**

```bash
git add backend/retrieval.py backend/test_retrieval.py
git commit -m "Rank the filtered pool by purpose similarity

The vectors are a plain (ids, matrix) pair loaded from an .npz, not a FAISS
index. A filtered pool is a subset, and FAISS cannot score a subset; 125
vectors also make exhaustive dot products faster and exact.

load_vectors returns None when the file is missing, and select_anchors then
skips ordering and returns the filtered pool as-is. Losing the ranking is
not losing the itinerary.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: `build_vectors.py`

**Files:**
- Create: `backend/build_vectors.py`
- Test: `backend/test_build_vectors.py`

**Interfaces:**
- Consumes: `dataset/course_descriptions.json`
- Produces: `normalize(matrix) -> np.ndarray`, `build(embed_fn) -> tuple[list[str], np.ndarray]`, `dataset/course_vectors.npz`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/test_build_vectors.py`:

```python
"""build_vectors — 임베딩 함수는 주입해서 API 호출 없이 검증한다."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

import build_vectors  # noqa: E402


def test_normalize_makes_unit_rows():
    m = np.array([[3.0, 4.0], [0.0, 2.0]], dtype="float32")
    out = build_vectors.normalize(m)
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0)


def test_normalize_leaves_zero_rows_alone_instead_of_dividing_by_zero():
    m = np.array([[0.0, 0.0], [1.0, 0.0]], dtype="float32")
    out = build_vectors.normalize(m)
    assert np.all(np.isfinite(out))
    assert np.allclose(out[0], 0.0)


def test_build_embeds_every_course_purpose():
    seen = []

    def fake_embed(texts):
        seen.extend(texts)
        return np.tile(np.array([1.0, 0.0], dtype="float32"), (len(texts), 1))

    ids, matrix = build_vectors.build(fake_embed)
    assert len(ids) == 125
    assert matrix.shape == (125, 2)
    assert all(t for t in seen), "빈 purpose 가 임베딩으로 넘어가면 안 된다"


def test_save_and_load_round_trip(tmp_path):
    ids = ["A", "B"]
    matrix = np.array([[1.0, 0.0], [0.0, 1.0]], dtype="float32")
    path = tmp_path / "v.npz"
    build_vectors.save(path, ids, matrix)

    z = np.load(path, allow_pickle=False)
    assert [str(x) for x in z["ids"]] == ids
    assert np.allclose(z["vectors"], matrix)
```

- [ ] **Step 2: 실패를 확인한다**

```bash
cd backend && ./venv/bin/python -m pytest test_build_vectors.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named 'build_vectors'`

- [ ] **Step 3: `backend/build_vectors.py`를 쓴다**

```python
"""코스 purpose 를 임베딩해 dataset/course_vectors.npz 를 만든다.

    ./venv/bin/python build_vectors.py

오프라인 배치다. 서비스 실행 중에는 돌지 않는다. course_descriptions.json 의
purpose 를 고치면 다시 돌려야 한다 — 안 돌리면 그 코스만 순위에서 밀린다
(예전 FAISS 인덱스처럼 조용히 옛 데이터를 쓰는 게 아니다. 그쪽은 index.pkl 에
코스 dict 사본을 통째로 담고 있었다).

description 은 임베딩하지 않는다. 장소 나열이라 목적 신호를 희석시키고, 장소는
이미 지역 필터가 처리한다.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
DESCRIPTIONS = _HERE / "dataset" / "course_descriptions.json"
OUT = _HERE / "dataset" / "course_vectors.npz"

EMBEDDING_MODEL = "models/gemini-embedding-001"
CHUNK = 50          # rag.py 가 쓰던 값과 같다 — 이 API 의 배치 한도에 맞춘 것


def normalize(matrix: np.ndarray) -> np.ndarray:
    """행마다 L2 정규화. 미리 해두면 검색이 내적 한 번으로 끝난다."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0        # 0 벡터는 그대로 둔다 — 나누면 nan 이 된다
    return (matrix / norms).astype("float32")


def build(embed_fn) -> tuple[list[str], np.ndarray]:
    """embed_fn(list[str]) -> ndarray 를 받아 (ids, 정규화된 행렬)."""
    doc = json.loads(DESCRIPTIONS.read_text(encoding="utf-8"))
    entries = doc["courses"]
    ids = [e["course_id"] for e in entries]
    texts = [e["purpose"] for e in entries]
    if not all(texts):
        raise ValueError("purpose 가 빈 코스가 있다 — validate_descriptions.py 를 먼저 통과시켜라")
    return ids, normalize(np.asarray(embed_fn(texts), dtype="float32"))


def save(path: Path, ids: list[str], matrix: np.ndarray) -> None:
    np.savez(path, ids=np.array(ids), vectors=matrix)


def _gemini_embed(texts: list[str]) -> np.ndarray:
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    if not key:
        raise SystemExit("GEMINI_API_KEY 가 없다")
    client = GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL, google_api_key=key)

    out: list[list[float]] = []
    for i in range(0, len(texts), CHUNK):
        chunk = texts[i:i + CHUNK]
        print(f"  embedding {i + 1}-{i + len(chunk)} / {len(texts)}")
        out.extend(client.embed_documents(chunk))
    return np.asarray(out, dtype="float32")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(_HERE / ".env")
    ids, matrix = build(_gemini_embed)
    save(OUT, ids, matrix)
    print(f"wrote {OUT} — {matrix.shape[0]} vectors x {matrix.shape[1]} dims", file=sys.stderr)
```

- [ ] **Step 4: 통과를 확인한다**

```bash
cd backend && ./venv/bin/python -m pytest test_build_vectors.py -q
```
Expected: 4 passed

- [ ] **Step 5: 실제 배치는 크레딧이 있을 때만 돌린다**

```bash
cd backend && ./venv/bin/python build_vectors.py
```
Expected (크레딧 있음): `wrote .../course_vectors.npz — 125 vectors x 3072 dims`
Expected (지금): `429 RESOURCE_EXHAUSTED`. **이 경우 넘어간다** — Task 2가 파일 없음을 정상 경로로 처리한다.

- [ ] **Step 6: 커밋**

```bash
git add backend/build_vectors.py backend/test_build_vectors.py
git commit -m "Add the offline batch that embeds course purposes

One vector per course over its purpose alone. The description is a list of
places: it dilutes the purpose signal, and places are already handled by the
region filter.

Vectors are L2-normalised at build time so search is a single dot product.
The embedding function is a parameter, so the batch is testable without
spending quota.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: 인텍스트 — `region` 빼고 `purpose` 넣기

**Files:**
- Modify: `backend/graph.py:74-141` (`FIELD_LABELS`, `FIELD_QUESTIONS`, `FIELD_ORDER`, `FIELD_EXTRACT`), `graph.py:_recommend_region`, `graph.py:_store`
- Modify: `backend/state.py`
- Modify: `backend/test_one_at_a_time_intake.py` (슬롯 목록을 쓰는 단언)

**Interfaces:**
- Consumes: 없음
- Produces: `state["purpose"]` (사용자 문장 원문 또는 `""`), `FIELD_ORDER == ["travel_dates","category","companion","pace","restrictions","purpose"]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/test_intake_purpose.py`:

```python
"""인텍스트 슬롯 변경 — region 이 빠지고 purpose 가 들어온다."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import graph  # noqa: E402


def test_region_is_no_longer_asked():
    assert "region" not in graph.FIELD_ORDER
    assert "region" not in graph.FIELD_QUESTIONS


def test_purpose_is_asked_last():
    assert graph.FIELD_ORDER[-1] == "purpose"
    assert len(graph.FIELD_ORDER) == 6


def test_purpose_is_stored_verbatim_not_normalised():
    out = graph._store("purpose", "travelling with my mother for the first time", {})
    assert out == {"purpose": "travelling with my mother for the first time"}


def test_skipping_purpose_leaves_it_empty():
    assert graph._store("purpose", "MISSING", {}) == {"purpose": ""}
    assert graph._store("purpose", "", {}) == {"purpose": ""}
```

- [ ] **Step 2: 실패를 확인한다**

```bash
cd backend && ./venv/bin/python -m pytest test_intake_purpose.py -q
```
Expected: FAIL — `assert 'region' not in [...]`

- [ ] **Step 3: `graph.py`를 고친다**

`FIELD_LABELS`에서 `"region"` 줄을 지우고 그 자리에 넣는다:

```python
    "purpose":      "Trip Purpose",
```

`FIELD_QUESTIONS`에서 `"region"` 줄을 지우고 넣는다:

```python
    # 자유 서술이다. 라벨로 정규화하지 않는다 — 뭉개면 임베딩할 게 없어진다.
    # 이 문장이 코스 purpose 와의 유사도 순위를 정한다.
    "purpose":      "Last one -- what's this trip for? (e.g. 'first time with my "
                    "parents', 'a free afternoon on a work trip') Or tap skip.",
```

`FIELD_ORDER`를 통째로 교체한다:

```python
# 한 턴에 한 필드씩 묻는 순서. purpose 가 마지막인 이유는 앞의 다섯 답이 목적을
# 안 적었을 때 쓸 합성 문장의 재료이기 때문이다 (planner._synth_purpose).
# region 은 여기 없다 — 날짜마다 다른 게 정상이라 Day Planner 화면이 받는다.
FIELD_ORDER = ["travel_dates", "category", "companion", "pace", "restrictions", "purpose"]
```

`FIELD_EXTRACT`에서 `"region"` 항목을 지우고 넣는다:

```python
    "purpose":      'purpose: the traveller\'s own words for what this trip is for, '
                    'copied verbatim and translated to English if needed. Do NOT '
                    'summarise into a category. "MISSING" if they skipped, declined, '
                    'or did not answer.',
```

`FIELD_EXTRACT["category"]`에서 복수 허용 문구를 지운다 (칩이 단일 선택이다):

```python
                    # 'Comma-separated if multiple. ' 를 삭제
```

`_CATEGORY_REGIONS` 상수와 `_recommend_region`, `_parse_regions` 함수를 삭제한다.

`_store`에서 `region` 분기를 지우고 `purpose` 분기를 넣는다:

```python
def _store(field: str, raw: str, state: TravelState) -> dict:
    """Turn one extracted value into the state update for its slot."""
    value = (raw or "").strip()

    if field == "purpose":
        # 건너뛰기는 정상 경로다. 빈 문자열로 두면 planner 가 다른 슬롯으로
        # 문장을 합성한다 — 목적을 적는 사람이 소수라서 그쪽이 다수 경로다.
        return {"purpose": "" if not value or value.upper() == "MISSING" else value}

    if not value or value.upper() == "MISSING":
        return {}

    return {field: value}
```

`state.py`의 `region` 줄을 교체한다:

```python
    purpose: Optional[str]             # 여행 목적. 사용자 문장 원문 또는 "" (건너뜀).
                                        # retrieval 의 유사도 질의로 쓰인다.
    day_specs: Optional[list[dict[str, Any]]]  # [{day, region, interest}] — Day Planner
                                        # 화면이 정하고 POST /day-plan 이 쓴다.
                                        # day_plan 단계 진입 시 서버가 기본값을 채운다.
```

`state.py`의 `current_step` 주석에 `day_plan`을 넣는다:

```python
    current_step: str                  # start | collecting | day_plan | confirm | retrieving | planning | critic | done
```

- [ ] **Step 4: 통과를 확인한다**

```bash
cd backend && ./venv/bin/python -m pytest test_intake_purpose.py -q
```
Expected: 4 passed

- [ ] **Step 5: 기존 인텍스트 테스트를 고친다**

```bash
cd backend && ./venv/bin/python -m pytest test_one_at_a_time_intake.py -q
```
`region`을 기대하는 단언이 있으면 `purpose`로 바꾸고, 질문 순서를 세는 곳은 6으로 맞춘다. `_recommend_region`을 부르는 테스트가 있으면 삭제한다.

- [ ] **Step 6: 전체 회귀**

```bash
cd backend && ./venv/bin/python -m pytest -q --ignore=test_reorder_supplements.py --ignore=test_checkin_store.py
```
Expected: 전부 통과

- [ ] **Step 7: 커밋**

```bash
git add backend/graph.py backend/state.py backend/test_intake_purpose.py backend/test_one_at_a_time_intake.py
git commit -m "Ask what the trip is for; stop asking for one region

Region left intake because it is not a trip-level fact — three days rarely
share one district, and parse_day_segments was guessing the split from the
count of areas the traveller happened to name.

Purpose takes its turn. It is stored verbatim: normalising it into a label
would leave nothing to embed, and the whole point is to catch what five
labels cannot ('a free afternoon on a work trip').

Skipping is a normal answer, not a failure. Most travellers will skip, and
the planner synthesises a sentence from the other five slots for them.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: `day_specs` 기본값과 `POST /day-plan`

**Files:**
- Modify: `backend/graph.py` (`_ask`, `route_entry`, `_after_collect`, `default_day_specs` 추가)
- Modify: `backend/api.py` (`StateResponse`, `_state_response` 헬퍼, `POST /day-plan`)
- Test: `backend/test_day_plan.py`

**Interfaces:**
- Consumes: `retrieval.DAY_PLAN_REGION_ORDER`, Task 4의 `state["purpose"]`
- Produces:
  - `graph.default_day_specs(state) -> list[dict]`
  - `POST /day-plan` — body `{thread_id, days: [{day, region, interest}]}` → `StateResponse`
  - `StateResponse.purpose: str | None`, `StateResponse.day_specs: list[dict] | None`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/test_day_plan.py`:

```python
"""day_specs 기본값과 POST /day-plan."""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))

import graph  # noqa: E402
from api import app  # noqa: E402

client = TestClient(app)
THREAD = "test-day-plan-0123456789"


def test_defaults_give_each_day_a_different_region():
    specs = graph.default_day_specs({"travel_dates": "June 1, 2026 to June 3, 2026 (3 days)",
                                     "category": "Shopping"})
    assert [s["day"] for s in specs] == [1, 2, 3]
    assert len({s["region"] for s in specs}) == 3
    assert all(s["interest"] == "Shopping" for s in specs)


def test_defaults_cover_a_seven_day_trip():
    specs = graph.default_day_specs({"travel_dates": "June 1, 2026 to June 7, 2026 (7 days)",
                                     "category": "Culture & History"})
    assert len(specs) == 7
    assert len({s["region"] for s in specs}) == 7


def test_defaults_fall_back_to_culture_when_no_interest_was_given():
    specs = graph.default_day_specs({"travel_dates": "June 1, 2026 (1 day)", "category": None})
    assert specs[0]["interest"] == "Culture & History"


def _seed(days=3, interest="Shopping"):
    """day_plan 단계의 스레드를 만든다."""
    client.post("/reset", params={"thread_id": THREAD})
    from api import _config, _graph
    label = f"June 1, 2026 to June {days}, 2026 ({days} days)"
    _graph.update_state(_config(THREAD), {
        "travel_dates": label, "category": interest, "current_step": "day_plan",
        "day_specs": graph.default_day_specs({"travel_dates": label, "category": interest}),
    })


def test_state_returns_the_defaults():
    _seed()
    body = client.get("/state", params={"thread_id": THREAD}).json()
    assert body["current_step"] == "day_plan"
    assert len(body["day_specs"]) == 3


def test_posting_a_plan_stores_it_and_advances_to_confirm():
    _seed()
    days = [{"day": 1, "region": "hongdae", "interest": "Food & Cafes"},
            {"day": 2, "region": "seongsu", "interest": "Shopping"},
            {"day": 3, "region": "jongno", "interest": "Culture & History"}]
    r = client.post("/day-plan", json={"thread_id": THREAD, "days": days})
    assert r.status_code == 200
    assert r.json()["current_step"] == "confirm"
    assert client.get("/state", params={"thread_id": THREAD}).json()["day_specs"] == days


@pytest.mark.parametrize("days,why", [
    ([{"day": 1, "region": "hongdae", "interest": "Shopping"}], "길이 불일치"),
    ([{"day": 1, "region": "atlantis", "interest": "Shopping"},
      {"day": 2, "region": "jongno", "interest": "Shopping"},
      {"day": 3, "region": "jongno", "interest": "Shopping"}], "없는 지역"),
    ([{"day": 1, "region": "jongno", "interest": "Beauty"},
      {"day": 2, "region": "jongno", "interest": "Shopping"},
      {"day": 3, "region": "jongno", "interest": "Shopping"}], "어휘 밖 관심사"),
    ([{"day": 1, "region": "jongno", "interest": "Shopping"},
      {"day": 1, "region": "jongno", "interest": "Shopping"},
      {"day": 3, "region": "jongno", "interest": "Shopping"}], "day 중복"),
])
def test_bad_plans_are_rejected(days, why):
    _seed()
    r = client.post("/day-plan", json={"thread_id": THREAD, "days": days})
    assert r.status_code == 400, why
```

- [ ] **Step 2: 실패를 확인한다**

```bash
cd backend && ./venv/bin/python -m pytest test_day_plan.py -q
```
Expected: FAIL — `AttributeError: module 'graph' has no attribute 'default_day_specs'`

- [ ] **Step 3: `graph.py`에 기본값 생성과 라우팅을 넣는다**

import에 추가:

```python
from retrieval import DAY_PLAN_REGION_ORDER
```

`_ask` 위에 추가:

```python
DEFAULT_INTEREST = "Culture & History"


def default_day_specs(state: TravelState) -> list[dict[str, Any]]:
    """day_plan 단계에 들어가는 순간 채워 넣는 날짜별 기본값.

    화면은 이 값을 GET /state 로 읽어 보여주기만 한다. 기본값 로직을 서버와
    화면 양쪽에 두면 반드시 어긋나므로 여기 한 곳에만 둔다. 그리고 day_specs 가
    항상 존재하므로 "비어 있을 때" 라는 분기가 생기지 않는다.

    지역은 코스 풀이 넓은 곳부터 서로 다르게 배분한다 — 그대로 두어도 권역이
    다양한 무난한 여행이 된다. 관심사는 채팅에서 답한 값을 모든 날에 깐다.
    """
    from rag import _parse_num_days

    days = _parse_num_days(state.get("travel_dates"))
    interest = (state.get("category") or "").strip() or DEFAULT_INTEREST
    order = DAY_PLAN_REGION_ORDER
    return [
        {"day": i + 1, "region": order[i % len(order)], "interest": interest}
        for i in range(days)
    ]
```

`_ask`의 `field is None` 분기를 교체한다:

```python
    if field is None:
        return {
            **state, **updates,
            "pending": None,
            "current_step": "day_plan",
            "day_specs": default_day_specs({**state, **updates}),
            "messages": [AIMessage(content=(
                "Got it. Now pick an area and a focus for each day -- "
                "I've filled in a starting point you can change."
            ))],
        }
```

`route_entry`에 분기를 추가한다 (`if step == "confirm":` 바로 위):

```python
    if step == "day_plan":
        # 화면이 POST /day-plan 으로 넘어가기 전까지는 그래프가 할 일이 없다.
        return END
```

`_after_collect`를 교체한다:

```python
def _after_collect(state: TravelState) -> str:
    # 마지막 질문에 답하면 day_plan 으로 넘어간다. 그래프는 여기서 멈추고,
    # 다음 진입은 POST /day-plan 이 current_step 을 confirm 으로 옮긴 뒤다.
    return END
```

`builder.add_conditional_edges("collect", ...)`의 매핑을 `{END: END}`로 줄인다:

```python
    builder.add_conditional_edges("collect", _after_collect, {END: END})
```

- [ ] **Step 4: `api.py`에 엔드포인트를 넣는다**

`StateResponse`에서 `region` 줄을 지우고 추가한다:

```python
    purpose: Optional[str] = None
    day_specs: Optional[list[dict]] = None
```

`StateResponse(...)`를 세 군데에서 직접 만들던 것을 헬퍼로 모은다. `_latest_ai_message` 아래에 추가:

```python
def _state_response(state: dict, *, reply: Optional[str] = None) -> StateResponse:
    """StateResponse 를 만드는 유일한 곳. 필드가 늘 때마다 세 군데를 고치던 걸 막는다."""
    return StateResponse(
        travel_dates=state.get("travel_dates"),
        category=state.get("category"),
        restrictions=state.get("restrictions"),
        companion=state.get("companion"),
        pace=state.get("pace"),
        purpose=state.get("purpose"),
        day_specs=state.get("day_specs"),
        current_step=state.get("current_step", "start"),
        current_field=state.get("pending"),
        confirmed=state.get("confirmed", False),
        reply=reply if reply is not None else _latest_ai_message(state),
        itinerary=state.get("itinerary"),
    )
```

`chat`의 세 `StateResponse(...)` 블록을 각각 `_state_response(state, reply=_BLOCKED_REPLY)`, `_state_response(new_state)`로, `get_state`의 것을 `_state_response(state)`로 바꾼다.

`_get_state`의 기본 dict 에서 `"region": None`을 지우고 `"purpose": None, "day_specs": None`을 넣는다.

`/reset` 아래에 추가:

```python
class DaySpec(BaseModel):
    day: int
    region: str
    interest: str


class DayPlanRequest(BaseModel):
    thread_id: str
    days: list[DaySpec]


@app.post("/day-plan", response_model=StateResponse)
def day_plan(req: DayPlanRequest):
    """Day Planner 화면이 정한 날짜별 지역·관심사를 저장하고 confirm 으로 넘긴다.

    어휘가 어긋나면 400 으로 시끄럽게 실패한다. retrieval 의 필터는 문자열
    비교라서, 통과시키면 조용히 0개를 반환하고 그날 앵커가 사라진다.
    """
    from geo import SEOUL_AREA_CENTERS
    from graph import INTEREST_LABELS
    from rag import _parse_num_days

    thread_id = _require_thread_id(req.thread_id)
    state = _get_state(thread_id)

    expected = _parse_num_days(state.get("travel_dates"))
    days = [d.model_dump() for d in req.days]

    if len(days) != expected:
        raise HTTPException(status_code=400, detail=f"expected {expected} days, got {len(days)}")
    if sorted(d["day"] for d in days) != list(range(1, expected + 1)):
        raise HTTPException(status_code=400, detail="day numbers must be 1..N with no gaps or repeats")
    for d in days:
        if d["region"] not in SEOUL_AREA_CENTERS:
            raise HTTPException(status_code=400, detail=f"unknown region: {d['region']}")
        if d["interest"] not in INTEREST_LABELS:
            raise HTTPException(status_code=400, detail=f"unknown interest: {d['interest']}")

    days.sort(key=lambda d: d["day"])
    _graph.update_state(_config(thread_id), {"day_specs": days, "current_step": "confirm"})
    return _state_response(_get_state(thread_id))
```

`graph.py`에 어휘 상수를 추가한다 (`FIELD_EXTRACT` 위):

```python
# 앱의 관심사 어휘. FIELD_EXTRACT["category"], Flutter 칩,
# course_descriptions.json 의 interests 가 전부 이 문자열을 그대로 쓴다.
INTEREST_LABELS = [
    "Culture & History", "Food & Cafes", "Shopping",
    "K-POP & Hallyu", "Nature & Relaxation",
]
```

- [ ] **Step 5: 통과를 확인한다**

```bash
cd backend && ./venv/bin/python -m pytest test_day_plan.py -q
```
Expected: 9 passed

- [ ] **Step 6: 전체 회귀**

```bash
cd backend && ./venv/bin/python -m pytest -q --ignore=test_reorder_supplements.py --ignore=test_checkin_store.py
```

- [ ] **Step 7: 커밋**

```bash
git add backend/graph.py backend/api.py backend/test_day_plan.py
git commit -m "Let the traveller set a region and focus for each day

The server fills day_specs the moment intake ends, so the screen only
displays and edits them. Putting the defaults in both places would drift,
and having them always present removes the 'what if it is empty' branch —
nothing is ever decided silently behind the traveller.

POST /day-plan rejects an unknown region or interest with a 400. The filters
compare strings, so a value that is merely close returns zero courses and
loses that day's anchor without saying anything.

Also collapses the three hand-copied StateResponse constructions into one
helper; adding a field had meant editing all three.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: `retrieve_node` 배선과 `rag.py` 정리

**Files:**
- Modify: `backend/planner.py:1737-1770` (`make_retrieve_node`), `planner.py:1772+` (`plan_node`의 `requested_areas`)
- Modify: `backend/rag.py` (FAISS·구간분할·dead code 제거)
- Test: `backend/test_retrieve_node.py`

**Interfaces:**
- Consumes: `retrieval.select_anchors`, `retrieval.load_vectors`, `retrieval.base_id`, `state["day_specs"]`, `state["purpose"]`
- Produces: `planner._synth_purpose(state) -> str`, `state["day_segments"]` (`[{day_numbers, area, purpose_hint, anchor_courses}]` — 기존 프롬프트 포매터가 읽는 모양 그대로)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/test_retrieve_node.py`:

```python
"""retrieve_node — day_specs 로 하루씩 앵커를 고른다. 임베딩 없이."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import planner  # noqa: E402


BASE = {
    "travel_dates": "June 1, 2026 to June 3, 2026 (3 days)",
    "category": "Culture & History",
    "companion": "family", "pace": "relaxed", "restrictions": "none",
    "purpose": "",
    "day_specs": [
        {"day": 1, "region": "jongno", "interest": "Culture & History"},
        {"day": 2, "region": "hongdae", "interest": "Shopping"},
        {"day": 3, "region": "seongsu", "interest": "Food & Cafes"},
    ],
}


def test_each_day_gets_its_own_segment_with_anchors():
    node = planner.make_retrieve_node("")
    out = node(dict(BASE))
    segs = out["day_segments"]
    assert [s["day_numbers"] for s in segs] == [[1], [2], [3]]
    assert all(len(s["anchor_courses"]) == 3 for s in segs)
    assert out["current_step"] == "planning"


def test_anchors_respect_the_region_of_that_day():
    from retrieval import _in_region
    node = planner.make_retrieve_node("")
    segs = node(dict(BASE))["day_segments"]
    for seg, want in zip(segs, ["jongno", "hongdae", "seongsu"]):
        assert all(_in_region(c, want) for c in seg["anchor_courses"])


def test_days_do_not_share_a_base_course():
    from retrieval import base_id
    node = planner.make_retrieve_node("")
    segs = node(dict(BASE))["day_segments"]
    per_day = [{base_id(c["course_id"]) for c in s["anchor_courses"]} for s in segs]
    assert not (per_day[0] & per_day[1])


def test_synthesises_a_purpose_when_the_traveller_skipped_it():
    text = planner._synth_purpose(BASE)
    assert "relaxed" in text and "family" in text and "Culture & History" in text


def test_uses_the_traveller_sentence_when_they_wrote_one():
    assert planner._synth_purpose({**BASE, "purpose": "my mother's first trip"}) == \
        "my mother's first trip"
```

- [ ] **Step 2: 실패를 확인한다**

```bash
cd backend && ./venv/bin/python -m pytest test_retrieve_node.py -q
```
Expected: FAIL — `AttributeError: module 'planner' has no attribute '_synth_purpose'`

- [ ] **Step 3: `planner.py`를 고친다**

import에서 `parse_day_segments`, `retrieve_for_segments`, `build_query`를 지우고 남긴다:

```python
from rag import _parse_num_days
from retrieval import base_id, load_vectors, select_anchors
```

`make_retrieve_node` 위에 추가:

```python
def _synth_purpose(state: TravelState) -> str:
    """사용자가 목적을 적었으면 그 문장, 아니면 다른 슬롯으로 한 문장을 만든다.

    목적을 적는 사람은 소수라 이쪽이 다수 경로다. 그리고 이 합성이 companion 과
    pace 를 검색에 처음 쓰이게 한다 — 지금까지 두 슬롯은 수집만 되고 순위에는
    한 번도 영향을 주지 않았다.
    """
    written = (state.get("purpose") or "").strip()
    if written:
        return written[:300]

    days = _parse_num_days(state.get("travel_dates"))
    pace = (state.get("pace") or "").strip().lower()
    companion = (state.get("companion") or "").strip().lower()
    interest = (state.get("category") or "").strip()

    pace_word = {"packed": "packed", "relaxed": "relaxed"}.get(pace, "")
    who = {
        "solo": "a solo traveller", "couple": "a couple",
        "friends": "a group of friends", "family": "a family with children",
    }.get(companion, "a traveller")

    parts = ["A"]
    if pace_word:
        parts.append(pace_word)
    parts.append(f"{days}-day trip for {who}")
    if interest:
        parts.append(f"focused on {interest.lower()}")
    return " ".join(parts) + "."
```

`make_retrieve_node`를 교체한다:

```python
def make_retrieve_node(api_key: str):
    set_planner_api_key(api_key)

    def retrieve_node(state: TravelState) -> TravelState:
        day_specs = state.get("day_specs") or []
        if not day_specs:
            return {
                "current_step": "confirm",
                "messages": [AIMessage(content="⚠️ No day plan found. Please set each day's area first.")],
            }

        vectors = load_vectors()
        query_vec = _embed_purpose(_synth_purpose(state)) if vectors else None

        segments, all_courses, used = [], [], set()
        seen_ids: set[str] = set()
        for spec in day_specs:
            sel = select_anchors(
                {**spec, "purpose_vec": query_vec}, exclude=used, vectors=vectors
            )
            if sel.relaxed:
                print(f"[retrieval] day {spec['day']} {spec['region']}/{spec['interest']}: {sel.relaxed}")
            used |= {base_id(c["course_id"]) for c in sel.courses}
            segments.append({
                "day_numbers": [spec["day"]],
                "area": spec["region"],
                "purpose_hint": spec["interest"],
                "anchor_courses": sel.courses,
            })
            for c in sel.courses:
                if c["course_id"] not in seen_ids:
                    seen_ids.add(c["course_id"])
                    all_courses.append(c)

        return {
            **state,
            "retrieved_courses": all_courses,
            "day_segments": segments,
            "current_step": "planning",
        }

    return retrieve_node


def _embed_purpose(text: str):
    """질의 임베딩. 일정 생성당 1회 — 모든 날이 같은 목적을 쓴다.

    실패하면 None 을 돌려 유사도 정렬만 건너뛴다. 예전에는 여기서 예외가 나면
    retrieve_node 가 통째로 죽어 대화가 멈췄다.
    """
    from build_vectors import EMBEDDING_MODEL, normalize
    import numpy as np

    try:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        client = GoogleGenerativeAIEmbeddings(
            model=EMBEDDING_MODEL, google_api_key=_PLANNER_GEMINI_KEY
        )
        vec = np.asarray(client.embed_query(text), dtype="float32")
        return normalize(vec.reshape(1, -1))[0]
    except Exception as e:
        print(f"[retrieval] query embedding failed ({type(e).__name__}) — filter-only")
        return None
```

`plan_node`의 `requested_areas` 계산을 교체한다:

```python
    # 날짜별 지역의 합집합. 예전에는 region 문자열에서 추출했는데, 이제 사용자가
    # 날마다 지정하므로 추측이 없다.
    requested_areas = list(dict.fromkeys(s["region"] for s in (state.get("day_specs") or [])))
    print(f"[planner] requested_areas = {requested_areas}")
```

`plan_node`의 `location` 변수를 교체한다 (`state.get("region")`이 사라졌다):

```python
    location = ", ".join(_area_label(a) for a in requested_areas)
```

- [ ] **Step 4: `rag.py`에서 죽은 것들을 지운다**

다음을 삭제한다: `build_or_load_vectorstore`, `_get_embeddings`, `_embed_documents_chunked`, `_embed_with_retry`, `_parse_retry_seconds`, `_course_to_text`, `_course_to_document`, `retrieve_courses`, `retrieve_for_segments`, `rerank_courses_by_area`, `parse_day_segments`, `segment_k`, `build_query`, `_extract_areas`, `_split_purpose_by_area`, `_load_courses`, staleness 경고 블록, `_vectorstore`/`_vectorstore_api_key` 전역, `EMBED_*` 상수, `VECTORSTORE_DIR`.

`from langchain_community.vectorstores import FAISS`, `from langchain_core.documents import Document`, `from langchain_google_genai import GoogleGenerativeAIEmbeddings`, `import sys` 를 지운다.

남는 것: `COURSE_DATA_PATH`, 날짜 파싱(`parse_trip_start_date`, `_parse_num_days`, `_days_from_date_range`, `_looks_like_single_date`, `_nearest_future`, `_resolve_weekday_phrase`)과 그 상수들.

모듈 docstring을 바꾼다:

```python
"""여행 날짜 파싱. 코스 검색은 retrieval.py 로 옮겼다.

이 파일은 FAISS 인덱스 빌드·임베딩 청크·구간 분할까지 들고 있었다. 그 중
검색에 해당하는 부분은 전부 retrieval.py 에 있고, 여기에는 자유 텍스트 날짜를
시작일과 일수로 바꾸는 코드만 남았다.
"""
```

- [ ] **Step 5: 통과와 회귀를 확인한다**

```bash
cd backend && ./venv/bin/python -m pytest test_retrieve_node.py -q
cd backend && ./venv/bin/python -m pytest -q --ignore=test_reorder_supplements.py --ignore=test_checkin_store.py
```
Expected: 전부 통과. `rag`의 지운 함수를 import 하던 테스트가 있으면 그 테스트도 함께 정리한다 (`test_retrieval_fixes.py`, `test_num_days_fix.py` 확인).

- [ ] **Step 6: 커밋**

```bash
git add backend/planner.py backend/rag.py backend/test_retrieve_node.py backend/test_retrieval_fixes.py backend/test_num_days_fix.py
git commit -m "Retrieve one day at a time from the plan the traveller set

retrieve_node now walks day_specs and calls select_anchors per day, passing
the base ids already used so two days do not share a backbone. The query
vector is embedded once per generation because every day shares the trip's
purpose.

When the traveller skipped the purpose question, a sentence is synthesised
from the other slots. That path is the common one, and it is the first time
companion and pace influence which courses come back at all.

A failed embedding no longer kills the turn — it drops the ranking and keeps
the filters, so an itinerary still comes out.

rag.py keeps only date parsing. Index building, embedding chunking, segment
splitting and build_query (which nothing called) are gone.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Flutter Day Planner 화면

**Files:**
- Modify: `lib/models/travel_state.dart`
- Modify: `lib/services/api_service.dart`
- Modify: `lib/data/api/api_chat_repository.dart` (`region` 칩 제거)
- Modify: `lib/routes/app_routes.dart`
- Modify: `lib/screens/chat/chat_screen.dart` (day_plan CTA)
- Create: `lib/screens/trip/day_planner_screen.dart`
- Test: `test/day_planner_test.dart`

**Interfaces:**
- Consumes: `GET /state`의 `day_specs`·`purpose`, `POST /day-plan`
- Produces: `DaySpec` 모델 (`day`, `region`, `interest`), `ApiService.postDayPlan(List<DaySpec>)`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`test/day_planner_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seoulfit_ui/models/travel_state.dart';
import 'package:seoulfit_ui/screens/trip/day_planner_screen.dart';

void main() {
  const seeded = [
    DaySpec(day: 1, region: 'jongno', interest: 'Shopping'),
    DaySpec(day: 2, region: 'myeongdong', interest: 'Shopping'),
    DaySpec(day: 3, region: 'hongdae', interest: 'Shopping'),
  ];

  Widget harness(List<DaySpec> specs, {ValueChanged<List<DaySpec>>? onSubmit}) =>
      MaterialApp(
        home: DayPlannerScreen(initial: specs, onSubmit: onSubmit ?? (_) {}),
      );

  testWidgets('opens with one row per day, already filled in', (tester) async {
    await tester.pumpWidget(harness(seeded));
    expect(find.text('Day 1'), findsOneWidget);
    expect(find.text('Day 3'), findsOneWidget);
    expect(find.text('Jongno'), findsOneWidget);
    expect(find.text('Shopping'), findsNWidgets(3));
  });

  testWidgets('a seven day trip shows seven rows', (tester) async {
    final week = List.generate(
      7, (i) => DaySpec(day: i + 1, region: 'jongno', interest: 'Shopping'));
    await tester.pumpWidget(harness(week));
    expect(find.textContaining('Day '), findsNWidgets(7));
  });

  testWidgets('submits what the rows currently hold', (tester) async {
    List<DaySpec>? sent;
    await tester.pumpWidget(harness(seeded, onSubmit: (v) => sent = v));

    await tester.tap(find.byKey(const ValueKey('interest-2')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Food & Cafes').last);
    await tester.pumpAndSettle();

    await tester.tap(find.text('Continue'));
    await tester.pumpAndSettle();

    expect(sent, isNotNull);
    expect(sent![1].interest, 'Food & Cafes');
    expect(sent![0].interest, 'Shopping');
  });
}
```

- [ ] **Step 2: 실패를 확인한다**

```bash
/opt/homebrew/bin/flutter test test/day_planner_test.dart
```
Expected: FAIL — `Error: Couldn't resolve the package 'day_planner_screen.dart'`

- [ ] **Step 3: 모델과 API 클라이언트를 고친다**

`lib/models/travel_state.dart`에서 `region` 필드를 지우고 추가한다:

```dart
/// One day's area and focus, as set on the Day Planner screen.
///
/// `region` is a geo.py key (lower case, e.g. 'jongno'), not a label —
/// the backend filters by exact string, so the two must not drift.
class DaySpec {
  const DaySpec({required this.day, required this.region, required this.interest});

  final int day;
  final String region;
  final String interest;

  factory DaySpec.fromJson(Map<String, dynamic> json) => DaySpec(
        day: json['day'] as int,
        region: json['region'] as String? ?? '',
        interest: json['interest'] as String? ?? '',
      );

  Map<String, dynamic> toJson() =>
      {'day': day, 'region': region, 'interest': interest};

  DaySpec copyWith({String? region, String? interest}) =>
      DaySpec(day: day, region: region ?? this.region, interest: interest ?? this.interest);
}

/// Region keys the app offers, with their display labels. Keys must exist in
/// geo.SEOUL_AREA_CENTERS or POST /day-plan rejects them with a 400.
const Map<String, String> kRegionLabels = {
  'jongno': 'Jongno',
  'myeongdong': 'Myeongdong',
  'hongdae': 'Hongdae',
  'gangnam': 'Gangnam',
  'seongsu': 'Seongsu',
  'itaewon': 'Itaewon',
  'bukchon': 'Bukchon',
  'insadong': 'Insadong',
  'mapo': 'Mapo',
  'dongdaemun': 'Dongdaemun',
  'sinchon': 'Sinchon',
  'apgujeong': 'Apgujeong',
};

/// The five interest labels, verbatim. Shared with graph.FIELD_EXTRACT and
/// each course's `interests` — the match is a string compare, not a score.
const List<String> kInterestLabels = [
  'Culture & History',
  'Food & Cafes',
  'Shopping',
  'K-POP & Hallyu',
  'Nature & Relaxation',
];
```

`TravelState`에 필드를 추가한다:

```dart
  final String? purpose;
  final List<DaySpec> daySpecs;
```

`fromJson`에 추가한다:

```dart
        purpose: json['purpose'] as String?,
        daySpecs: (json['day_specs'] as List<dynamic>? ?? const [])
            .map((e) => DaySpec.fromJson(e as Map<String, dynamic>))
            .toList(),
```

`lib/services/api_service.dart`에 추가한다:

```dart
  /// Stores the per-day plan and advances the thread to `confirm`.
  Future<TravelState> postDayPlan(List<DaySpec> days) async {
    final res = await _post('/day-plan', {
      'thread_id': _threadId,
      'days': days.map((d) => d.toJson()).toList(),
    });
    return TravelState.fromJson(res);
  }
```

`lib/data/api/api_chat_repository.dart`의 `_quickRepliesFor`에서 `case 'region':` 블록을 지운다. 그 자리에 넣는다:

```dart
    case 'purpose':
      // Free text is the point — a chip would collapse it back into a label.
      // Only the skip is offered.
      return const ['Skip'];
```

- [ ] **Step 4: 화면을 만든다**

`lib/screens/trip/day_planner_screen.dart`:

```dart
import 'package:flutter/material.dart';

import '../../models/travel_state.dart';
import '../../theme/theme.dart';

/// Picks an area and a focus for each day of the trip.
///
/// Opens already filled in: the backend writes defaults into `day_specs` the
/// moment intake ends, and this screen displays them. Continuing without
/// changing anything is a valid answer — most travellers will do exactly that.
class DayPlannerScreen extends StatefulWidget {
  const DayPlannerScreen({super.key, required this.initial, required this.onSubmit});

  final List<DaySpec> initial;
  final ValueChanged<List<DaySpec>> onSubmit;

  @override
  State<DayPlannerScreen> createState() => _DayPlannerScreenState();
}

class _DayPlannerScreenState extends State<DayPlannerScreen> {
  late List<DaySpec> _specs = List.of(widget.initial);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(title: const Text('Plan each day')),
      body: ListView.separated(
        padding: const EdgeInsets.all(AppSpacing.lg),
        itemCount: _specs.length,
        separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.md),
        itemBuilder: (context, i) => _DayRow(
          spec: _specs[i],
          index: i,
          onChanged: (s) => setState(() => _specs[i] = s),
        ),
      ),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: FilledButton(
            onPressed: () => widget.onSubmit(_specs),
            child: const Text('Continue'),
          ),
        ),
      ),
    );
  }
}

class _DayRow extends StatelessWidget {
  const _DayRow({required this.spec, required this.index, required this.onChanged});

  final DaySpec spec;
  final int index;
  final ValueChanged<DaySpec> onChanged;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        SizedBox(
          width: 56,
          child: Text('Day ${spec.day}', style: AppTextStyles.bodySmall),
        ),
        Expanded(
          child: DropdownButtonFormField<String>(
            key: ValueKey('region-$index'),
            initialValue: spec.region,
            isExpanded: true,
            items: [
              for (final e in kRegionLabels.entries)
                DropdownMenuItem(value: e.key, child: Text(e.value)),
            ],
            onChanged: (v) => v == null ? null : onChanged(spec.copyWith(region: v)),
          ),
        ),
        const SizedBox(width: AppSpacing.sm),
        Expanded(
          flex: 2,
          child: DropdownButtonFormField<String>(
            key: ValueKey('interest-$index'),
            initialValue: spec.interest,
            isExpanded: true,
            items: [
              for (final label in kInterestLabels)
                DropdownMenuItem(value: label, child: Text(label)),
            ],
            onChanged: (v) => v == null ? null : onChanged(spec.copyWith(interest: v)),
          ),
        ),
      ],
    );
  }
}
```

- [ ] **Step 5: 라우트와 CTA를 붙인다**

`lib/routes/app_routes.dart`에 `dayPlanner` 라우트를 추가하고, `lib/screens/chat/chat_screen.dart`에서 `readyToBuild`를 판단하던 자리 옆에 추가한다:

```dart
        // day_plan 단계에서는 일정 생성 대신 Day Planner 로 보낸다.
        if (messages.isNotEmpty && messages.last.awaitingStep == 'day_plan')
          _CtaButton(
            label: 'Plan each day',
            onPressed: () => Navigator.pushNamed(context, AppRoutes.dayPlanner),
          ),
```

`ChatMessage`에 `awaitingStep`을 추가하고 `_botMessage`에서 `state.currentStep`을 넣는다.

- [ ] **Step 6: 테스트와 정적 분석**

```bash
/opt/homebrew/bin/flutter test test/day_planner_test.dart
/opt/homebrew/bin/flutter analyze lib/
/opt/homebrew/bin/flutter test
```
Expected: 3 passed · `No issues found!` · 기존 Flutter 테스트 전부 통과

- [ ] **Step 7: 커밋**

```bash
git add lib/ test/day_planner_test.dart
git commit -m "Add the screen where each day gets its own area and focus

Asking this in chat would cost three questions a day — twenty-one turns for
a week, each one a Gemini round trip. A table is also what the traveller
wants to look back at; chat makes them scroll.

The rows arrive filled in from the server, so continuing is one tap and only
the days someone cares about need touching.

Region keys are geo.py keys, not labels. The backend filters by exact string
and answers a mismatch with a 400.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: FAISS 제거와 설명문 검증 CI 편입

**Files:**
- Delete: `backend/build_index.py`, `backend/vectorstore/index.faiss`, `backend/vectorstore/index.pkl`, `backend/dataset/course_descriptions.gold.json`
- Modify: `backend/requirements.txt`
- Create: `backend/test_descriptions.py`

**Interfaces:**
- Consumes: `scripts/validate_descriptions.py`의 `validate`
- Produces: 없음

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/test_descriptions.py`:

```python
"""125개 설명문 전수 검증을 CI 에 넣는다.

손으로 돌리던 스크립트였다. course_data_v6.json 을 고치면 설명문이 어긋나는데,
실제로 market 타입을 재분류했을 때 두 건이 깨졌다 — 그때는 우연히 돌려봐서 알았다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))

from validate_descriptions import DESCRIPTIONS, validate  # noqa: E402


def test_every_description_matches_its_course():
    assert validate(DESCRIPTIONS) == 0


def test_faiss_is_gone():
    import pathlib
    root = pathlib.Path(__file__).parent
    assert not (root / "vectorstore").exists()
    assert not (root / "build_index.py").exists()
    assert "faiss" not in (root / "requirements.txt").read_text()
```

- [ ] **Step 2: 실패를 확인한다**

```bash
cd backend && ./venv/bin/python -m pytest test_descriptions.py -q
```
Expected: FAIL — `assert not True` (vectorstore 가 아직 있다)

- [ ] **Step 3: 지운다**

```bash
cd /Users/jameslee/cj_final/seoulfit_ui
git rm -r backend/vectorstore backend/build_index.py backend/dataset/course_descriptions.gold.json
```

`backend/requirements.txt`에서 두 줄을 지우고:

```
# Vector store for the course RAG (rag.py loads vectorstore/index.faiss).
faiss-cpu>=1.8
```

대신 넣는다:

```
# retrieval.py 가 코스 벡터(dataset/course_vectors.npz)에 내적을 건다.
# 125개뿐이라 FAISS 같은 근사 탐색은 필요 없고, 필터가 남긴 부분집합에만
# 점수를 매겨야 하는데 그건 FAISS 가 못 하는 일이다.
numpy>=1.26
```

- [ ] **Step 4: 통과를 확인한다**

```bash
cd backend && ./venv/bin/python -m pytest test_descriptions.py -q
```
Expected: 2 passed

- [ ] **Step 5: 전체 회귀와 서버 기동**

```bash
cd backend && ./venv/bin/python -m pytest -q --ignore=test_reorder_supplements.py --ignore=test_checkin_store.py
cd backend && ./venv/bin/python -c "import api; print('imports clean')"
```
Expected: 전부 통과 · `imports clean`

- [ ] **Step 6: 커밋**

```bash
git add -A backend/
git commit -m "Drop FAISS and put description validation in the test run

The index pickled a full copy of every course alongside its vectors, so
editing course_data_v6.json left search reading the old data until someone
remembered to rebuild. Vectors alone cannot go stale that way.

validate_descriptions.py was a script people ran by hand. Retyping fourteen
markets as food markets broke two descriptions, and that was caught by
chance. Now it runs with the tests.

The gold file goes too: course_descriptions.json superseded it, and keeping
a second copy of ten entries in an older schema only invites drift.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## 자체 검토

**스펙 커버리지**

| 스펙 항목 | 태스크 |
|---|---|
| `retrieval.py` 필터 사다리·완화·중복 방지 | Task 1 |
| 유사도 정렬, 벡터 없을 때 폴백 | Task 2 |
| `build_vectors.py`, `.npz` | Task 3 |
| `purpose` 슬롯, `region` 제거, `_recommend_region` 삭제 | Task 4 |
| `day_specs` 기본값, `POST /day-plan`, 입력 검증, `day_plan` 단계 | Task 5 |
| `retrieve_node` 배선, 합성 문장, `requested_areas`, `rag.py` 정리 | Task 6 |
| Day Planner 화면, 모델, 라우트, CTA | Task 7 |
| FAISS 제거, `vectorstore/` 삭제, 설명문 검증 CI | Task 8 |
| `k = 3` | Task 1 `DEFAULT_K` |
| 목적 300자 절단 | Task 6 `_synth_purpose` |
| 임베딩 실패 시 필터 유지 | Task 6 `_embed_purpose` |

빠진 스펙 항목: **`npz` ids 와 설명문 id 불일치 경고.** Task 2의 `_rank`가 없는 id를
`missing`으로 뒤에 붙여 조용히 처리한다 — 스펙은 기동 시 경고를 요구했다.
Task 2 Step 3의 `load_vectors`에 다음을 추가한다:

```python
    ids = [str(x) for x in z["ids"]]
    from_desc = {c["course_id"] for c in load_courses()}
    if missing := from_desc - set(ids):
        print(f"[retrieval] {len(missing)} courses have no vector — "
              f"they will not be ranked. Re-run build_vectors.py")
    return ids, z["vectors"]
```

**플레이스홀더 스캔**: TBD/TODO 없음. 모든 코드 단계에 실제 코드가 들어 있다.

**타입 일관성**: `Selection(courses, relaxed, sims)`가 Task 1·2·6에서 같은 이름으로
쓰인다. `base_id`가 Task 1에서 정의되고 6에서 쓰인다. `DaySpec`의 필드명
(`day`/`region`/`interest`)이 Python `DaySpec` 모델(Task 5)과 Dart `DaySpec`
(Task 7), `default_day_specs`(Task 5)에서 동일하다. `INTEREST_LABELS`(Python,
Task 5)와 `kInterestLabels`(Dart, Task 7)가 같은 다섯 문자열을 담는다.

## 선행 조건과 순서

Task 1 → 2 → 3은 서로 독립적으로 리뷰 가능하지만 2가 1의 `select_anchors`를 고치므로
순서대로 간다. Task 4 → 5 → 6은 상태 스키마가 이어지므로 순서 고정. Task 7은 Task 5의
API가 있어야 하고, Task 8은 Task 6이 `rag.py`의 FAISS 사용을 없앤 뒤여야 한다.

**Gemini 크레딧**은 Task 3 Step 5(실제 배치)에서만 필요하다. 없으면 그 단계를 건너뛰고
계속 간다 — Task 2가 벡터 파일 부재를 정상 경로로 처리하고, Task 6의 테스트는 전부
`vectors=None` 경로를 탄다. 크레딧이 들어오면 `build_vectors.py` 한 번으로 순위가 켜진다.
