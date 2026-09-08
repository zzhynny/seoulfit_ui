"""코스 설명문 검증 — 배치로 생성한 description 이 데이터와 맞는지 확인한다.

    python backend/scripts/validate_descriptions.py                     # gold 파일 검증
    python backend/scripts/validate_descriptions.py path/to/other.json   # 배치 산출물 검증
    python backend/scripts/validate_descriptions.py --demo               # 자체 점검

설명문은 사람이 126개를 읽어서 검증할 수 없다. 그래서 기계가 잡을 수 있는 것만
잡는다 — 없는 장소를 지어냈는지, 약점을 빼먹었는지, 홍보 문구를 썼는지.

핵심은 caveats 다. LLM 이 "다양한 비건 옵션" 같은 문장을 쓰는 걸 프롬프트로 막는
건 못 미덥다. 대신 코스의 약점을 코드가 계산해서, 설명문이 그걸 caveats 에
빠짐없이 신고했는지 확인한다. 신고 안 하면 실패다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from geo import infer_area_from_fields  # noqa: E402

COURSE_DATA = _BACKEND / "dataset" / "course_data_v6.json"
GOLD = _BACKEND / "dataset" / "course_descriptions.gold.json"

MEAL_TYPES = {"restaurant", "cafe", "market"}

# 임계값. 설명문 문체가 아니라 코스 자체의 성질을 재는 값이라 여기 모아둔다.
AREA_HEAVY_RATIO = 0.30   # is_area_type 비율 — 이 위면 '장소'가 아니라 '동네' 코스
GEO_SCATTER_MIN = 3       # 하루에 걸치는 권역 수
THIN_DAY_MAX = 3          # 하루 POI 수
OVERLONG_HOURS = 11.0     # 하루 체류시간 합계
DESC_MIN, DESC_MAX = 80, 700

# 홍보 문구. 임베딩 검색에서 이런 단어는 신호가 아니라 잡음이다 — 어느 코스에나
# 붙을 수 있어서 코스를 구분해주지 못한다.
MARKETING = [
    "감성", "힙한", "완벽한", "최고의", "놓칠 수 없", "필수 코스", "인생샷",
    "강추", "매력적", "환상적", "잊지 못할", "빼놓을 수 없", "그야말로",
    "must-see", "must-visit", "hidden gem", "perfect for", "stunning",
    "breathtaking", "unforgettable", "vibrant", "charming",
]

VOCAB = {
    "persona": {"first_timer", "repeat_visitor", "local_style", "family_kids", "couple",
                "mother_daughter", "solo", "friends", "pet_owner", "business",
                "backpacker", "student"},
    "constraints": {"halal", "vegan", "vegetarian", "budget", "luxury", "wheelchair", "no_alcohol"},
    "visit_stage": {"first", "repeat", "local", "any"},
    "activity_style": {"관람형", "체험형", "도보중심", "실내중심", "야간", "쇼핑중심", "미식중심"},
    "caveats": {"no_meal", "area_heavy", "geo_scatter", "thin_day", "overlong_day",
                "unmapped_area", "generic_activity", "kpop_tag_mismatch", "constraint_unsupported"},
}


# ---------------------------------------------------------------------------
# 데이터 쪽 계산 — LLM 이 아니라 여기서 나온 값이 기준이 된다
# ---------------------------------------------------------------------------

def base_id(course_id: str) -> str:
    return re.sub(r"_DAY.*$", "", course_id)


def name_variants(poi_name: str) -> list[str]:
    """'Seoul Forest (서울숲)' -> ['Seoul Forest (서울숲)', 'Seoul Forest', '서울숲']"""
    out = [poi_name.strip()]
    m = re.match(r"^(.*?)\s*\((.+)\)\s*$", poi_name.strip())
    if m:
        out += [m.group(1).strip(), m.group(2).strip()]
    return [v for v in out if v]


def poi_area(p: dict) -> str | None:
    return infer_area_from_fields(
        name=p.get("poi_name", ""),
        address=p.get("address_en") or p.get("address_ko") or "",
        lat=p.get("lat"), lng=p.get("lng"),
    )


def compute_facts(days: list[dict]) -> dict:
    """원본 코스(하루짜리면 1개) 기준 사실 + caveat 코드."""
    pois = [p for d in days for p in d["sequence"]]
    n = len(pois)
    areas = {a for p in pois if (a := poi_area(p))}
    unmapped = sum(1 for p in pois if not poi_area(p))
    area_type = sum(1 for p in pois if p.get("is_area_type"))
    themes = set(days[0].get("theme_category") or [])

    caveats: set[str] = set()
    if not any(p["poi_type"] in MEAL_TYPES for p in pois):
        caveats.add("no_meal")
    if n and area_type / n >= AREA_HEAVY_RATIO:
        caveats.add("area_heavy")
    if unmapped and unmapped / n >= 0.5:
        caveats.add("unmapped_area")
    if any(p.get("is_generic_activity") for p in pois):
        caveats.add("generic_activity")
    if "K-POP" in themes and not any(p["poi_type"] == "kpop_landmark" for p in pois):
        caveats.add("kpop_tag_mismatch")

    # 하루 단위 판정 — 멀티데이는 하루라도 걸리면 코스 전체에 붙인다.
    for d in days:
        seq = d["sequence"]
        if len(seq) <= THIN_DAY_MAX:
            caveats.add("thin_day")
        if len({a for p in seq if (a := poi_area(p))}) >= GEO_SCATTER_MIN:
            caveats.add("geo_scatter")
        mins = sum(int(p.get("estimated_stay_time") or 0) for p in seq)
        if mins / 60 > OVERLONG_HOURS:
            caveats.add("overlong_day")

    return {
        "days": len(days), "pois": n, "areas": areas,
        "hours": sum(int(p.get("estimated_stay_time") or 0) for p in pois) / 60,
        "has_meal": "no_meal" not in caveats,
        "caveats": caveats,
        "names": {v for p in pois for v in name_variants(p["poi_name"])},
    }


def load_courses(path: Path = COURSE_DATA) -> dict[str, dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    grouped: dict[str, list[dict]] = {}
    for c in raw:
        grouped.setdefault(base_id(c["course_id"]), []).append(c)
    for v in grouped.values():
        v.sort(key=lambda c: c["course_id"])
    return {k: compute_facts(v) for k, v in grouped.items()}


def build_gazetteer(path: Path = COURSE_DATA) -> dict[str, set[str]]:
    """장소명 -> 그 이름을 가진 코스들. 짧은 이름은 오탐이 나므로 뺀다."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    gaz: dict[str, set[str]] = {}
    for c in raw:
        for p in c["sequence"]:
            for v in name_variants(p["poi_name"]):
                # 한글 3자 / 영문 6자 미만은 다른 단어에 우연히 걸린다.
                if len(v) < (3 if re.search(r"[가-힣]", v) else 6):
                    continue
                gaz.setdefault(v, set()).add(base_id(c["course_id"]))
    return gaz


# ---------------------------------------------------------------------------
# 검증
# ---------------------------------------------------------------------------

def check_one(entry: dict, facts: dict, gaz: dict[str, set[str]], cid: str) -> list[str]:
    errs: list[str] = []
    desc = entry.get("description_search") or ""

    if not desc:
        return ["description_search 없음"]
    if not (DESC_MIN <= len(desc) <= DESC_MAX):
        errs.append(f"길이 {len(desc)}자 — {DESC_MIN}~{DESC_MAX} 밖")

    # 1. 없는 장소를 지어냈는가. 다른 코스 소유의 이름이 등장하면 실패다.
    own = facts["names"]
    for term, owners in gaz.items():
        if term not in desc:
            continue
        # 이 코스의 이름과 겹치면(부분 문자열 어느 방향이든) 통과.
        if cid in owners or any(term in o or o in term for o in own):
            continue
        errs.append(f"이 코스에 없는 장소를 언급: '{term}' (실제 소유: {', '.join(sorted(owners)[:2])})")

    # 2. 홍보 문구
    for w in MARKETING:
        if w.lower() in desc.lower():
            errs.append(f"홍보 문구: '{w}'")

    # 3. 어휘 검사
    for field in ("persona", "constraints", "activity_style", "caveats"):
        bad = set(entry.get(field) or []) - VOCAB[field]
        if bad:
            errs.append(f"{field} 어휘 밖: {sorted(bad)}")
    if entry.get("visit_stage") not in VOCAB["visit_stage"]:
        errs.append(f"visit_stage 어휘 밖: {entry.get('visit_stage')!r}")

    # 4. anchor_areas 는 실제 추정 지역의 부분집합
    extra = set(entry.get("anchor_areas") or []) - facts["areas"]
    if extra:
        errs.append(f"anchor_areas 에 실제로 없는 지역: {sorted(extra)}")

    # 5. 일수
    if entry.get("best_for_days") and facts["days"] > 1 and entry["best_for_days"] != facts["days"]:
        errs.append(f"best_for_days {entry['best_for_days']} != 실제 DAY {facts['days']}개")
    if (days_txt := entry.get("days")) and len(days_txt) != facts["days"]:
        errs.append(f"days 항목 {len(days_txt)}개 != 실제 DAY {facts['days']}개")

    # 6. caveats — 계산된 것이 전부 신고돼야 한다. 이게 이 스크립트의 핵심.
    declared = set(entry.get("caveats") or [])
    expected = set(facts["caveats"])
    # 제약을 걸어놓고 그 제약을 받쳐줄 식사 장소가 없으면 별도로 잡는다.
    if set(entry.get("constraints") or []) & {"halal", "vegan", "vegetarian"} and not facts["has_meal"]:
        expected.add("constraint_unsupported")
    if missing := expected - declared:
        errs.append(f"caveats 누락: {sorted(missing)}")
    if bogus := declared - expected - {"constraint_unsupported"}:
        errs.append(f"caveats 과잉 신고: {sorted(bogus)}")

    # 7. no_meal 이면 설명문이 그 사실을 말해야 한다.
    if "no_meal" in expected and not re.search(r"식사|식당|끼니|먹", desc):
        errs.append("식사 장소가 없는데 설명문이 언급하지 않음")

    return errs


def validate(path: Path) -> int:
    facts_by_id = load_courses()
    gaz = build_gazetteer()
    doc = json.loads(path.read_text(encoding="utf-8"))
    entries = doc.get("courses") if isinstance(doc, dict) else doc

    total = failed = 0
    for entry in entries:
        cid = entry.get("course_id", "")
        total += 1
        facts = facts_by_id.get(cid)
        if not facts:
            print(f"✗ {cid}: course_data_v6.json 에 없는 course_id")
            failed += 1
            continue
        errs = check_one(entry, facts, gaz, cid)
        if errs:
            failed += 1
            print(f"✗ {cid}")
            for e in errs:
                print(f"    - {e}")
        else:
            print(f"✓ {cid}  {facts['days']}일 · POI {facts['pois']} · "
                  f"{facts['hours']:.1f}h · caveats {len(facts['caveats'])}")

    print(f"\n{total - failed}/{total} 통과" + (f" — {failed}개 실패" if failed else ""))
    return 1 if failed else 0


# ---------------------------------------------------------------------------

def demo() -> None:
    """자체 점검 — 일부러 틀린 항목이 잡히는지 본다."""
    facts_by_id = load_courses()
    gaz = build_gazetteer()

    f = facts_by_id["VK_THEME_041"]
    assert "thin_day" in f["caveats"], "POI 3개짜리인데 thin_day 가 안 붙었다"
    assert "no_meal" in f["caveats"], "식당이 없는데 no_meal 이 안 붙었다"

    f8 = facts_by_id["VK_THEME_008"]
    assert "geo_scatter" in f8["caveats"] and "overlong_day" in f8["caveats"]

    f2 = facts_by_id["VK_THEME_002"]
    assert "kpop_tag_mismatch" in f2["caveats"], "K-POP 태그인데 kpop POI 가 없다"

    good = {
        "course_id": "VK_THEME_041",
        "description_search": "반려견과 갈 수 있는 야외 공간 세 곳이다. " * 3 + "식사 장소는 없다.",
        "persona": ["pet_owner"], "constraints": [], "visit_stage": "any",
        "activity_style": ["도보중심"], "best_for_days": 1,
        "anchor_areas": ["mapo", "yongsan", "seongsu"],
        "caveats": ["no_meal", "geo_scatter", "thin_day"],
    }
    assert check_one(good, facts_by_id["VK_THEME_041"], gaz, "VK_THEME_041") == [], \
        check_one(good, facts_by_id["VK_THEME_041"], gaz, "VK_THEME_041")

    # 환각: 이 코스에 없는 장소
    bad = dict(good, description_search=good["description_search"] + " 경복궁도 들른다.")
    assert any("경복궁" in e for e in check_one(bad, facts_by_id["VK_THEME_041"], gaz, "VK_THEME_041"))

    # 약점 은폐: caveats 를 비우면 잡혀야 한다
    bad2 = dict(good, caveats=[])
    assert any("caveats 누락" in e for e in check_one(bad2, facts_by_id["VK_THEME_041"], gaz, "VK_THEME_041"))

    # 홍보 문구
    bad3 = dict(good, description_search=good["description_search"] + " 감성 가득한 곳이다.")
    assert any("홍보 문구" in e for e in check_one(bad3, facts_by_id["VK_THEME_041"], gaz, "VK_THEME_041"))

    # 없는 지역
    bad4 = dict(good, anchor_areas=["mapo", "jongno"])
    assert any("anchor_areas" in e for e in check_one(bad4, facts_by_id["VK_THEME_041"], gaz, "VK_THEME_041"))

    print("demo ok")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--demo"]
    if "--demo" in sys.argv[1:]:
        demo()
    else:
        sys.exit(validate(Path(args[0]) if args else GOLD))
