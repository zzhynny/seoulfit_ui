"""_mofa_raw.json → assets/data/embassies.json.

국제기구를 걷어내고 전화번호·웹사이트를 정규화한 뒤 영문 국가명을 붙인다.
scrape_mofa.py 를 먼저 돌려야 한다.
"""
import json, re
from pathlib import Path

from names_en import COUNTRIES

_HERE = Path(__file__).resolve().parent
RAW = _HERE / "_mofa_raw.json"
OUT = _HERE.parent.parent / "assets" / "data" / "embassies.json"

AREA = {"서울": "02", "부산": "051", "인천": "032", "광주": "062", "제주": "064", "대구": "053"}
CONSULATE = re.compile(r"^주(부산|제주|광주|인천|대구)(.+?)(총영사관|영사관)$")
HOST_OK = re.compile(r"^https?://[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def blank(v):
    """원본은 '없음'을 '-' 나 '.' 로 적어둔 칸이 있다. 화면에 그대로 새면 안 된다."""
    v = (v or "").strip()
    return "" if v in {"-", ".", "_", "N/A", "n/a", "없음"} else v


def city_of(address):
    for c in AREA:
        if address.startswith(c):
            return c
    return "서울"


def dial(raw, area):
    """표기용 문자열에서 실제로 걸 수 있는 번호 하나를 뽑는다.

    원본은 '3785-1427/ 749-8982/3' 나 '794-6482~3' 처럼 여러 번호를 슬래시·물결로
    잇고 지역번호를 대부분 생략한다. 첫 번호만 취하고, 0 으로 시작하지 않으면
    지역번호를 붙인다.
    """
    first = re.split(r"[/,~∼]", raw.strip())[0]
    n = re.sub(r"[^\d]", "", first)
    if not n:
        return ""
    if n.startswith("0"):
        for code in ("02", "064", "051", "032", "062", "053"):
            if n.startswith(code) and len(n) > len(code):
                return f"{code}-{n[len(code):]}"
        return n
    return f"{area}-{n}"


def website(raw):
    w = (raw or "").strip()
    w = re.sub(r"^https?://(?=https?://)", "", w)  # 'http://https://…' 이중 접두 제거
    return w if HOST_OK.match(w) else ""


rows = json.loads(RAW.read_text(encoding="utf-8"))
out, skipped, offseoul = [], [], []
for r in rows:
    name = r["mission_ko"]
    m = CONSULATE.match(name)
    if m:
        city, country_ko, kind = m.group(1), m.group(2), "consulate"
    else:
        city, country_ko, kind = city_of(r.get("주소", "")), name, "embassy"
    if country_ko not in COUNTRIES:
        skipped.append(name)
        continue
    if city != "서울":
        # 서울 여행 앱이라 부산/제주/광주 영사관은 싣지 않는다.
        offseoul.append(name)
        continue
    en, iso = COUNTRIES[country_ko]
    area = AREA[city]
    out.append({
        "country_en": en,
        "country_ko": country_ko,
        "iso2": iso,
        "kind": kind,
        "mission_ko": name,
        "city": city,
        "postal_code": blank(r.get("우편번호")),
        "address_ko": re.sub(r"\s+", " ", r.get("주소", "")).strip(),
        "phone": blank(r.get("전화번호")),
        "phone_dial": dial(r.get("전화번호", ""), area),
        "email": blank(r.get("이메일")),
        "website": website(r.get("website")),
    })

out.sort(key=lambda x: x["country_en"])
OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{len(out)} missions  |  국제기구 {len(skipped)}건, 서울 외 {len(offseoul)}건 제외")
print("전화 다이얼 불가:", [x["mission_ko"] for x in out if not x["phone_dial"]])
print("웹사이트 보유:", sum(1 for x in out if x["website"]))

# 셀프체크 — 번호 파싱은 조용히 틀리면 tel: 링크가 엉뚱한 곳으로 걸린다.
assert dial("3785-1427/ 749-8982/3", "02") == "02-37851427"
assert dial("(051) 465-5104~6", "051") == "051-4655104"
assert dial("032) 458-6540/1", "032") == "032-4586540"
assert dial("02-6366-9905", "02") == "02-63669905"
assert dial(".", "02") == ""
assert blank("-") == "" and blank(" 03188 ") == "03188"
assert website("http://https://www.lebanoninkorea.com") == "https://www.lebanoninkorea.com"
assert website("http://-") == "" and website("http://") == ""
bad = [x for x in out if x["phone_dial"] and not 9 <= len(re.sub(r"\D", "", x["phone_dial"])) <= 11]
assert not bad, bad
print("self-check ok")
