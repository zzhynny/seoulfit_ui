"""_visitseoul/visitseoul_shopping.json (310건) → dataset/shopping_poi.json.

On-trip 탭의 '쇼핑' 목록이 읽는 데이터를 만든다. build_tour_poi.py 와 같은
오프라인 배치 1회이고 서비스 실행 중에는 돌지 않는다.

    python backend/scripts/build_shopping_poi.py

원본은 서울관광재단 Visit Seoul API 덤프다. 앱이 쓰지 않는 것이 대부분이라
2065KB → 414KB 로 줄어든다. 빼는 것과 그 이유:

  post_desc  1352KB — HTML 원문. 태그를 걷어내고 본문만 남긴다.
  relate_img  138KB — 카드도 시트도 대표 이미지 하나만 쓴다.
  tag          42KB — 220건에 1132종이고 921종이 한 번만 나온다. 필터로 못 쓴다.
  multi_lang   25KB — 다국어 cid 목록. 앱은 영문만 부른다.
  중복         167KB — 목록 필드가 detail 안에 그대로 한 번 더 들어 있다.

좌표가 detail.traffic 안에 문자열로 들어 있어서 여기서 float 으로 바꾼다.
요청마다 310건을 파싱할 이유가 없다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
SRC = BACKEND / "_visitseoul" / "visitseoul_shopping.json"
OUT = BACKEND / "dataset" / "shopping_poi.json"

# Visit Seoul 하위 카테고리 → 앱의 칩·마커 키. tour_poi.json 의 VE/EX/HS 와
# 같은 자리에 들어가므로 두 글자로 맞춘다.
CATEGORIES = {
    "Shopping > Specialty Shops & Stores": "SP",
    "Shopping > Traditional Markets": "TM",
    "Shopping > Shopping Malls & Outlets": "MO",
    "Shopping > Department Stores": "DS",
    "Shopping > Duty Free Shops": "DF",
    "Shopping > Supermarkets & Warehouses": "SW",
}
# 하위 카테고리 없이 대분류만 달린 48건. 들여다보면 508shop, LOW CLASSIC,
# 10 Corso Como 처럼 전부 편집숍이라 SP 로 넣는다.
BARE = "Shopping"
BARE_CATEGORY = "SP"

CATEGORY_NAMES = {
    "SP": "Shops",
    "TM": "Markets",
    "MO": "Malls",
    "DS": "Dept stores",
    "DF": "Duty free",
    "SW": "Supermarkets",
}

# <style>/<script> 는 본문이 통째로 텍스트라, 태그만 걷어내면 CSS 가 설명문에
# 그대로 흘러든다. 310건 중 190건이 style 블록을 물고 있다.
_BLOCK = re.compile(r"<(style|script)\b[^>]*>.*?</\1\s*>", re.S | re.I)
_BR = re.compile(r"<br\s*/?>|</p\s*>|</div\s*>", re.I)
_TAG = re.compile(r"<[^>]+>")
_NBSP = re.compile(r"[ ​]")
_BLANKS = re.compile(r"\n{3,}")
_SPACES = re.compile(r"[ \t]+")


def clean_html(raw: str | None) -> str:
    """설명문 HTML 을 읽을 수 있는 평문으로. 문단 구분만 개행으로 남긴다."""
    if not raw:
        return ""
    t = _BLOCK.sub(" ", raw)
    t = _BR.sub("\n", t)
    t = _TAG.sub(" ", t)
    t = _NBSP.sub(" ", t)
    t = (t.replace("&nbsp;", " ").replace("&amp;", "&")
          .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    t = _SPACES.sub(" ", t)
    t = "\n".join(line.strip() for line in t.split("\n"))
    return _BLANKS.sub("\n\n", t).strip()


# 주소 끝의 (한글 동/건물명). 영문 UI 라 지운다. 310건 중 9건.
_KO_ADDR = re.compile(r"\s*\([^)]*[가-힣][^)]*\)\s*$")


def clean_address(raw: str | None) -> str:
    return _KO_ADDR.sub("", one_line(raw)).rstrip(" ,")


def one_line(raw: str | None) -> str:
    """영업시간·지하철 안내처럼 짧은 값에 섞인 개행을 접는다."""
    return _SPACES.sub(" ", (raw or "").replace("\r", " ").replace("\n", " ")).strip()


def build(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for r in rows:
        d = r.get("detail")
        if not d:
            continue
        traffic = d.get("traffic") or {}
        extra = d.get("extra") or {}

        lat, lng = traffic.get("map_position_y"), traffic.get("map_position_x")
        if not (lat and lng):
            continue  # 지도에 못 찍고 거리도 못 재는 건 목록에 둘 이유가 없다.

        depth = (d.get("cate_depth") or r.get("cate_depth") or "").strip()
        category = CATEGORIES.get(depth, BARE_CATEGORY if depth == BARE else None)
        if category is None:
            continue

        out.append({
            "id": d.get("cid") or r["cid"],
            "title": (d.get("post_sj") or r.get("post_sj") or "").strip(),
            "category": category,
            "address": clean_address(traffic.get("new_adres") or traffic.get("adres")),
            "lat": float(lat),
            "lng": float(lng),
            # 이미지 호스트는 https 지만 tour_poi 와 같은 이유로 한 번 더 막는다.
            "image": (d.get("main_img") or "").replace("http://", "https://", 1),
            "summary": one_line(d.get("sumry")),
            "overview": clean_html(d.get("post_desc")),
            "hours": one_line(extra.get("cmmn_use_time")),
            "tel": one_line(extra.get("cmmn_telno")),
            "homepage": one_line(extra.get("cmmn_hmpg_url")),
            "subway": one_line(traffic.get("subway_info")),
        })
    out.sort(key=lambda p: (p["category"], p["title"]))
    return out


def main() -> None:
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    pois = build(rows)
    OUT.write_text(json.dumps(pois, ensure_ascii=False, indent=1), encoding="utf-8")

    counts: dict[str, int] = {}
    for p in pois:
        counts[p["category"]] = counts.get(p["category"], 0) + 1
    print(f"{SRC.name} {len(rows)} → {OUT.name} {len(pois)}")
    for code, name in CATEGORY_NAMES.items():
        print(f"  {code} {name:13} {counts.get(code, 0)}")
    for f in ("hours", "tel", "homepage", "subway", "overview"):
        n = sum(1 for p in pois if p[f])
        print(f"  with {f:9} {n}/{len(pois)}")
    print(f"  {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
