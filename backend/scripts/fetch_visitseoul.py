"""Visit Seoul API(서울관광재단) 쇼핑 카테고리 영문 전량을 내려받는다.

    export VISITSEOUL_API_KEY=...        # 없으면 backend/.env 의 visitseoul_api_key
    python backend/scripts/fetch_visitseoul.py                 # 쇼핑(기본)
    python backend/scripts/fetch_visitseoul.py --category Cu8e6t5 --lang en

산출물: backend/_visitseoul/visitseoul_shopping.json (원본 덤프)
        → scripts/build_shopping_poi.py 가 dataset/shopping_poi.json 을 만든다

TourAPI 의 index_t(사후면세 등록 명부 4102건)와는 성격이 다르다. 이쪽은 서울관광
재단이 골라 쓴 '가볼 만한 곳' 310건이고, 대신 좌표·주소·영업시간·전화·홈페이지·
지하철 안내·설명문이 전부 영문으로 들어 있다. index_t 에 없는 것들이다.

호스트가 api-call.visitseoul.net 이다(call-api 가 아니다 — DNS 가 없다).
contents/info 는 문서 제목에 GET 이라고 적혀 있지만 실제로는 POST 다.

목록은 페이지당 50건이라 7회, 상세는 건당 1회다. 중간에 끊겨도 이미 받은 cid 는
건너뛰므로 다시 돌리면 이어진다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

BASE = "https://api-call.visitseoul.net/api/v1"
BACKEND = Path(__file__).resolve().parent.parent
# 원본 덤프는 _visitseoul/ 에 둔다. dataset/ 은 백엔드가 실제로 읽는
# 가공 산출물(tour_poi.json, taxrefund.json, shopping_poi.json)만 담는다.
OUT_DIR = BACKEND / "_visitseoul"

# 대분류 '쇼핑'. category/list 로 확인한 값이다.
SHOPPING = "Cu8e6t5"


def _client(key: str) -> httpx.Client:
    return httpx.Client(
        headers={
            "VISITSEOUL-API-KEY": key,
            "Accept": "application/json;charset=UTF-8",
            "Content-Type": "application/json;charset=UTF-8",
        },
        timeout=30,
    )


def _post(c: httpx.Client, path: str, body: dict, tries: int = 3) -> dict:
    """응답이 간헐적으로 result_code 없이 빈 몸으로 오는 걸 봤다. 몇 번 다시 친다."""
    last = "no attempt made"
    for attempt in range(1, tries + 1):
        try:
            r = c.post(f"{BASE}/{path}", json=body)
            r.raise_for_status()
            j = r.json()
            if "data" in j:
                return j
            last = f"no data key: {str(j)[:120]}"
        except Exception as e:  # 네트워크·JSON 오류 모두
            last = f"{type(e).__name__}: {str(e)[:120]}"
        if attempt < tries:
            time.sleep(1.5 * attempt)
    raise RuntimeError(last)


def fetch_categories(c: httpx.Client) -> list[dict]:
    return c.get(f"{BASE}/category/list").json()["data"]


def fetch_list(c: httpx.Client, category: str, lang: str) -> list[dict]:
    """페이지를 끝까지 넘기며 목록을 모은다."""
    rows: list[dict] = []
    page = 1
    while True:
        j = _post(c, "contents/list",
                  {"com_ctgry_sn": category, "lang_code_id": lang, "page_no": page})
        rows += j["data"]
        total = (j.get("paging") or {}).get("total_count")
        print(f"  page {page}: +{len(j['data'])} (total so far {len(rows)}/{total})")
        if not j["data"] or (total is not None and len(rows) >= total):
            break
        page += 1
        time.sleep(0.3)
    return rows


def fetch_details(c: httpx.Client, rows: list[dict], out: Path) -> list[dict]:
    """cid 별 상세를 붙인다. 이미 detail 이 있는 건은 건너뛴다."""
    have: dict[str, dict] = {}
    if out.exists():
        have = {r["cid"]: r for r in json.loads(out.read_text(encoding="utf-8"))}

    merged: list[dict] = []
    todo = [r for r in rows if not (have.get(r["cid"]) or {}).get("detail")]
    print(f"상세 조회 {len(todo)}/{len(rows)}건")

    for i, r in enumerate(rows, 1):
        prev = have.get(r["cid"]) or {}
        if prev.get("detail"):
            merged.append(prev)
            continue
        try:
            r = dict(r, detail=_post(c, "contents/info", {"cid": r["cid"]})["data"])
        except Exception as e:
            r = dict(r, detail=None, _error=str(e)[:200])
        merged.append(r)
        if i % 25 == 0:
            print(f"  {i}/{len(rows)}")
            out.write_text(json.dumps(merged, ensure_ascii=False, indent=1),
                           encoding="utf-8")
        time.sleep(0.25)
    return merged


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--category", default=SHOPPING, help="대분류 코드 (기본: 쇼핑)")
    p.add_argument("--lang", default="en", help="언어 코드 (기본: en)")
    p.add_argument("--out", default="visitseoul_shopping.json")
    a = p.parse_args()

    key = os.environ.get("VISITSEOUL_API_KEY")
    if not key:
        # 편의를 위해 backend/.env 도 본다. 키 이름이 소문자다.
        try:
            from dotenv import load_dotenv
            load_dotenv(BACKEND / ".env")
            key = os.getenv("visitseoul_api_key") or os.getenv("VISITSEOUL_API_KEY")
        except ImportError:
            pass
    if not key:
        sys.exit("VISITSEOUL_API_KEY 가 필요하다 (또는 backend/.env 의 visitseoul_api_key).")

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / a.out

    with _client(key) as c:
        print(f"목록: category={a.category} lang={a.lang}")
        rows = fetch_list(c, a.category, a.lang)
        merged = fetch_details(c, rows, out)

    out.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = [r for r in merged if r.get("detail")]
    withxy = [r for r in ok
              if (r["detail"].get("traffic") or {}).get("map_position_y")]
    print(f"\n{out.name}: {len(merged)}건 (상세 {len(ok)}, 좌표 {len(withxy)})")
    print(f"  {out.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
