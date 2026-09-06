"""
TourAPI (한국관광공사 영문 관광정보서비스) 소규모 연동 테스트.

무엇을 하는가
------------
1. backend/course_data.json 에서 poi_type 이 "cafe" 또는 "restaurant" 인 POI 중
   이름이 뚜렷한 것들을 몇 개 골라 테스트 대상으로 삼는다 (SELECTED_POI_KO_NAMES).
2. 각 POI 이름으로 searchKeyword{API_VERSION} 을 호출해 contentid / contenttypeid 를 찾는다.
   한글명, 영문명 둘 다 시도해서 어느 쪽이 더 잘 매칭되는지 비교한다.
3. contentid 를 찾은 POI 에 대해서는 detailIntro{API_VERSION} 을 호출해서 운영시간
   (usetime/opentime 계열 필드)과 휴무일(restdate 계열 필드)이 실제로 채워져 있는지 확인한다.
4. 결과를 backend/scripts/tourapi_test_result.json 에 저장하고, 매칭률/채움률을 요약 출력한다.

버전 관련 참고
-------------
원래 요청은 searchKeyword1 / detailIntro1 (EngService1) 이었지만 실제로 호출해보니
"NO_OPENAPI_SERVICE_ERROR / 해당 오픈API 서비스가 없거나 폐기됨" (reasonCode 12) 에러가
떨어졌다. 한국관광공사가 TourAPI 4.0으로 개편하면서 "...1" 엔드포인트들이 전부 폐기되고
"...2" (EngService2, searchKeyword2, detailIntro2 등)로 이전되었기 때문이다. 이 스크립트는
API_VERSION 상수로 버전을 전환할 수 있게 해뒀고, 기본값은 실제로 동작하는 "2"다.

주의: 이건 소규모 테스트 스크립트다. 전체 course_data.json 배치 처리는 하지 않는다.

사용법
------
    backend/venv/Scripts/python.exe backend/scripts/test_tourapi.py
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

# Windows 콘솔(cp949)에서도 한글/특수문자가 깨지지 않도록 stdout/stderr 을 UTF-8로 강제
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
COURSE_DATA_PATH = BACKEND_DIR / "dataset" / "course_data.json"
RESULT_PATH = SCRIPT_DIR / "tourapi_test_result.json"

load_dotenv(BACKEND_DIR / ".env")

# 키는 반드시 os.getenv() 로만 읽는다 - 코드에 하드코딩 금지.
TOUR_API_KEY = os.getenv("TOUR_API_KEY")

# 참고: 원래는 searchKeyword1 / detailIntro1 (EngService1, TourAPI 3.0 계열)로 호출했으나
# 실제 호출 결과 "NO_OPENAPI_SERVICE_ERROR / 해당 오픈API 서비스가 없거나 폐기됨" (reasonCode 12)
# 가 떨어져 해당 버전은 폐기된 상태임을 확인했다. 한국관광공사가 TourAPI 4.0으로 개편하면서
# 모든 엔드포인트가 "...1" -> "...2" 로 이동했고 (EngService1 -> EngService2,
# searchKeyword1 -> searchKeyword2, detailIntro1 -> detailIntro2), contenttypeid 값도
# 바뀌었다 (예: 음식점 39 -> 82). 아래는 실제 살아있는 v2 엔드포인트로 테스트한다.
API_VERSION = "2"
BASE_URL = f"https://apis.data.go.kr/B551011/EngService{API_VERSION}"
MOBILE_OS = "ETC"
MOBILE_APP = "SeoulFitTest"
REQUEST_TIMEOUT = 10
SLEEP_BETWEEN_CALLS = 0.35  # 초당 호출량을 살짝 눌러서 rate limit 회피

# course_data.json 안의 poi_name 은 "English Name (한글명)" 형태다.
# 이 중 이름이 뚜렷한 (알레이/거리류 말고 특정 상호에 가까운 것 위주로) 8개를 골랐다.
SELECTED_POI_KO_NAMES = [
    "성수동 갈비골목",
    "백년옥",
    "오설록 티하우스 북촌점",
    "금돼지식당",
    "수연산방",
    "서울숲 카페거리",
    "티테라피",
    "카페 디올",
]

POI_NAME_RE = re.compile(r"^(.*?)\s*\((.*)\)\s*$")


# ---------------------------------------------------------------------------
# 1) course_data.json 에서 테스트 대상 POI 뽑기
# ---------------------------------------------------------------------------

def load_selected_pois() -> list[dict]:
    with open(COURSE_DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    candidates: dict[str, dict] = {}
    for course in data:
        for poi in course.get("sequence", []):
            if poi.get("poi_type") not in ("cafe", "restaurant"):
                continue
            # 같은 이름이 여러 코스에 중복 등장할 수 있으니 첫 등장만 사용
            candidates.setdefault(poi["poi_name"], poi)

    selected = []
    for poi_name, poi in candidates.items():
        m = POI_NAME_RE.match(poi_name)
        if m:
            name_en, name_ko = m.group(1).strip(), m.group(2).strip()
        else:
            name_en, name_ko = poi_name, poi_name

        if name_ko in SELECTED_POI_KO_NAMES:
            selected.append(
                {
                    "poi_name": poi_name,
                    "name_en": name_en,
                    "name_ko": name_ko,
                    "poi_type": poi.get("poi_type"),
                    "lat": poi.get("lat"),
                    "lng": poi.get("lng"),
                }
            )

    # SELECTED_POI_KO_NAMES 순서로 정렬
    order = {name: i for i, name in enumerate(SELECTED_POI_KO_NAMES)}
    selected.sort(key=lambda p: order.get(p["name_ko"], 999))
    return selected


# ---------------------------------------------------------------------------
# TourAPI 호출 헬퍼
# ---------------------------------------------------------------------------

def build_url(endpoint: str, params: dict) -> str:
    q = {"MobileOS": MOBILE_OS, "MobileApp": MOBILE_APP, "_type": "json", **params}
    query_str = "&".join(f"{k}={quote(str(v))}" for k, v in q.items())

    # data.go.kr 키는 "Decoding"(원문) / "Encoding"(퍼센트 인코딩 완료) 두 형태로 발급된다.
    # 이미 퍼센트 인코딩된 키를 requests 로 다시 encode 하면 이중 인코딩 되어 인증 오류가 난다.
    # '%' 가 이미 포함돼 있으면 그대로 붙이고, 아니면 quote() 로 한 번 인코딩한다.
    if "%" in (TOUR_API_KEY or ""):
        key_part = f"serviceKey={TOUR_API_KEY}"
    else:
        key_part = f"serviceKey={quote(TOUR_API_KEY or '')}"

    return f"{BASE_URL}/{endpoint}?{key_part}&{query_str}"


def call_api(endpoint: str, params: dict) -> dict:
    url = build_url(endpoint, params)
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        return {"ok": False, "error": f"RequestException: {e!r}"}

    raw_text = resp.text
    try:
        data = resp.json()
    except ValueError:
        return {
            "ok": False,
            "error": f"Non-JSON response (HTTP {resp.status_code}): {raw_text[:800]}",
        }

    header = (data.get("response") or {}).get("header") or {}
    result_code = header.get("resultCode")
    if result_code not in ("0000", "00"):
        return {
            "ok": False,
            "error": (
                f"API error resultCode={result_code} resultMsg={header.get('resultMsg')} "
                f"raw={json.dumps(data, ensure_ascii=False)[:800]}"
            ),
            "raw": data,
        }

    return {"ok": True, "data": data}


def search_keyword(keyword: str) -> dict:
    result = call_api(
        f"searchKeyword{API_VERSION}",
        {"keyword": keyword, "numOfRows": 10, "pageNo": 1, "arrange": "A"},
    )
    time.sleep(SLEEP_BETWEEN_CALLS)
    if not result["ok"]:
        return {"query": keyword, "ok": False, "error": result["error"], "items": []}

    body = result["data"].get("response", {}).get("body", {})
    total_count = body.get("totalCount", 0)
    items_raw = (body.get("items") or {}).get("item") or []
    if isinstance(items_raw, dict):  # 결과가 1건이면 dict 로 오는 API 특성
        items_raw = [items_raw]

    items = [
        {
            "contentid": it.get("contentid"),
            "contenttypeid": it.get("contenttypeid"),
            "title": it.get("title"),
            "addr1": it.get("addr1"),
        }
        for it in items_raw
    ]
    return {"query": keyword, "ok": True, "total_count": total_count, "items": items}


def detail_intro(content_id: str, content_type_id: str) -> dict:
    result = call_api(
        f"detailIntro{API_VERSION}",
        {"contentId": content_id, "contentTypeId": content_type_id},
    )
    time.sleep(SLEEP_BETWEEN_CALLS)
    if not result["ok"]:
        return {"ok": False, "error": result["error"]}

    body = result["data"].get("response", {}).get("body", {})
    items_raw = (body.get("items") or {}).get("item") or []
    if isinstance(items_raw, dict):
        items_raw = [items_raw]
    if not items_raw:
        return {"ok": True, "fields": {}, "operating_hours_fields": {}, "closed_day_fields": {}}

    item = items_raw[0]
    operating_hours_fields = {
        k: v for k, v in item.items() if "usetime" in k.lower() or "opentime" in k.lower()
    }
    closed_day_fields = {k: v for k, v in item.items() if "restdate" in k.lower()}
    return {
        "ok": True,
        "fields": item,
        "operating_hours_fields": operating_hours_fields,
        "closed_day_fields": closed_day_fields,
    }


# ---------------------------------------------------------------------------
# 메인 테스트 흐름
# ---------------------------------------------------------------------------

def has_nonempty_value(d: dict) -> bool:
    return any(str(v).strip() for v in d.values() if v is not None)


def main():
    if not TOUR_API_KEY:
        print("ERROR: TOUR_API_KEY not found. backend/.env 에 TOUR_API_KEY=... 를 설정했는지 확인하세요.")
        sys.exit(1)

    pois = load_selected_pois()
    print(f"[1] course_data.json 에서 테스트 대상 POI {len(pois)}개 로드 완료\n")

    results = []
    for poi in pois:
        name_ko, name_en = poi["name_ko"], poi["name_en"]
        print(f"--- {poi['poi_name']} ---")

        search_ko = search_keyword(name_ko)
        search_en = search_keyword(name_en)

        if search_ko["ok"]:
            print(f"  [ko] '{name_ko}' -> {len(search_ko['items'])}건")
        else:
            print(f"  [ko] '{name_ko}' -> ERROR: {search_ko['error']}")

        if search_en["ok"]:
            print(f"  [en] '{name_en}' -> {len(search_en['items'])}건")
        else:
            print(f"  [en] '{name_en}' -> ERROR: {search_en['error']}")

        # 매칭 소스 결정: en 결과 우선 (EngService 는 영문 title 기준일 가능성이 높음),
        # en 이 비어있으면 ko 결과 사용.
        matched_source = None
        top_item = None
        if search_en.get("ok") and search_en["items"]:
            matched_source = "en"
            top_item = search_en["items"][0]
        elif search_ko.get("ok") and search_ko["items"]:
            matched_source = "ko"
            top_item = search_ko["items"][0]

        record = {
            "poi_name": poi["poi_name"],
            "name_ko": name_ko,
            "name_en": name_en,
            "poi_type": poi["poi_type"],
            "lat": poi["lat"],
            "lng": poi["lng"],
            "search_ko": search_ko,
            "search_en": search_en,
            "matched": top_item is not None,
            "matched_source": matched_source,
            "contentid": top_item["contentid"] if top_item else None,
            "contenttypeid": top_item["contenttypeid"] if top_item else None,
            "matched_title": top_item["title"] if top_item else None,
            "detail_intro": None,
        }

        if top_item and top_item.get("contentid") and top_item.get("contenttypeid"):
            detail = detail_intro(top_item["contentid"], top_item["contenttypeid"])
            record["detail_intro"] = detail
            if detail["ok"]:
                has_hours = has_nonempty_value(detail["operating_hours_fields"])
                print(
                    f"  [detailIntro{API_VERSION}] contentid={top_item['contentid']} "
                    f"운영시간 필드 채워짐: {has_hours} "
                    f"({detail['operating_hours_fields']})"
                )
            else:
                print(f"  [detailIntro{API_VERSION}] ERROR: {detail['error']}")
        else:
            print(f"  [detailIntro{API_VERSION}] 건너뜀 (contentid 없음)")

        results.append(record)
        print()

    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"[2] 결과 저장 완료: {RESULT_PATH}\n")

    # --- 요약 ---
    total = len(results)
    matched = [r for r in results if r["matched"]]
    matched_count = len(matched)
    filled = [
        r
        for r in matched
        if r["detail_intro"]
        and r["detail_intro"]["ok"]
        and has_nonempty_value(r["detail_intro"]["operating_hours_fields"])
    ]
    filled_count = len(filled)

    print("=" * 60)
    print("요약")
    print("=" * 60)
    print(f"테스트 POI 수         : {total}")
    print(
        f"searchKeyword{API_VERSION} 매칭   : {matched_count}/{total} "
        f"({matched_count / total * 100:.0f}%)"
    )
    if matched_count:
        print(
            f"detailIntro{API_VERSION} 운영시간 채움 : {filled_count}/{matched_count} "
            f"({filled_count / matched_count * 100:.0f}%)"
        )
    else:
        print(f"detailIntro{API_VERSION} 운영시간 채움 : N/A (매칭된 POI 없음)")

    ko_hits = sum(1 for r in results if r["search_ko"].get("ok") and r["search_ko"]["items"])
    en_hits = sum(1 for r in results if r["search_en"].get("ok") and r["search_en"]["items"])
    print(f"한글명 검색 히트      : {ko_hits}/{total}")
    print(f"영문명 검색 히트      : {en_hits}/{total}")

    print("\nPOI별 매칭/채움 상세:")
    for r in results:
        hours_ok = (
            r["detail_intro"]
            and r["detail_intro"]["ok"]
            and has_nonempty_value(r["detail_intro"]["operating_hours_fields"])
        )
        print(
            f"  - {r['poi_name']:<45} matched={r['matched']!s:<5} "
            f"source={r['matched_source']} contentid={r['contentid']} "
            f"hours_filled={hours_ok}"
        )


if __name__ == "__main__":
    main()
