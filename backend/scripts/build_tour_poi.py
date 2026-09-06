"""_tourapi/index_b.json (740건) → dataset/tour_poi.json (431건).

On-trip 탭의 주변 관광 POI 지도가 읽는 데이터를 만든다. 오프라인 배치 1회이고
서비스 실행 중에는 돌지 않는다 — 원본이 하루 1회만 갱신되므로 산출물을 커밋한다.

    python backend/scripts/build_tour_poi.py

거르는 것과 그 이유:
  FD(음식) 90건   — /nearby 의 Google Places 가 더 촘촘하게 커버한다.
  EX050800 219건  — 성형외과·한의원·피부과·대학병원. TourAPI 는 이것들을
                    '체험관광'으로 분류하지만 여행 중 둘러볼 곳이 아니다.
                    스파/한방스파는 EX0501/0502/0503/0505 라 남는다.

앱이 타입별로 분기하지 않도록 여기서 평평하게 정규화한다. 원본은 같은 뜻의
필드가 관광타입마다 이름이 다르고(usetime / usetimeculture / usetimeleports),
값 안에 HTML 이 섞여 있으며, 이미지 URL 이 대부분 평문 http 다.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
SRC = BACKEND / "_tourapi" / "index_b.json"
OUT = BACKEND / "dataset" / "tour_poi.json"

# 남기는 6개 카테고리. 앱의 칩·마커색과 1:1 대응한다.
CATEGORIES = {
    "VE": "Culture",
    "EX": "Experience",
    "HS": "History",
    "NA": "Nature",
    "LS": "Leisure",
    "AC": "Stay",
}

# 관광타입(contenttypeid)별 필드명. 남는 타입은 4개뿐이다 — 75 레포츠,
# 76 관광지, 78 문화시설, 80 숙박.
INTRO = {
    "hours": ("usetime", "usetimeculture", "usetimeleports", "checkintime"),
    "closed": ("restdate", "restdateculture", "restdateleports"),
    "fee": ("usefee", "usefeeleports"),
    "parking": ("parking", "parkingculture", "parkingleports", "parkinglodging"),
    "tel": ("infocenter", "infocenterculture", "infocenterleports", "infocenterlodging"),
}

_TAG = re.compile(r"<[^>]+>")
_HREF = re.compile(r'href="([^"]+)"')
_WS = re.compile(r"[ \t]*\n[ \t]*")
_PHONE = re.compile(r"\+82[-\d]*\d")


def clean(v: str) -> str:
    """값에 섞인 HTML 을 지운다. <br> 만 개행으로 살린다."""
    if not v:
        return ""
    v = re.sub(r"<br\s*/?>", "\n", v, flags=re.I)
    return _WS.sub("\n", html.unescape(_TAG.sub("", v))).strip()


def homepage(v: str) -> str:
    """homepage 는 371건 중 304건이 <a href=...>표시명</a> 통째로 온다.

    여는 데 쓸 수 있는 건 href 뿐이라 그것만 뽑고, 태그가 없으면 원문을 쓴다.
    복수 링크가 <br> 로 이어진 경우가 있어 첫 번째만 취한다.
    """
    if not v:
        return ""
    m = _HREF.search(v)
    url = m.group(1) if m else clean(v).split("\n")[0]
    return url.strip()


def phone(v: str) -> str:
    """걸 수 있는 번호 하나만 남긴다.

    문화시설·레포츠의 infocenter 는 420건 중 144건이 안내문 블록으로 온다:
    "• 1330 Travel Hotline: +82-2-1330 (Korean, English…) • For more info:
    +82-2-6002-5300". 1330 은 관광공사 공용 안내번호라 이 POI 의 번호가
    아니고, 그대로 tel: 링크에 넣으면 엉뚱한 곳에 전화가 걸린다.
    """
    nums = [n for n in _PHONE.findall(v or "") if "1330" not in n]
    return nums[-1] if nums else ""


def pick(intro: dict, keys: tuple[str, ...]) -> str:
    for k in keys:
        if v := intro.get(k):
            return clean(v)
    return ""


def build(rows: list[dict]) -> list[dict]:
    out = []
    for x in rows:
        cat = x.get("lclsSystm1", "")
        if cat not in CATEGORIES or x.get("lclsSystm3") == "EX050800":
            continue
        intro = x.get("intro") or {}
        common = x.get("common") or {}

        hours = pick(intro, INTRO["hours"])
        # 숙박은 영업시간 대신 체크인/아웃이라 그렇게 읽히도록 라벨을 붙인다.
        if x.get("contenttypeid") == "80" and hours:
            checkout = clean(intro.get("checkouttime", ""))
            hours = f"Check-in {hours}" + (f" · Check-out {checkout}" if checkout else "")

        # 이미지 313건 중 263건이 http:// 다. iOS ATS 가 평문 HTTP 를 막으므로
        # 그대로 두면 사진이 통째로 안 뜬다. 같은 호스트가 https 로도 서빙한다.
        image = (x.get("firstimage") or "").replace("http://", "https://", 1)

        out.append({
            "id": x["contentid"],
            "title": x["title"],
            "category": cat,
            "address": x.get("addr1", ""),
            "lat": float(x["mapy"]),
            "lng": float(x["mapx"]),
            "image": image,
            "overview": clean(common.get("overview", "")),
            "hours": hours,
            "closed": pick(intro, INTRO["closed"]),
            "fee": pick(intro, INTRO["fee"]),
            "parking": pick(intro, INTRO["parking"]),
            "tel": phone(pick(intro, INTRO["tel"])),
            "homepage": homepage(common.get("homepage", "")),
        })
    return out


def main() -> None:
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    pois = build(rows)
    OUT.write_text(
        json.dumps(pois, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    counts: dict[str, int] = {}
    for p in pois:
        counts[p["category"]] = counts.get(p["category"], 0) + 1
    print(f"{SRC.name} {len(rows)} → {OUT.name} {len(pois)}")
    for c, name in CATEGORIES.items():
        print(f"  {c} {name:11} {counts.get(c, 0)}")
    print(f"  {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
