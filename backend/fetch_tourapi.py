"""TourAPI(EngService2) 서울 데이터를 로컬 JSON으로 내려받는다.

Index B — 코스 보강/대체 후보 (면세점 제외, 약 858건)
Index T — 면세점 (Tax Refund Shop, 약 4,102건)

목록만 받는 --list 와 휴무일까지 채우는 --detail 을 분리했다.
목록은 십여 회 호출이면 끝나지만 상세는 건당 1회라 비싸다.

    export TOURAPI_KEY=...
    python fetch_tourapi.py --list          # 먼저 이것부터
    python fetch_tourapi.py --detail        # 데이터 확인 후
    python fetch_tourapi.py --common        # 설명글(overview) 채우기
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

BASE = "https://apis.data.go.kr/B551011/EngService2"
SEOUL = "11"
# SH(쇼핑)는 83%가 면세점이라 Index T로 따로 뺀다.
INDEX_B_CATS = ["EX", "FD", "HS", "LS", "NA", "VE", "AC"]  # EV(축제)는 상시 변동이라 제외 — searchFestival2로 실시간 조회
OUT_DIR = Path(__file__).resolve().parent / "_tourapi"

# 관광타입별 휴무일/영업시간 필드명. detailIntro2 응답이 타입마다 다르다.
INTRO_FIELDS = {
    "75": ("restdateleports", "usetimeleports"),
    "76": ("restdate", "usetime"),
    "78": ("restdateculture", "usetimeculture"),
    "79": ("restdateshopping", "opentime"),
    "80": (None, "checkintime"),
    "82": ("restdatefood", "opentimefood"),
    "85": (None, "playtime"),
}


def _client(key: str) -> httpx.Client:
    return httpx.Client(
        timeout=30.0,
        params={
            "serviceKey": key,
            "MobileOS": "ETC",
            "MobileApp": "SeoulFit",
            "_type": "json",
        },
    )


def _get(c: httpx.Client, op: str, **params) -> dict:
    """오퍼레이션 1회 호출. GW 오류는 최상위 resultCode로 오므로 따로 잡는다."""
    r = c.get(f"{BASE}/{op}", params=params)
    r.raise_for_status()
    if not r.text.lstrip().startswith("{"):
        raise RuntimeError(f"{op}: JSON이 아닌 응답 (트래픽 초과/키 오류 가능) {r.text[:200]}")
    d = r.json()
    if "response" not in d:  # GW 레벨 오류
        raise RuntimeError(f"{op}: {d.get('resultCode')} {d.get('resultMsg')}")
    return d["response"]["body"]


def _items(body: dict) -> list[dict]:
    it = body.get("items")
    if not it:
        return []
    item = it["item"]
    return item if isinstance(item, list) else [item]


def fetch_list(c: httpx.Client, **filt) -> list[dict]:
    """areaBasedList2를 끝까지 페이징한다."""
    rows, page = [], 1
    while True:
        body = _get(c, "areaBasedList2", lDongRegnCd=SEOUL, arrange="Q",
                    numOfRows=100, pageNo=page, **filt)
        got = _items(body)
        rows += got
        if len(rows) >= int(body.get("totalCount", 0)) or not got:
            return rows
        page += 1


def cmd_list(c: httpx.Client) -> None:
    OUT_DIR.mkdir(exist_ok=True)

    index_b, calls = [], 0
    for cat in INDEX_B_CATS:
        rows = fetch_list(c, lclsSystm1=cat)
        calls += 1 + len(rows) // 100
        index_b += rows
        print(f"  {cat}  {len(rows):>4}")

    index_t = fetch_list(c, lclsSystm1="SH", lclsSystm2="SH04")
    calls += 1 + len(index_t) // 100

    (OUT_DIR / "index_b.json").write_text(
        json.dumps(index_b, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT_DIR / "index_t.json").write_text(
        json.dumps(index_t, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nIndex B {len(index_b)}건 / Index T {len(index_t)}건 · 호출 {calls}회")
    print(f"저장: {OUT_DIR}")


_SECRET = re.compile(r"(serviceKey|apiKey|key)=[^&\s\'\"]+", re.I)


def _redact(msg: str) -> str:
    """예외 메시지에 섞인 API 키를 지운다."""
    return _SECRET.sub(r"\1=REDACTED", msg)


# 한 건물에서 상세를 채울 매장 수 상한.
#
# 면세점 목록은 백화점·아울렛 한 건물의 브랜드 매장이 전부 개별 레코드고,
# 앱은 그걸 좌표 단위로 한 건으로 접어 보여준다. 접힌 건물에 필요한 건
# saleitem 의 합집합인데, 실측하면 10~12건이면 포화한다 — 롯데 잠실 에비뉴엘은
# 10번째 매장에서 12개 중 11개가 채워졌고 신세계 타임스퀘어는 8번째에서 6개
# 전부가 나왔다. 마리오아울렛 113건을 전부 부르면 쿼터만 태우고 카테고리는
# 7개에서 멈춘다.
VENUE_SAMPLE = 12


def _cap_per_venue(rows: list[dict], todo: list[dict]) -> list[dict]:
    """같은 좌표에 몰린 매장은 VENUE_SAMPLE 건까지만 상세를 부른다."""
    have: dict[tuple, int] = collections.Counter()
    for r in rows:
        intro = r.get("intro")
        if isinstance(intro, dict) and "_error" not in intro:
            have[(r.get("mapx"), r.get("mapy"))] += 1

    picked, taken = [], collections.Counter()
    for r in sorted(todo, key=lambda x: x["contentid"]):
        at = (r.get("mapx"), r.get("mapy"))
        if have[at] + taken[at] >= VENUE_SAMPLE:
            continue
        taken[at] += 1
        picked.append(r)
    skipped = len(todo) - len(picked)
    if skipped:
        print(f"  건물당 {VENUE_SAMPLE}건 상한으로 {skipped}건 건너뜀")
    return picked


def enrich(c: httpx.Client, key: str, op: str, needs_type: bool,
           index: str = "b") -> None:
    """Index B/T 각 건에 상세 조회 결과를 key 필드로 병합한다.

    intro  <- detailIntro2   운영정보 (휴무일, 영업시간, 문의처)
    common <- detailCommon2  공통정보 (overview, homepage)

    이미 key가 있는 건은 건너뛰므로 중간에 끊겨도 다시 돌리면 이어진다.

    Index T(면세점)는 contenttypeid 가 전부 79라 detailIntro2 가 쇼핑 전용
    필드를 준다 — saleitem(판매품목), shopguide(즉시환급/사후환급),
    opentime, infocentershopping. 목록 응답에는 없는 것들이고, 이 중
    saleitem 이 앱 칩의 유일한 분류 축이다.
    """
    path = OUT_DIR / f"index_{index}.json"
    if not path.exists():
        sys.exit(f"{path.name}이 없다. --list 를 먼저 실행할 것.")

    rows = json.loads(path.read_text(encoding="utf-8"))
    # 실패로 남은 건(_error)도 다시 집는다. 하루 1,000회 쿼터에 걸려 429 로
    # 끝난 건들이 key 를 갖고 있다는 이유로 영영 건너뛰어지면 안 된다.
    todo = [r for r in rows if key not in r or "_error" in (r[key] or {})]
    if index == "t":
        todo = _cap_per_venue(rows, todo)
    print(f"{op}: {len(todo)}/{len(rows)}건 조회")

    for i, r in enumerate(todo, 1):
        params = {"contentId": r["contentid"]}
        if needs_type:
            params["contentTypeId"] = r["contenttypeid"]
        try:
            got = _items(_get(c, op, **params))
            r[key] = got[0] if got else {}
        except Exception as e:
            # str(e) 를 그대로 넣으면 안 된다 — httpx 예외 메시지에 요청 URL 이
            # 통째로 들어 있고 거기에 serviceKey 가 붙어 있다. 파일에 API 키를
            # 수천 번 적어두는 꼴이 된다.
            r[key] = {"_error": _redact(str(e))}
        if i % 100 == 0:
            print(f"  {i}/{len(todo)}")
            path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(0.05)

    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for r in rows if r.get(key) and "_error" not in r[key])
    print(f"\n완료 {ok}/{len(rows)}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--list", action="store_true", help="목록 수집 (호출 ~50회)")
    p.add_argument("--detail", action="store_true", help="detailIntro2 운영정보 (건당 1회)")
    p.add_argument("--common", action="store_true", help="detailCommon2 설명글 (건당 1회)")
    p.add_argument("--index", choices=["b", "t"], default="b",
                   help="상세를 채울 대상. b=코스 후보(기본), t=면세점")
    a = p.parse_args()

    key = os.environ.get("TOURAPI_KEY")
    if not key:
        sys.exit("TOURAPI_KEY 환경변수가 필요하다.")

    with _client(key) as c:
        if a.list:
            cmd_list(c)
        elif a.detail:
            enrich(c, "intro", "detailIntro2", needs_type=True, index=a.index)
        elif a.common:
            enrich(c, "common", "detailCommon2", needs_type=False, index=a.index)
        else:
            p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
