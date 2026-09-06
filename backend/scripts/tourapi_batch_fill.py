"""
TourAPI(EngService2) 배치 호출 — course_data_v3.json에서 is_area_type=false 이면서
opening_hours가 아직 없는 POI들의 운영시간/휴무일을 찾는다.

test_tourapi.py의 소규모 테스트 로직(searchKeyword2 -> detailIntro2, 한글/영문 둘 다
시도)을 그대로 확장한 배치 버전. 하루 호출 한도(1000)를 지키기 위해:
  - 체크포인트 파일에 POI별 결과를 매번 즉시 저장한다 (중단돼도 안전).
  - 이미 처리된 POI는 건너뛴다 (다음 날 이어서 실행 가능).
  - 호출 카운터가 CALL_BUDGET을 넘기기 직전에 멈춘다.

사용법:
    backend/venv/Scripts/python.exe backend/scripts/tourapi_batch_fill.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
COURSE_DATA_PATH = BACKEND_DIR / "dataset" / "course_data_v3.json"
CHECKPOINT_PATH = SCRIPT_DIR / "tourapi_batch_result.json"

load_dotenv(BACKEND_DIR / ".env")
TOUR_API_KEY = os.getenv("TOUR_API_KEY")

API_VERSION = "2"
BASE_URL = f"https://apis.data.go.kr/B551011/EngService{API_VERSION}"
MOBILE_OS = "ETC"
MOBILE_APP = "SeoulFitBatch"
REQUEST_TIMEOUT = 10
SLEEP_BETWEEN_CALLS = 0.3

# 오늘 하루 호출 한도(1000) 안에서 안전하게 멈추기 위한 예산.
# (이전 소규모 테스트에서 이미 ~24건을 썼으므로 여유를 더 둔다.)
CALL_BUDGET = 900

NAME_RE = re.compile(r"^(.*?)\s*\((.*)\)\s*$")


def load_targets() -> list[dict]:
    with open(COURSE_DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)
    seen: dict[str, dict] = {}
    for course in data:
        for poi in course.get("sequence", []):
            seen.setdefault(poi["poi_name"], poi)

    targets = []
    for poi in seen.values():
        if poi.get("is_area_type") or "opening_hours" in poi:
            continue
        m = NAME_RE.match(poi["poi_name"])
        if m:
            name_en, name_ko = m.group(1).strip(), m.group(2).strip()
        else:
            name_en, name_ko = poi["poi_name"], poi["poi_name"]
        targets.append({
            "poi_name": poi["poi_name"],
            "poi_type": poi.get("poi_type"),
            "name_en": name_en,
            "name_ko": name_ko,
            "lat": poi.get("lat"),
            "lng": poi.get("lng"),
        })
    return targets


def load_checkpoint() -> list[dict]:
    if CHECKPOINT_PATH.exists():
        with open(CHECKPOINT_PATH, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_checkpoint(results: list[dict]) -> None:
    with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


call_count = 0


def build_url(endpoint: str, params: dict) -> str:
    q = {"MobileOS": MOBILE_OS, "MobileApp": MOBILE_APP, "_type": "json", **params}
    query_str = "&".join(f"{k}={quote(str(v))}" for k, v in q.items())
    if "%" in (TOUR_API_KEY or ""):
        key_part = f"serviceKey={TOUR_API_KEY}"
    else:
        key_part = f"serviceKey={quote(TOUR_API_KEY or '')}"
    return f"{BASE_URL}/{endpoint}?{key_part}&{query_str}"


def call_api(endpoint: str, params: dict) -> dict:
    global call_count
    call_count += 1
    url = build_url(endpoint, params)
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        return {"ok": False, "error": f"RequestException: {e!r}"}
    try:
        data = resp.json()
    except ValueError:
        return {"ok": False, "error": f"Non-JSON response (HTTP {resp.status_code}): {resp.text[:500]}"}
    header = (data.get("response") or {}).get("header") or {}
    result_code = header.get("resultCode")
    if result_code not in ("0000", "00"):
        return {"ok": False, "error": f"API error resultCode={result_code} resultMsg={header.get('resultMsg')}"}
    return {"ok": True, "data": data}


def search_keyword(keyword: str) -> dict:
    result = call_api(f"searchKeyword{API_VERSION}", {"keyword": keyword, "numOfRows": 10, "pageNo": 1, "arrange": "A"})
    time.sleep(SLEEP_BETWEEN_CALLS)
    if not result["ok"]:
        return {"query": keyword, "ok": False, "error": result["error"], "items": []}
    body = result["data"].get("response", {}).get("body", {})
    items_raw = (body.get("items") or {}).get("item") or []
    if isinstance(items_raw, dict):
        items_raw = [items_raw]
    items = [
        {"contentid": it.get("contentid"), "contenttypeid": it.get("contenttypeid"),
         "title": it.get("title"), "addr1": it.get("addr1")}
        for it in items_raw
    ]
    return {"query": keyword, "ok": True, "items": items}


def detail_intro(content_id: str, content_type_id: str) -> dict:
    result = call_api(f"detailIntro{API_VERSION}", {"contentId": content_id, "contentTypeId": content_type_id})
    time.sleep(SLEEP_BETWEEN_CALLS)
    if not result["ok"]:
        return {"ok": False, "error": result["error"]}
    body = result["data"].get("response", {}).get("body", {})
    items_raw = (body.get("items") or {}).get("item") or []
    if isinstance(items_raw, dict):
        items_raw = [items_raw]
    if not items_raw:
        return {"ok": True, "operating_hours_fields": {}, "closed_day_fields": {}}
    item = items_raw[0]
    operating_hours_fields = {k: v for k, v in item.items() if "usetime" in k.lower() or "opentime" in k.lower()}
    closed_day_fields = {k: v for k, v in item.items() if "restdate" in k.lower()}
    return {"ok": True, "operating_hours_fields": operating_hours_fields, "closed_day_fields": closed_day_fields}


def has_nonempty(d: dict) -> bool:
    return any(str(v).strip() for v in d.values() if v is not None)


def main():
    if not TOUR_API_KEY:
        print("ERROR: TOUR_API_KEY not set")
        sys.exit(1)

    targets = load_targets()
    print(f"[batch] 전체 대상: {len(targets)}개")

    results = load_checkpoint()
    done_names = {r["poi_name"] for r in results}
    remaining = [t for t in targets if t["poi_name"] not in done_names]
    print(f"[batch] 이미 처리됨(체크포인트): {len(done_names)}개, 남은 대상: {len(remaining)}개")

    stopped_early = False
    processed_this_run = 0
    for t in remaining:
        # 이번 POI가 최악의 경우(ko검색+en검색+detail) 3콜을 쓸 수 있으니
        # 여유 있게 예산을 넘기기 전에 멈춘다.
        if call_count + 3 > CALL_BUDGET:
            print(f"[batch] 호출 예산({CALL_BUDGET}) 근접 -> 중단. 지금까지 이번 실행에서 {call_count}콜 사용.")
            stopped_early = True
            break

        name_ko, name_en = t["name_ko"], t["name_en"]
        search_en = search_keyword(name_en)
        search_ko = search_keyword(name_ko) if call_count + 1 <= CALL_BUDGET else {"query": name_ko, "ok": False, "error": "budget", "items": []}

        matched_source, top_item = None, None
        if search_en.get("ok") and search_en["items"]:
            matched_source, top_item = "en", search_en["items"][0]
        elif search_ko.get("ok") and search_ko["items"]:
            matched_source, top_item = "ko", search_ko["items"][0]

        record = {
            "poi_name": t["poi_name"], "poi_type": t["poi_type"],
            "name_ko": name_ko, "name_en": name_en,
            "search_ko": search_ko, "search_en": search_en,
            "matched": top_item is not None, "matched_source": matched_source,
            "contentid": top_item["contentid"] if top_item else None,
            "contenttypeid": top_item["contenttypeid"] if top_item else None,
            "matched_title": top_item["title"] if top_item else None,
            "detail_intro": None,
        }

        if top_item and top_item.get("contentid") and top_item.get("contenttypeid") and call_count + 1 <= CALL_BUDGET:
            record["detail_intro"] = detail_intro(top_item["contentid"], top_item["contenttypeid"])

        results.append(record)
        processed_this_run += 1
        save_checkpoint(results)  # 즉시 저장 -> 중단돼도 안전

        if processed_this_run % 20 == 0:
            print(f"[batch] {processed_this_run}개 처리 (누적 콜 {call_count}) ...")

    print()
    print(f"[batch] 이번 실행에서 {processed_this_run}개 처리, 총 누적 콜 수(이번 실행) = {call_count}")
    print(f"[batch] 전체 체크포인트: {len(results)}/{len(targets)}")
    if stopped_early:
        left = len(targets) - len(results)
        print(f"[batch] 예산 초과로 중단 -> 아직 {left}개 남음. 다음 날 다시 실행하면 이어서 처리됨.")
    else:
        print("[batch] 전체 대상 처리 완료.")


if __name__ == "__main__":
    main()
