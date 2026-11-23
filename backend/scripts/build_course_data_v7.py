"""
build_course_data_v7.py — course_data_v6.json 에서 하루 일정의 뼈대로 못 쓰는
것을 걸러 course_data_v7.json 을 만든다.

    ./venv/bin/python scripts/build_course_data_v7.py

v6 -> v7. v6 은 그대로 두고 별도 파일로 저장한다 (v5 -> v6 와 같은 관례).
결정적이다: 같은 v6 이면 항상 같은 v7. 네트워크도 LLM 도 쓰지 않는다.

순서가 중요하다. 정류장 단위로 먼저 걸러야 코스 단위 판정이 걸러진 뒤의 모습을 본다.

1. 정류장 제거
   - 일반명 정류장: 실제 장소가 아니라 활동·범주 이름 ("Jjimjilbang", "Karaoke").
     GENERIC_STOPS 에 이름을 직접 적었다. 정규식으로 짐작하지 않는다 — 걸러진 것을
     눈으로 확인할 수 있어야 한다.
   - 지하철역: 도착 지점이지 방문지가 아니다. 점(is_area_type 아님)이고
     tourist_spot/street 인 "... Station" 만. 강남역처럼 상권을 가리키는 area 형,
     문화역서울284 같은 건물, 롯데마트 서울역점은 남긴다.
2. 코스 제거 (남은 정류장 기준, 사유는 겹칠 수 있다)
   - thin       : 정류장 MIN_STOPS 개 미만
   - food_only  : 식당·카페가 아닌 정류장이 MIN_NON_FOOD 개 미만
   - spread     : 정류장을 순서대로 이은 직선거리 합이 MAX_PATH_KM 초과.
                  구역 수가 아니라 이동 거리다 — 한 구역 안에서 38km 를 도는 코스도 잡는다.
3. 살아남은 코스의 sequence_order 를 1..n 으로 다시 매긴다 (운영 코드는 읽지 않는다).

course_descriptions.json 과 course_vectors.npz 는 건드리지 않는다. 둘 다 course_id 로
묶이므로 v7 에 없는 id 의 행은 그냥 쓰이지 않는다.
"""
from __future__ import annotations

import itertools
import json
import re
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from geo import haversine_km

V6_PATH = _BACKEND / "dataset" / "course_data_v6.json"
V7_PATH = _BACKEND / "dataset" / "course_data_v7.json"
REPORT_PATH = _HERE / "course_data_v7_report.json"

MIN_STOPS = 3        # 25개가 3개, 34개가 4개 — 3 미만만 얇다고 본다
MIN_NON_FOOD = 2     # 식당·카페 말고 갈 곳이 2곳은 있어야 하루의 뼈대다
MAX_PATH_KM = 20.0   # 직선거리 합. 20 초과 16개, 25 초과 7개
FOOD_TYPES = {"restaurant", "cafe"}   # market 은 구경거리라 뺀다 (광장시장·남대문시장)

# 이름이 활동·범주라 지도에서 찾을 수 없는 정류장. 괄호 앞 영문명, 소문자.
GENERIC_STOPS = {
    "jjimjilbang",
    "karaoke",
    "hanbok rental",
    "hanbok experience at palaces",
    "traditional culture experience",
    "brunch at yeonhui-dong",
    "food delivery at hangang river",
    "hangang water sports",
    "hangang parks",
    "seongsu self-photo booths",
    "hongdae street performance",
    "daehak-ro retro cafe",          # 주소가 "(venue TBD)"
    "jongno hanok cafes",
    "mangnidan street accessory shop",
    "jazz bars",                     # 설명문 스스로 "a category, not a venue"
}


def base_name(poi_name: str) -> str:
    """'Hongik Univ. Station (AREX) (홍대입구역)' -> 'hongik univ. station'"""
    return re.sub(r"\s*\([^)]*\)", "", poi_name or "").strip().lower()


def is_generic(poi: dict[str, Any]) -> bool:
    return base_name(poi.get("poi_name", "")) in GENERIC_STOPS


def is_station(poi: dict[str, Any]) -> bool:
    return (
        base_name(poi.get("poi_name", "")).endswith(" station")
        and poi.get("poi_type") in {"tourist_spot", "street"}
        and not poi.get("is_area_type")
    )


def drop_reason(poi: dict[str, Any]) -> str | None:
    if is_generic(poi):
        return "generic"
    if is_station(poi):
        return "station"
    return None


def path_km(sequence: list[dict[str, Any]]) -> float:
    pts = [(p["lat"], p["lng"]) for p in sequence if p.get("lat") is not None and p.get("lng") is not None]
    return sum(haversine_km(*a, *b) for a, b in itertools.pairwise(pts))


def course_reasons(sequence: list[dict[str, Any]]) -> list[str]:
    reasons = []
    if len(sequence) < MIN_STOPS:
        reasons.append("thin")
    if sum(1 for p in sequence if p.get("poi_type") not in FOOD_TYPES) < MIN_NON_FOOD:
        reasons.append("food_only")
    if path_km(sequence) > MAX_PATH_KM:
        reasons.append("spread")
    return reasons


def build(v6: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    dropped_courses: list[dict[str, Any]] = []
    trimmed: list[dict[str, Any]] = []

    for c in v6:
        removed = [(p["poi_name"], r) for p in c["sequence"] if (r := drop_reason(p))]
        seq = [p for p in c["sequence"] if not drop_reason(p)]

        reasons = course_reasons(seq)
        if reasons:
            dropped_courses.append({
                "course_id": c["course_id"], "title": c["course_title"], "reasons": reasons,
                "stops_before": len(c["sequence"]), "stops_after": len(seq),
                "path_km": round(path_km(seq), 1),
            })
            continue

        if removed:
            trimmed.append({"course_id": c["course_id"], "removed": [f"{n} [{r}]" for n, r in removed]})
        kept.append({**c, "sequence": [{**p, "sequence_order": i} for i, p in enumerate(seq, 1)]})

    report = {
        "thresholds": {"min_stops": MIN_STOPS, "min_non_food": MIN_NON_FOOD, "max_path_km": MAX_PATH_KM},
        "counts": {"v6": len(v6), "v7": len(kept), "dropped": len(dropped_courses),
                   "stops_removed": sum(len(t["removed"]) for t in trimmed)
                   + sum(d["stops_before"] - d["stops_after"] for d in dropped_courses)},
        "dropped_courses": dropped_courses,
        "trimmed_courses": trimmed,
    }
    return kept, report


def main() -> None:
    v6 = json.loads(V6_PATH.read_text(encoding="utf-8"))
    v7, report = build(v6)
    V7_PATH.write_text(json.dumps(v7, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {V7_PATH.name}: {report['counts']['v6']} -> {report['counts']['v7']} courses "
          f"({report['counts']['dropped']} dropped, {len(report['trimmed_courses'])} trimmed)")


if __name__ == "__main__":
    main()
