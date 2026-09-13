"""dataset/poi_images.json 의 빈 자리를 SerpApi 로 채운다 — 후보만 받아온다.

    python backend/scripts/backfill_missing_images.py fetch              # 후보 다운로드
    python backend/scripts/backfill_missing_images.py fetch --limit 10   # 표본
    python backend/scripts/backfill_missing_images.py apply verdicts.json # 판정 반영
    python backend/scripts/backfill_missing_images.py --selfcheck

scrape_poi_images.py 는 코스 원본 페이지에서 긁을 수 있는 것만 채웠다 (211개).
나머지는 원본 페이지에 사진 구조가 없거나 v6 정거장이 페이지에서 사라진
경우라 그쪽으로는 더 못 채운다.

여기서부터는 /poi-image 런타임과 같은 1~2단계(Gemini 검색어 생성 → SerpApi 상위
5개 → Gemini 가 제목만 보고 1개 고름)를 오프라인으로 미리 돌린다. 텍스트만
쓰는 두 단계라 저렴하다. 그 사진이 진짜 맞는지는 Gemini Vision 을 또 부르는
대신(이미지 토큰은 비싸다) 로컬로 받아두고 사람이 직접 눈으로 본다 — 이 리포를
보는 사람은 이미 화면을 볼 수 있으니 그게 공짜다.

fetch  → dataset/_pending_review/<slug>.jpg + manifest.json
apply  → {poi_name: {"verdict": "match"|"reject", "reason": "..."}} 형식의
         verdicts.json 을 받아 poi_images.json 에 병합하고 나머지는
         poi_images_review.md 에 남긴다. _pending_review/ 는 지운다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parent.parent
COURSE_DATA = BACKEND / "dataset" / "course_data_v6.json"
IMAGES = BACKEND / "dataset" / "poi_images.json"
REVIEW = BACKEND / "dataset" / "poi_images_review.md"
PENDING_DIR = BACKEND / "dataset" / "_pending_review"
MANIFEST = PENDING_DIR / "manifest.json"

load_dotenv(BACKEND / ".env")
import os

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


def load_courses() -> list[dict[str, Any]]:
    return json.loads(COURSE_DATA.read_text(encoding="utf-8"))


def missing_pois(courses: list[dict[str, Any]], have: dict[str, str]) -> list[dict[str, Any]]:
    """{poi_name, poi_type, course_ids} — 사진이 없는 고유 POI."""
    out: dict[str, dict[str, Any]] = {}
    for c in courses:
        for s in c.get("sequence", []):
            name = s["poi_name"]
            if name in have:
                continue
            if name not in out:
                out[name] = {"poi_name": name, "poi_type": s.get("poi_type", ""), "course_ids": []}
            out[name]["course_ids"].append(c["course_id"])
    return list(out.values())


def _slug(name: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z가-힣]+", "_", name).strip("_")
    return s[:60] or "poi"


# ---------------------------------------------------------------------------
# /poi-image 런타임과 같은 검색어 생성 + SerpApi 조회 (텍스트만, 저렴하다)
# ---------------------------------------------------------------------------

def _gemini_text(client, prompt: str) -> str:
    resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    return (resp.text or "").strip()


def search_candidates(client, name: str, poi_type: str) -> list[dict[str, str]]:
    import serpapi

    type_hint = f" ({poi_type})" if poi_type else ""
    query = _gemini_text(
        client,
        f"Generate a concise Google Images search query (max 8 words) to find a "
        f"photo of '{name}'{type_hint} in Seoul, South Korea. Make it specific "
        "enough to avoid confusion with similarly named places or people "
        "elsewhere in the world. Return only the search query string, nothing else.",
    ).strip('"')

    serp = serpapi.Client(api_key=SERPAPI_KEY)
    results = serp.search({
        "engine": "google_images_light",
        "google_domain": "google.co.kr",
        "q": query,
        "hl": "en",
        "gl": "kr",
        "location": "Seoul, Seoul, South Korea",
        "safe": "active",
        "image_type": "photo",
    })
    return (results.get("images_results") or [])[:5], query


def pick_thumbnail(client, name: str, poi_type: str, candidates: list[dict[str, str]]) -> str:
    """제목만 보고 하나를 고른다.

    Gemini 에게 URL 문자열을 그대로 돌려달라고 하면(런타임 /poi-image 가 실제로
    이렇게 한다) 가끔 옮겨 적다가 끝을 잘라먹는다 — gstatic 썸네일은 쿼리 문자열
    끝 "=10" 하나 빠지면 404 로 바뀐다. 번호(1~5)만 고르게 하고 URL 은 우리가
    candidates 에서 그대로 꺼내면 이 부류의 오류가 원천적으로 없다.
    """
    if not candidates:
        return ""
    type_hint = f" ({poi_type})" if poi_type else ""
    listing = "\n".join(
        f"{i + 1}. title={c.get('title', '')!r}"
        for i, c in enumerate(candidates)
    )
    reply = _gemini_text(
        client,
        f"I need a photo of '{name}'{type_hint} in Seoul, South Korea.\n"
        f"Here are {len(candidates)} image search results (titles only):\n{listing}\n\n"
        "Reply with ONLY the number of the one that best shows the actual Seoul "
        "location. If none of them clearly show the correct place, reply exactly: none",
    ).strip()
    if not reply or reply.lower() == "none":
        return ""
    m = re.match(r"\d+", reply)
    if not m:
        return ""
    idx = int(m.group()) - 1
    return candidates[idx]["thumbnail"] if 0 <= idx < len(candidates) else ""


def _download(url: str) -> tuple[bytes, str] | None:
    try:
        r = httpx.get(url, timeout=20, follow_redirects=True,
                       headers={"User-Agent": "Mozilla/5.0"})
        ctype = r.headers.get("content-type", "")
        if r.status_code == 200 and ctype.startswith("image/"):
            return r.content, ctype.split(";")[0]
    except Exception:
        pass
    return None


_EXT = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


def cmd_fetch(args: argparse.Namespace) -> int:
    if not SERPAPI_KEY or not GEMINI_API_KEY:
        print("SERPAPI_KEY / GEMINI_API_KEY 가 .env 에 없다.")
        return 1
    from google import genai as _genai
    client = _genai.Client(api_key=GEMINI_API_KEY)

    have = json.loads(IMAGES.read_text(encoding="utf-8")) if IMAGES.exists() else {}
    pois = missing_pois(load_courses(), have)[: args.limit]
    PENDING_DIR.mkdir(exist_ok=True)

    manifest: dict[str, Any] = {}
    no_candidate: list[dict[str, Any]] = []
    errored: list[dict[str, Any]] = []

    for n, poi in enumerate(pois, 1):
        name, poi_type = poi["poi_name"], poi["poi_type"]
        try:
            candidates, query = search_candidates(client, name, poi_type)
            chosen = pick_thumbnail(client, name, poi_type, candidates)
            if not chosen:
                print(f"[{n}/{len(pois)}] NONE   {name}  (검색어: {query!r})")
                no_candidate.append(poi)
                continue

            dl = _download(chosen)
            if dl is None:
                print(f"[{n}/{len(pois)}] ERR    {name}  다운로드 실패: {chosen}")
                errored.append({**poi, "detail": f"다운로드 실패: {chosen}"})
                continue

            image_bytes, mime_type = dl
            slug = _slug(name)
            path = PENDING_DIR / f"{slug}.{_EXT.get(mime_type, 'jpg')}"
            path.write_bytes(image_bytes)
            manifest[name] = {**poi, "url": chosen, "query": query, "local_path": str(path)}
            print(f"[{n}/{len(pois)}] ok     {name}  -> {path.name}")
        except Exception as exc:
            print(f"[{n}/{len(pois)}] ERR    {name}  {type(exc).__name__}: {exc}")
            errored.append({**poi, "detail": f"{type(exc).__name__}: {exc}"})
        time.sleep(args.delay)

    MANIFEST.write_text(json.dumps(
        {"manifest": manifest, "no_candidate": no_candidate, "errored": errored},
        ensure_ascii=False, indent=2,
    ), encoding="utf-8")
    print(f"\n후보 확보 {len(manifest)} / 후보 없음 {len(no_candidate)} / 에러 {len(errored)}")
    print(f"이미지: {PENDING_DIR.relative_to(BACKEND)}/   판정 대상: {MANIFEST.relative_to(BACKEND)}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    """verdicts.json = {poi_name: {"verdict": "match"|"reject", "reason": "..."}}."""
    if not MANIFEST.exists():
        print(f"{MANIFEST} 없음 — 먼저 fetch 를 돌려야 한다.")
        return 1
    state = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest, no_candidate, errored = state["manifest"], state["no_candidate"], state["errored"]
    verdicts = json.loads(Path(args.verdicts).read_text(encoding="utf-8"))

    have = json.loads(IMAGES.read_text(encoding="utf-8")) if IMAGES.exists() else {}
    rejected = []
    unjudged = []
    for name, info in manifest.items():
        v = verdicts.get(name)
        if v is None:
            unjudged.append(info)
        elif v.get("verdict") == "match":
            have[name] = info["url"]
        else:
            rejected.append({**info, "reason": v.get("reason", "")})

    IMAGES.write_text(json.dumps(have, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# 이미지 확보 실패 — 검토 필요 목록",
        "",
        f"매치 {sum(1 for v in verdicts.values() if v.get('verdict') == 'match')} / "
        f"거부 {len(rejected)} / 미판정 {len(unjudged)} / "
        f"후보 없음 {len(no_candidate)} / 에러 {len(errored)}",
        "",
        "## 거부됨 — SerpApi 후보가 있었지만 그 장소가 아니라고 판단",
        "",
    ]
    for r in rejected:
        lines.append(f"- **{r['poi_name']}** ({r['poi_type']}) — 후보: {r['url']}\n"
                      f"  판단: {r['reason']}\n"
                      f"  코스: {', '.join(r['course_ids'])}")
    lines += ["", "## 후보 없음 — SerpApi/Gemini 가 아무 사진도 못 찾음", ""]
    for r in no_candidate:
        lines.append(f"- **{r['poi_name']}** ({r['poi_type']}) — 코스: {', '.join(r['course_ids'])}")
    if unjudged:
        lines += ["", "## 미판정 — verdicts.json 에 없었음", ""]
        for r in unjudged:
            lines.append(f"- **{r['poi_name']}** — {r['url']}")
    if errored:
        lines += ["", "## 에러", ""]
        for r in errored:
            lines.append(f"- **{r['poi_name']}** — {r['detail']}")

    REVIEW.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{IMAGES.relative_to(BACKEND)} 갱신, {REVIEW.relative_to(BACKEND)} 작성")
    return 0


def selfcheck() -> None:
    assert _slug("Mosim (모심)") == "Mosim_모심"
    assert _slug("Café Dior (카페 디올)").startswith("Caf")
    print("[selfcheck] slug OK")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selfcheck", action="store_true")
    sub = ap.add_subparsers(dest="cmd")

    p_fetch = sub.add_parser("fetch")
    p_fetch.add_argument("--limit", type=int)
    p_fetch.add_argument("--delay", type=float, default=0.3)

    p_apply = sub.add_parser("apply")
    p_apply.add_argument("verdicts")

    args = ap.parse_args()
    if args.selfcheck:
        selfcheck()
        return 0
    if args.cmd == "fetch":
        return cmd_fetch(args)
    if args.cmd == "apply":
        return cmd_apply(args)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
