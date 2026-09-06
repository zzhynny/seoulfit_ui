"""
google_places_closed_weekday_fill.py — course_data_v5.json에서 opening_hours가
채워진 192개 고유 POI 전체에 대해 Google Places(legacy Place Details,
opening_hours.weekday_text)로 정기휴무 요일을 조회해 closed_weekday 필드로
opening_hours 스키마에 추가한다.

Places API (New)의 regularOpeningHours는 이 프로젝트 키에서 비활성화되어 있어
(places_api_probe.py로 확인, 403 SERVICE_DISABLED) legacy Place Details로 대체.
결과는 10곳 사전 테스트(test_places_weekly_closure.py, 10/10 성공, 경복궁 화요일
정확히 확인됨)로 검증됨.

이름 오매칭 방지: Find Place가 반환한 후보의 이름과 원본 POI 이름을 정규화해
비교하고, 토큰 겹침이 거의 없으면 closed_weekday를 채우지 않고
no_confident_match로 건너뛴다(엉뚱한 장소의 휴무일을 잘못 붙이는 것을 막기 위함).

v5 -> v6 (opening_hours + closed_weekday). course_data_v5.json은 그대로 두고
별도 파일로 저장 — 이 저장소의 기존 v2/v3/v4/v5 관례를 그대로 따름.

Run: backend/venv/Scripts/python.exe backend/scripts/google_places_closed_weekday_fill.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_BACKEND_DIR = _HERE.parent
sys.path.insert(0, str(_BACKEND_DIR))

from dotenv import load_dotenv

load_dotenv(_BACKEND_DIR / ".env")

import planner as pl  # noqa: E402

API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
V5_PATH = _BACKEND_DIR / "dataset" / "course_data_v5.json"
V6_PATH = _BACKEND_DIR / "dataset" / "course_data_v6.json"
RESULT_LOG_PATH = _HERE / "closed_weekday_fill_result.json"
REQUEST_DELAY_SECONDS = 0.15  # 예의상 딜레이, 별도 QPS 제한 회피 목적


def _strip_parenthetical(name: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", name or "").strip()


def _parenthetical(name: str) -> str:
    m = re.search(r"\(([^)]*)\)\s*$", name or "")
    return m.group(1).strip() if m else ""


def _ascii_tokens(s: str) -> set[str]:
    """영문 토큰만 추출 — 한글 압축 지명(공백 없는 단어)은 토큰 분리가 의미
    없어서 별도로(문자열 포함 비교) 처리한다."""
    s = re.sub(r"[^a-z0-9\s]", " ", (s or "").lower())
    return {tok for tok in s.split() if len(tok) > 1}


def _match_tier(input_name: str, candidate_name: str) -> str:
    """원본 POI 이름(보통 "English (한글)" 형태)과 Google이 반환한 후보 이름을
    비교한다. 최초 구현은 한글을 정규화 과정에서 전부 지워버려서, Google이
    한글로만 응답하는 경우(예: 입력 "Suseongdonggyegok Valley (수성동계곡)" vs
    Google "수성동계곡") 완전히 동일한 이름인데도 no_confident_match로
    떨어지는 버그가 있었다 — 실측 192건 배치에서 다수 확인되어 이 함수로
    교체함."""
    input_name = (input_name or "").strip()
    candidate_name = (candidate_name or "").strip()
    if not input_name or not candidate_name:
        return "no_confident_match"

    input_lower = input_name.lower()
    candidate_lower = candidate_name.lower()
    input_nospace = input_lower.replace(" ", "")
    candidate_nospace = candidate_lower.replace(" ", "")

    # 1. 전체 문자열 완전/부분 일치 (공백 무시) — 한글-한글 동일 이름 케이스를 잡는다.
    if input_nospace == candidate_nospace:
        return "exact"
    if len(candidate_nospace) >= 3 and (
        candidate_nospace in input_nospace or input_nospace in candidate_nospace
    ):
        return "exact"

    # 2. "English (한글)" 형태의 입력이면, 영문부/괄호 안 한글부를 각각
    #    후보와 비교 (Google이 영문 또는 한글 단독으로 응답하는 경우 대응).
    for part in (_strip_parenthetical(input_name).lower(), _parenthetical(input_name).lower()):
        part_nospace = part.replace(" ", "")
        if not part_nospace:
            continue
        if part_nospace == candidate_nospace:
            return "exact"
        if len(candidate_nospace) >= 3 and (
            candidate_nospace in part_nospace or part_nospace in candidate_nospace
        ):
            return "exact"

    # 3. 영문 토큰 겹침 fallback (로마자 표기가 다른 순서/일부만 겹치는 경우)
    a, b = _ascii_tokens(_strip_parenthetical(input_name)), _ascii_tokens(candidate_lower)
    if a and b:
        overlap = len(a & b) / min(len(a), len(b))
        if overlap >= 0.8:
            return "exact"
        if overlap >= 0.4:
            return "loose"

    return "no_confident_match"


def _find_place_id_and_name(name: str, address: str, lat, lng) -> tuple[str | None, str | None]:
    url = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
    params = {
        "input": f"{name}, {address}" if address else name,
        "inputtype": "textquery",
        "fields": "place_id,name",
        "key": API_KEY,
    }
    if lat is not None and lng is not None:
        params["locationbias"] = f"point:{lat},{lng}"
    data = pl._google_get(url, params)
    candidates = data.get("candidates") or []
    if not candidates:
        return None, None
    return candidates[0].get("place_id"), candidates[0].get("name")


def main() -> None:
    if not API_KEY:
        print("GOOGLE_PLACES_API_KEY not set — aborting.")
        return

    v5 = json.loads(V5_PATH.read_text(encoding="utf-8"))

    # opening_hours가 채워진 고유 POI 수집 (poi_name 기준, 첫 등장 항목 사용)
    unique_pois: dict[str, dict[str, Any]] = {}
    for course in v5:
        for poi in course.get("sequence", []) or []:
            name = poi.get("poi_name")
            if name and name not in unique_pois and poi.get("opening_hours"):
                unique_pois[name] = poi

    print(f"대상 POI: {len(unique_pois)}개")

    log: list[dict[str, Any]] = []
    closed_weekday_by_name: dict[str, dict[str, Any]] = {}

    for i, (name, poi) in enumerate(unique_pois.items(), start=1):
        address = poi.get("address_en") or poi.get("address_ko") or ""
        lat, lng = poi.get("lat"), poi.get("lng")

        place_id, candidate_name = _find_place_id_and_name(name, address, lat, lng)
        time.sleep(REQUEST_DELAY_SECONDS)

        if not place_id:
            print(f"[{i}/{len(unique_pois)}] {name}: place_id 못 찾음")
            log.append({"name": name, "status": "no_place_id"})
            continue

        tier = _match_tier(name, candidate_name or "")
        if tier == "no_confident_match":
            print(f"[{i}/{len(unique_pois)}] {name}: 매칭 신뢰도 낮음 (Google명='{candidate_name}') -> 건너뜀")
            log.append({
                "name": name, "status": "no_confident_match",
                "place_id": place_id, "google_name": candidate_name,
            })
            continue

        opening_hours = pl.fetch_weekly_closure(place_id=place_id, api_key=API_KEY)
        time.sleep(REQUEST_DELAY_SECONDS)
        closed = pl.derive_closed_weekdays(opening_hours)

        if opening_hours is None:
            print(f"[{i}/{len(unique_pois)}] {name}: opening_hours 데이터 없음")
            log.append({
                "name": name, "status": "no_opening_hours_data",
                "place_id": place_id, "google_name": candidate_name, "match_tier": tier,
            })
            continue

        print(f"[{i}/{len(unique_pois)}] {name}: closed_weekday={closed!r} (match={tier})")
        log.append({
            "name": name, "status": "ok", "place_id": place_id,
            "google_name": candidate_name, "match_tier": tier, "closed_weekday": closed,
        })
        closed_weekday_by_name[name] = {
            "closed_weekday": closed,
            "closed_weekday_source": "google_places_legacy",
            "closed_weekday_place_id": place_id,
            "closed_weekday_match_tier": tier,
        }

    # v5 전체 구조에 반영 (해당 POI 이름이 등장하는 모든 course의 모든 occurrence)
    n_applied = 0
    for course in v5:
        for poi in course.get("sequence", []) or []:
            name = poi.get("poi_name")
            extra = closed_weekday_by_name.get(name)
            if extra and poi.get("opening_hours"):
                poi["opening_hours"].update(extra)
                n_applied += 1

    V6_PATH.write_text(json.dumps(v5, ensure_ascii=False, indent=2), encoding="utf-8")
    RESULT_LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

    n_ok = sum(1 for r in log if r["status"] == "ok")
    n_no_place = sum(1 for r in log if r["status"] == "no_place_id")
    n_no_match = sum(1 for r in log if r["status"] == "no_confident_match")
    n_no_hours = sum(1 for r in log if r["status"] == "no_opening_hours_data")
    n_has_closure = sum(1 for r in log if r.get("closed_weekday"))

    print()
    print("=== 요약 ===")
    print(f"대상 고유 POI: {len(unique_pois)}")
    print(f"  성공(closed_weekday 필드 채움 대상): {n_ok}")
    print(f"  place_id 못 찾음: {n_no_place}")
    print(f"  매칭 신뢰도 낮아 건너뜀: {n_no_match}")
    print(f"  opening_hours 데이터 없음: {n_no_hours}")
    print(f"  실제 정기휴무 요일이 있는 곳: {n_has_closure} / {n_ok}")
    print(f"  course_data_v6.json에 실제로 반영된 POI occurrence 수: {n_applied}")
    print(f"\n저장: {V6_PATH}")
    print(f"로그: {RESULT_LOG_PATH}")


if __name__ == "__main__":
    main()
