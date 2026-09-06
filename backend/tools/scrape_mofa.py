"""주한공관주소록(외교부)을 긁어 _mofa_raw.json 으로 떨군다.

    uv run --with httpx python backend/tools/scrape_mofa.py
    uv run python backend/tools/normalize.py      # → assets/data/embassies.json

원본: https://www.mofa.go.kr/www/pgm/m_4073/uss/cnsrshp/inKoEmblgbdAdres.do
공관 정보가 갱신되면 두 스크립트를 순서대로 다시 돌리면 된다.
"""
import html, json, re, sys, time
from pathlib import Path

import httpx

URL = "https://www.mofa.go.kr/www/pgm/m_4073/uss/cnsrshp/inKoEmblgbdAdres.do"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"

RAW = Path(__file__).resolve().parent / "_mofa_raw.json"

client = httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=30)

# 공관명은 홈페이지가 있으면 <a href>, 없으면 <strong> 으로 감싸 나온다. 둘 다 받는다.
ITEM = re.compile(r"<li>\s*<h3>(.*?)</h3>\s*<ul>(.*?)</ul>", re.S)
HREF = re.compile(r'href="([^"]*)"')
FIELD = re.compile(r"<b>\s*(.*?)\s*:\s*</b>\s*(.*?)\s*</li>", re.S)


def clean(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s)).strip()


rows = []
for page in range(1, 33):
    # 첫 요청은 307 + TMOSHCooKie 를 물린다. Client 가 쿠키를 들고 리다이렉트를 따라간다.
    h = client.post(URL, data={"cPage": page, "srchOrd": "", "srchTxt": ""}).text
    body = h[h.find('bo_list2') : h.find('class="pagination"')]
    found = ITEM.findall(body)
    if not found:
        print(f"page {page}: 0 items — 구조가 바뀌었거나 차단됨", file=sys.stderr)
        sys.exit(1)
    for head, blob in found:
        m = HREF.search(head)
        rec = {"mission_ko": clean(head), "website": (m.group(1).strip() if m else "")}
        for k, v in FIELD.findall(blob):
            rec[clean(k)] = clean(v)
        rows.append(rec)
    print(f"page {page}: {len(found)} (total {len(rows)})", file=sys.stderr)
    time.sleep(0.4)

RAW.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"wrote {RAW.name} — {len(rows)} rows")
