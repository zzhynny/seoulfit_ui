"""dataset/poi_images.json 을 만든다 — course_data_v6.json 의 source_url 에서 정거장별 사진 URL 을 긁는다.

    python backend/scripts/scrape_poi_images.py              # 전량 (125 코스, 약 2분)
    python backend/scripts/scrape_poi_images.py --selfcheck  # 파서 회귀 검사 (2 코스)
    python backend/scripts/scrape_poi_images.py --limit 5    # 앞 5 코스만

산출물: backend/dataset/poi_images.json  {poi_name: image_url}
        → api.py 의 /poi-image 가 SerpApi 를 치기 전에 먼저 뒤진다.

왜 있냐면: /poi-image 가 POI 하나당 Gemini 2회 + SerpApi 1회를 쓴다. 카드 한 장에
3초씩, 화면 하나에 수십 장이다. 정작 코스 원본 페이지(visitseoul / visitkorea)가
정거장별 공식 사진을 이미 들고 있고, 둘 다 JS 없이 정적 HTML 로 나온다. 한 번 긁어
이름→URL 로 박아두면 런타임이 dict 조회가 된다.

두 소스 모두 '이름'으로 맞춘다. 순서로 맞추면 v6 의 정거장이 원본과 한 칸이라도
어긋나는 순간 엉뚱한 사진이 조용히 박힌다.
  - visitseoul: li.course-item 안에 h5.course-title 과 .course-img img 가 같이 있다.
    제목은 영문만이라 v6 의 "이름 (한글)" 에서 한글 괄호를 떼고 맞춘다.
  - visitkorea: 본문이 JS 렌더라 DOM 은 비어 있지만, 인라인 스크립트에
    contsNm.push(...) / rprsImg.push(...) 가 같은 순서로 박혀 있다. contsNm 은
    v6 의 poi_name 과 글자까지 같아서 그대로 맞으면 된다.

v6 의 is_generic_activity 플래그는 걸러내지 않는다. "Seongsu Self-Photo Booths"
처럼 플래그는 붙었는데 원본 페이지엔 버젓이 사진이 있는 게 있다. 이름이 맞으면
가져오고, 없으면 없는 대로 둔다 — 판단은 이름 대조에 맡긴다.

같은 POI 가 여러 코스에 나오면 먼저 찾은 쪽을 쓴다. 어느 코스 사진이든 그 장소를
찍은 공식 사진이라 우열이 없다.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from pathlib import Path

from scrapling.fetchers import Fetcher

BACKEND = Path(__file__).resolve().parent.parent
COURSE_DATA = BACKEND / "dataset" / "course_data_v6.json"
OUT = BACKEND / "dataset" / "poi_images.json"

# --selfcheck 가 쓰는 고정 표본. 소스별로 하나씩, 기대 정거장 수까지 박아둔다.
SELFCHECK = {"VS_MVP_001": 7, "VK_THEME_001": 4}

_HANGUL = re.compile(r"[가-힣]")
_NONWORD = re.compile(r"[^0-9a-z]+")
_BRACKET = re.compile(r"\[[^\[\]]*\]")
# contsNm.push("...") / rprsImg.push("...") — 값에 이스케이프된 따옴표는 안 나온다.
_VK_NAMES = re.compile(r'contsNm\.push\("([^"]*)"\)')
_VK_IMAGES = re.compile(r'rprsImg\.push\("([^"]*)"\)')


def _strip_hangul_parens(name: str) -> str:
    """이름 뒤에 붙은 한글 괄호를 뗀다.

    "Seoul Forest (서울숲)" → "Seoul Forest"
    "Songpa Naru Park (Seokchonhosu Lake) (송파나루공원 (석촌호수))" 처럼 괄호가
    중첩되고 영문 괄호까지 섞인 게 있어서, 안쪽부터 한글이 든 짝만 골라 반복해 뗀다.
    """
    while True:
        for m in re.finditer(r"\(([^()]*)\)", name):
            if _HANGUL.search(m.group(1)):
                name = name[: m.start()] + name[m.end():]
                break
        else:
            return name.strip()


def _norm(name: str) -> str:
    """이름 대조용 키. 한글 괄호·대괄호 수식어·대소문자·구두점·공백 차이를 흡수한다.

    대괄호는 통째로 뗀다. 원본이 이름 뒤에 등급이나 분류를 달아 놓는 자리라
    (v6 "Jongmyo Shrine" vs 페이지 "Jongmyo Shrine [UNESCO World Heritage]",
    tourapi 의 "[Tax Refund Shop]") 이름의 일부인 적이 없었다.
    """
    return _NONWORD.sub("", _strip_hangul_parens(_BRACKET.sub(" ", name)).lower())


def _fetch(url: str):
    return Fetcher.get(url, stealthy_headers=True, timeout=30)


def _parse_visitseoul(url: str) -> dict[str, str]:
    """{페이지에 적힌 정거장 이름: 사진 URL}.

    li.course-item 이 없으면 구식 템플릿이다. 30개쯤 남아 있는데, 에디터로 자유
    편집한 기사라 정거장 구조가 아예 없고 사진도 'K-Beauty Items' 같은 섹션 삽화다.
    순서로 우겨넣으면 엉뚱한 사진이 박히므로 빈손으로 돌려보내고 SerpApi 에 맡긴다.
    """
    out: dict[str, str] = {}
    items = _fetch(url).css("li.course-item")
    if not items:
        print("    - 구식 템플릿(정거장 구조 없음) — SerpApi 로 넘김")
        return out
    for item in items:
        title = item.css("h5.course-title")
        img = item.css("div.course-img img")
        if not title or not img:
            continue
        src = html.unescape((img[0].attrib.get("src") or "").strip())
        name = html.unescape(title[0].text.strip())
        if name and src:
            out[name] = src
    return out


def _parse_visitkorea(url: str) -> dict[str, str]:
    """{contsNm: rprsImg}. 두 배열 길이가 다르면 페이지가 바뀐 것이라 통째로 버린다."""
    page = _fetch(url).html_content
    names = _VK_NAMES.findall(page)
    images = _VK_IMAGES.findall(page)
    if len(names) != len(images):
        print(f"    ! contsNm {len(names)}개 vs rprsImg {len(images)}개 — 코스 통째로 건너뜀")
        return {}
    # 스크립트 안의 값은 HTML 이스케이프된 채다 — "Lotte World Tower &amp; Mall".
    # v6 는 "&" 로 갖고 있어서 풀어주지 않으면 이름이 안 맞는다.
    return {html.unescape(n): html.unescape(i) for n, i in zip(names, images) if n and i}


PARSERS = (
    ("visitseoul.net", _parse_visitseoul),
    ("visitkorea.or.kr", _parse_visitkorea),
)


def _parser_for(url: str):
    for host, fn in PARSERS:
        if host in url:
            return fn
    return None


def scrape_course(course: dict) -> tuple[dict[str, str], list[str]]:
    """한 코스 → ({v6 poi_name: 사진 URL}, 못 찾은 poi_name 목록)."""
    stops = course.get("sequence", [])
    parser = _parser_for(course["source_url"])
    if parser is None:
        return {}, [s["poi_name"] for s in stops]

    scraped = parser(course["source_url"])
    by_norm = {_norm(k): v for k, v in scraped.items()}

    found, missing = {}, []
    for stop in stops:
        name = stop["poi_name"]
        url = scraped.get(name) or by_norm.get(_norm(name))
        if url:
            found[name] = url
        else:
            missing.append(name)
    return found, missing


def selfcheck() -> None:
    # 이름 정규화부터. 네트워크 없이 도는 부분이고, 여기가 틀리면 대조가 조용히
    # 빗나가서 사진이 통째로 비거나 엉뚱하게 붙는다.
    assert _strip_hangul_parens("Seoul Forest (서울숲)") == "Seoul Forest"
    # 영문 괄호는 살리고 한글 괄호만 뗀다. 중첩된 놈이 실제로 v6 에 있다.
    assert _strip_hangul_parens(
        "Songpa Naru Park (Seokchonhosu Lake) (송파나루공원 (석촌호수))"
    ) == "Songpa Naru Park (Seokchonhosu Lake)"
    assert _strip_hangul_parens("HiKR GROUND") == "HiKR GROUND"
    # 대소문자·구두점·공백 차이는 흡수해야 한다: v6 "HiKR GROUND" vs 페이지 "HiKR Ground"
    assert _norm("HiKR GROUND (하이커 그라운드)") == _norm("HiKR Ground")
    assert _norm("Ewha Womans Univ. (이화여대)") == _norm("Ewha Womans Univ")
    # 대괄호 수식어는 이름의 일부가 아니다: v6 "Jongmyo Shrine" vs 페이지 쪽 긴 이름
    assert _norm("Jongmyo Shrine (종묘)") == _norm(
        "Jongmyo Shrine [UNESCO World Heritage] (종묘 [유네스코 세계유산])"
    )
    # HTML 이스케이프를 푼 뒤라야 맞는다 — 파서가 unescape 를 빼먹으면 여기서 걸린다.
    assert _norm("Lotte World Tower & Mall (롯데월드타워&롯데월드몰)") == _norm(
        html.unescape("Lotte World Tower &amp; Mall (롯데월드타워&amp;롯데월드몰)")
    )
    # 서로 다른 장소가 같은 키로 뭉개지면 안 된다.
    assert _norm("Seoul Forest (서울숲)") != _norm("Seoul Plaza (서울광장)")
    print("[selfcheck] 이름 정규화 OK")

    courses = {c["course_id"]: c for c in json.loads(COURSE_DATA.read_text(encoding="utf-8"))}
    for course_id, expected in SELFCHECK.items():
        found, missing = scrape_course(courses[course_id])
        assert not missing, f"{course_id}: 이름 대조 실패 {missing}"
        assert len(found) == expected, f"{course_id}: {len(found)}개, {expected}개 기대"
        assert all(u.startswith("https://") for u in found.values()), f"{course_id}: URL 아닌 값"
        print(f"[selfcheck] {course_id} OK — {len(found)}개 전부 이름으로 맞음")
    print("[selfcheck] 파서 정상")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selfcheck", action="store_true", help="표본 2 코스로 파서만 검사")
    ap.add_argument("--limit", type=int, help="앞 N 코스만")
    ap.add_argument("--delay", type=float, default=0.5, help="요청 간 간격(초)")
    args = ap.parse_args()

    if args.selfcheck:
        selfcheck()
        return 0

    courses = json.loads(COURSE_DATA.read_text(encoding="utf-8"))[: args.limit]
    images: dict[str, str] = {}

    for n, course in enumerate(courses, 1):
        stops = course.get("sequence", [])
        try:
            found, missing = scrape_course(course)
        except Exception as exc:  # 코스 하나 때문에 전량을 다시 돌릴 이유가 없다
            print(f"[{n}/{len(courses)}] {course['course_id']} 실패: {exc}")
            continue

        # 먼저 찾은 쪽을 남긴다.
        images.update({k: v for k, v in found.items() if k not in images})
        print(f"[{n}/{len(courses)}] {course['course_id']} {len(found)}/{len(stops)}"
              + (f" — 못 찾음: {', '.join(missing)}" if missing and found else ""))
        time.sleep(args.delay)

    OUT.write_text(json.dumps(images, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")

    # 진행 로그의 코스별 숫자보다 이쪽이 크다. A 코스에서 긁은 사진이 같은 POI 를
    # 쓰는 B 코스에도 그대로 붙기 때문이다. 런타임에 실제로 맞는 건 이 숫자다.
    stops = [s["poi_name"] for c in courses for s in c.get("sequence", [])]
    covered = sum(1 for name in stops if name in images)
    print(f"\n{OUT.relative_to(BACKEND)} — 고유 POI {len(images)}개 "
          f"(정거장 {covered}/{len(stops)}, {covered / max(len(stops), 1):.0%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
