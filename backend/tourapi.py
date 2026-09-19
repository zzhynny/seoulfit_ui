"""한국관광공사 TourAPI(EngService2) 런타임 클라이언트.

`fetch_tourapi.py` 의 오프라인 배치와 같은 서비스를 치지만 쓰임이 다르다 —
배치는 몇 시간짜리 수집이고 이쪽은 요청 하나를 처리하는 중에 불린다. 그래서
페이징 루프가 없고, 예외 메시지에서 키를 지우고, 클라이언트를 한 번만 만든다.

    rows, total = tourapi.items("locationBasedList2", mapX=..., mapY=..., radius=1000)

키는 data.go.kr 계정 인증키 하나를 모든 서비스가 공유한다. `EGEN_API_KEY` 가
이미 그 키라서 TourAPI 용으로 따로 받을 필요가 없고, 나중에 분리하고 싶으면
`TOURAPI_KEY` 를 넣으면 그쪽이 이긴다.
"""

from __future__ import annotations

import os
import re
import threading

import httpx

BASE = "https://apis.data.go.kr/B551011/EngService2"
SEOUL = "11"

# 오퍼레이션마다 각각 1,000회/일. 런타임 호출이 쿼터를 태우지 않도록 부르는
# 쪽에서 캐시하고, 여기서는 한 번에 받아올 최대 건수만 막아둔다.
MAX_ROWS = 300

# 배치의 30초와 다르다. 사용자가 기다리는 요청 안에서 불린다.
#
# 15초가 아니라 4초인 이유: 부르는 쪽(/poi-summary · /poi-detail · /poi-image)은
# 전부 여기서 miss 나면 Tavily + Gemini 로 넘어간다. 그 폴백까지가 한 번의 클라이언트
# 요청(30초 타임아웃) 안에 들어가야 하는데, 공사 API 가 느린 날 15초를 먼저 태우면
# 남은 예산으로 폴백을 끝낼 수 없어 시트가 통째로 비어 돌아온다 — 실제로 그랬다.
# 4 + 8(Tavily) + 12(Gemini) = 24초, 6초 여유.
_TIMEOUT = 4.0

_SECRET = re.compile(r"(serviceKey|apiKey|key)=[^&\s\'\"]+", re.I)
_HANGUL_PAREN = re.compile(r"\s*\([^()]*[가-힣][^()]*\)")

_client: httpx.Client | None = None
_lock = threading.Lock()


class NotConfigured(RuntimeError):
    """data.go.kr 인증키가 없다."""


def key() -> str:
    return os.getenv("TOURAPI_KEY") or os.getenv("EGEN_API_KEY") or ""


def redact(msg: str) -> str:
    """예외 메시지·로그에 섞인 인증키를 지운다."""
    return _SECRET.sub(r"\1=REDACTED", str(msg))


def _get_client() -> httpx.Client:
    global _client
    with _lock:
        if _client is None:
            k = key()
            if not k:
                raise NotConfigured("TOURAPI_KEY / EGEN_API_KEY not configured")
            _client = httpx.Client(
                timeout=_TIMEOUT,
                params={
                    "serviceKey": k,
                    "MobileOS": "ETC",
                    "MobileApp": "SeoulFit",
                    "_type": "json",
                },
            )
        return _client


def items(op: str, **params) -> tuple[list[dict], int]:
    """오퍼레이션 1회 호출 → (레코드 리스트, totalCount).

    실패하면 예외를 던진다. 부르는 쪽이 로컬 폴백을 갖고 있으므로 여기서
    빈 리스트로 삼키면 장애가 '결과 없음' 으로 둔갑한다.
    """
    params.setdefault("numOfRows", MAX_ROWS)
    params.setdefault("pageNo", 1)

    r = _get_client().get(f"{BASE}/{op}", params=params)
    r.raise_for_status()

    # 트래픽 초과·키 오류는 200 에 XML 로 온다. JSON 파서에 넣기 전에 잡는다.
    if not r.text.lstrip().startswith("{"):
        raise RuntimeError(redact(f"{op}: non-JSON response {r.text[:200]}"))

    d = r.json()
    if "response" not in d:  # GW 레벨 오류
        raise RuntimeError(redact(f"{op}: {d.get('resultCode')} {d.get('resultMsg')}"))

    body = d["response"]["body"]
    it = body.get("items")
    if not it:  # 결과 0건이면 items 가 빈 문자열로 온다
        return [], 0
    row = it["item"]
    return (row if isinstance(row, list) else [row]), int(body.get("totalCount") or 0)


def name_of(title: str) -> str:
    """`English (한글)` 형식의 TourAPI 제목에서 영문만 남긴다.

    괄호 앞 공백이 있는 것과 없는 것이 섞여 있고("Gyeongbokgung Palace (경복궁)"
    vs "Bongsan Mask Dance(봉산탈춤 다 모여라~ )"), 괄호 안이 영문인 제목도
    있다("Seoul Robot & AI Museum (RAIM)"). 그래서 위치가 아니라 내용으로
    판단한다 — 한글이 든 괄호만 떼고 나머지는 그대로 둔다.
    """
    return _HANGUL_PAREN.sub("", title).strip()
