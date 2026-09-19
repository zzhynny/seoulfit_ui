"""poi_text.py — the per-stop text the app shows, grounded in a web search.

Two kinds: "summary" (1-2 sentences on the card) and "detail" (Hours / Entry /
Highlight / Tip bullets in the place detail sheet).

Gemini never describes a place from memory here. Tavily (basic depth) finds
what the web says, and Gemini only rewrites that into the app's short format,
told to use nothing else and to answer NONE when the search doesn't clearly
describe the place. No web result means no text — the app keeps the planner's
own note rather than a guess.

Answers are cached on disk per place, so a stop reads the same on every screen
and every app launch, and each search is paid for once. Errors aren't cached.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

CACHE_PATH = Path(__file__).resolve().parent / "_poi_text_cache.json"
# Hours and fees drift; two weeks keeps "Before you go" reasonably fresh.
CACHE_TTL = 14 * 24 * 3600
_WEB_CHARS = 6000

# 이 두 호출은 타임아웃이 아예 없었다. 부르는 쪽은 사용자가 POI 를 탭한 순간
# 시작된 요청이고, 클라이언트는 30초에 끊는다(api_service._fetchPoiField).
# 공사 API 4초를 먼저 쓰고 나면 남는 게 26초라, 둘을 합쳐 그 안에 끝나게 묶는다.
# 정상일 때 Tavily 는 1~3초, Gemini 는 1~4초다 — 이 값들은 상한이지 목표가 아니다.
_TAVILY_TIMEOUT = 8        # seconds
_GEMINI_TIMEOUT_MS = 12_000  # google-genai 의 HttpOptions.timeout 은 밀리초다

# ponytail: one JSON file rewritten per new answer, same as odsay's cache. Move
# to SQLite if it grows past a few thousand places or runs multi-worker.
_CACHE: dict[str, list] = {}   # "kind|name" -> [expires_at, text]
_lock = threading.Lock()


class NotConfigured(RuntimeError):
    """TAVILY_API_KEY is missing and the answer isn't cached."""


def _load_cache_from_disk() -> None:
    try:
        raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw = {}  # 파일 없음/손상 — 빈 캐시로 시작. 캐시가 기능을 막아선 안 된다.
    with _lock:
        _CACHE.clear()
        _CACHE.update({k: [float(v[0]), v[1]] for k, v in raw.items()})


def _flush_cache_to_disk() -> None:
    try:
        # 직렬화만 락 안에서 하고 쓰기를 밖에서 하면, 동시 호출 둘이 같은 tmp
        # 경로를 각자 truncate 해서 열고 내용이 섞인다. rename 은 원자적이어도
        # 그 앞의 write 가 아니라서, 반쯤 쓰인 파일이 캐시 자리에 들어앉는다.
        # 다음 기동에 JSON 파싱이 깨져 {} 로 시작하고, 이미 값을 치른 Tavily/
        # Gemini 결과를 전부 다시 사기 시작한다. 쓰기까지 락 안에 둔다.
        with _lock:
            text = json.dumps(_CACHE, ensure_ascii=False)
            tmp = CACHE_PATH.with_suffix(".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(CACHE_PATH)  # atomic rename — 쓰는 도중 죽어도 파일이 안 깨짐
    except Exception as e:
        print(f"[poi_text] cache write failed: {e}")


def _web_search(query: str) -> str:
    """Tavily basic search: its short answer plus the top result snippets."""
    from tavily import TavilyClient

    response = TavilyClient(api_key=os.getenv("TAVILY_API_KEY", "")).search(
        query=query,
        search_depth="basic",
        max_results=3,
        include_answer=True,
        timeout=_TAVILY_TIMEOUT,
    )
    parts = [response.get("answer") or ""]
    parts += [r.get("content") or "" for r in response.get("results") or []]
    return "\n\n".join(p.strip() for p in parts if p and p.strip())[:_WEB_CHARS]


def _rewrite(prompt: str) -> str:
    from google import genai
    from google.genai import types

    response = genai.Client(
        api_key=os.getenv("GEMINI_API_KEY"),
        http_options=types.HttpOptions(timeout=_GEMINI_TIMEOUT_MS),
    ).models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    return (response.text or "").strip()


# Seams for tests, like stamp._client.
_search = _web_search
_write = _rewrite

# kind -> (Tavily query, what Gemini should write from the results)
_KINDS = {
    "summary": (
        "{name} {type} Seoul South Korea",
        "write 1-2 engaging sentences in plain English describing what the place "
        "is and what visitors can experience there. No markdown.",
    ),
    "detail": (
        "{name} Seoul opening hours admission fee visitor tips highlights",
        "write exactly 3-4 short bullet lines with these labels, skipping any "
        "label the information doesn't cover:\n"
        "• Hours: ...\n• Entry: ...\n• Highlight: ...\n• Tip: ...\n"
        "Keep each line to one sentence or less and return only the bullet lines.",
    ),
}


def poi_text(kind: str, name: str, type_: str = "") -> str:
    """The web-grounded text of `kind` for one place, cached per place."""
    query_template, task = _KINDS[kind]
    key = f"{kind}|{' '.join(name.lower().split())}"
    with _lock:
        entry = _CACHE.get(key)
    if entry and time.time() < entry[0]:
        return entry[1]
    if not os.getenv("TAVILY_API_KEY"):
        raise NotConfigured("TAVILY_API_KEY not configured")

    web = _search(" ".join(query_template.format(name=name, type=type_).split()))
    text = ""
    if web:
        type_hint = f" ({type_})" if type_ else ""
        text = _write(
            f"Here is live web information about '{name}'{type_hint} in Seoul:\n\n"
            f"{web}\n\n"
            f"Using ONLY that information, {task} Do not add anything it doesn't "
            "say. If it doesn't clearly describe this specific place, reply with "
            "exactly: NONE"
        ).strip()
        if text.rstrip(".").upper() == "NONE":
            text = ""

    with _lock:
        _CACHE[key] = [time.time() + CACHE_TTL, text]
    _flush_cache_to_disk()
    return text


_load_cache_from_disk()
