"""Shared Seoul-neighborhood geography utilities.

Single source of truth for area aliases, geographic centers, and the logic
used to infer which neighborhood a POI belongs to. Imported by both rag.py
(Index B area metadata) and planner.py (Google Places fallback + validator).

Keeping this in one module prevents the two files from drifting out of sync
on alias lists, area centers, or radius thresholds.
"""

from __future__ import annotations

import math
import re
from typing import Any


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

SEOUL_AREA_CENTERS: dict[str, tuple[float, float]] = {
    "hongdae":    (37.5563, 126.9227),
    "hapjeong":   (37.5499, 126.9143),
    "mangwon":    (37.5530, 126.9028),
    "yeonnam":    (37.5663, 126.9236),
    "seongsu":    (37.5447, 127.0558),
    "wangsimni":  (37.5612, 127.0371),
    "gangnam":    (37.4979, 127.0276),
    "sinsa":      (37.5196, 127.0228),
    "garosu-gil": (37.5207, 127.0227),
    "jongno":     (37.5729, 126.9794),
    "insadong":   (37.5741, 126.9861),
    "myeongdong": (37.5636, 126.9857),
    "itaewon":    (37.5347, 126.9946),
    "yongsan":    (37.5326, 126.9770),
    "sinchon":    (37.5596, 126.9373),
    "dongdaemun": (37.5666, 127.0097),
    "yeouido":    (37.5217, 126.9244),
    "mapo":       (37.5479, 126.9130),
    "jamsil":     (37.5133, 127.1028),
    "dmc":        (37.5770, 126.8902),
    # 앱의 지역 질문(graph.py FIELD_EXTRACT["region"])이 제시하는 12개 중 이 둘만
    # 여기 없어서, 사용자가 고르면 지역 추출이 빈 리스트를 돌려주고
    # Google Places 보완이 myeongdong 기본값으로 떨어졌다.
    "bukchon":    (37.5826, 126.9836),
    "apgujeong":  (37.5271, 127.0286),
    # 외곽 자치구. 없을 때는 여기 속한 POI 33행이 전부 미분류로 떨어져
    # 어떤 지역을 요청해도 매칭되지 않았다. 좌표 폴백보다 주소의 자치구
    # 별칭이 먼저 잡히므로 배정이 결정적이다.
    # 영등포구는 통째로 넣지 않는다 — 여의도가 영등포구라서 alias 가 여의도를
    # 통째로 흡수한다. 문래만 별도 키로 둔다.
    "gangdong":   (37.5479, 127.1318),   # 올림픽공원을 잠실에서 뺏지 않도록 동쪽
    "gangseo":    (37.5657, 126.8265),   # 마곡
    "nowon":      (37.6350, 127.0780),
    "dobong":     (37.6560, 127.0470),
    "jungnang":   (37.5905, 127.0930),
    "gangbuk":    (37.6400, 127.0250),
    "seongbuk":   (37.5950, 127.0000),
    "eunpyeong":  (37.6020, 126.9290),
    "guro":       (37.4850, 126.8650),
    "gwanak":     (37.4780, 126.9520),
    "mullae":     (37.5206, 126.8868),
}

AREA_ALIASES: dict[str, list[str]] = {
    "hongdae":    ["hongdae", "hongik", "hongik univ", "hongik university", "홍대"],
    "hapjeong":   ["hapjeong", "합정"],
    "mangwon":    ["mangwon", "망원"],
    "yeonnam":    ["yeonnam", "연남"],
    "seongsu":    ["seongsu", "seongsu-dong", "성수", "성수동"],
    "wangsimni":  ["wangsimni", "왕십리"],
    "gangnam":    ["gangnam", "강남"],
    "sinsa":      ["sinsa", "신사"],
    "garosu-gil": ["garosu", "garosu-gil", "가로수길"],
    "jongno":     ["jongno", "종로"],
    "insadong":   ["insadong", "인사동"],
    "myeongdong": ["myeongdong", "명동"],
    "itaewon":    ["itaewon", "이태원"],
    "yongsan":    ["yongsan", "용산"],
    "sinchon":    ["sinchon", "신촌"],
    "dongdaemun": ["dongdaemun", "동대문"],
    "yeouido":    ["yeouido", "여의도"],
    "mapo":       ["mapo", "마포"],
    "jamsil":     ["jamsil", "잠실"],
    "dmc":        ["digital media city", "dmc", "상암", "디지털미디어시티"],
    "bukchon":    ["bukchon", "북촌"],
    "apgujeong":  ["apgujeong", "압구정"],
    "gangdong":   ["gangdong", "강동"],
    "gangseo":    ["gangseo", "magok", "강서", "마곡"],
    "nowon":      ["nowon", "노원"],
    "dobong":     ["dobong", "도봉"],
    "jungnang":   ["jungnang", "중랑"],
    "gangbuk":    ["gangbuk", "강북"],
    "seongbuk":   ["seongbuk", "성북"],
    "eunpyeong":  ["eunpyeong", "은평"],
    "guro":       ["guro", "구로"],
    "gwanak":     ["gwanak", "관악"],
    "mullae":     ["mullae", "문래"],
}

DEFAULT_CENTER: tuple[float, float] = (37.5665, 126.9780)

# Walkably adjacent neighborhoods — "this counts as the same trip area".
_ADJACENT_AREAS: dict[str, set[str]] = {
    # sinchon 은 Day Planner 의 "Hongdae · Sinchon · Mapo" 구역에 속한다.
    "hongdae": {"hongdae", "hapjeong", "mangwon", "yeonnam", "mapo", "sinchon"},
    "seongsu": {"seongsu", "wangsimni"},
    # bukchon / apgujeong 을 센터 목록에 넣으면 좌표 폴백의 최근접 중심이 바뀌어,
    # 그동안 jongno / insadong / gangnam 으로 잡히던 POI 34행이 새 키로 이동한다.
    # 아래 인접 규칙이 그 이동을 흡수한다 — 기존 요청의 매칭 결과는 그대로다.
    "gangnam": {"gangnam", "sinsa", "garosu-gil", "apgujeong"},
    "jongno": {"jongno", "insadong", "myeongdong", "bukchon"},
    "insadong": {"insadong", "bukchon"},
    # 좁게 잡는다. bukchon 에 jongno 를 넣으면 '북촌' 요청이 종로 전체(74코스)와
    # 사실상 같아져서 선택지로서 의미가 없어진다 — 실측 66 vs 23.
    "bukchon": {"bukchon", "insadong"},
    "apgujeong": {"apgujeong", "sinsa", "garosu-gil"},
    # 영등포 타임스퀘어가 mullae 로 재분류되므로, 여의도 요청이 놓치지 않게 묶는다.
    "yeouido": {"yeouido", "mullae"},
    "mullae": {"mullae", "yeouido"},
    # Itaewon sits inside Yongsan-gu, so the two satisfy each other's requests.
    "yongsan": {"yongsan", "itaewon"},
    "itaewon": {"itaewon", "yongsan"},
}

# Max distance (km) for the haversine fallback to claim a POI belongs to an area.
AREA_RADIUS_KM = 3.2

_AREA_LABELS: dict[str, str] = {
    "hongdae":    "Hongdae",
    "hapjeong":   "Hapjeong",
    "mangwon":    "Mangwon",
    "yeonnam":    "Yeonnam",
    "seongsu":    "Seongsu",
    "wangsimni":  "Wangsimni",
    "gangnam":    "Gangnam",
    "sinsa":      "Sinsa",
    "garosu-gil": "Garosu-gil",
    "jongno":     "Jongno",
    "insadong":   "Insadong",
    "myeongdong": "Myeongdong",
    "itaewon":    "Itaewon",
    "yongsan":    "Yongsan",
    "sinchon":    "Sinchon",
    "dongdaemun": "Dongdaemun",
    "yeouido":    "Yeouido",
    "mapo":       "Mapo",
    "jamsil":     "Jamsil",
    "dmc":        "Digital Media City",
    "bukchon":    "Bukchon",
    "apgujeong":  "Apgujeong",
    "gangdong":   "Gangdong",
    "gangseo":    "Gangseo",
    "nowon":      "Nowon",
    "dobong":     "Dobong",
    "jungnang":   "Jungnang",
    "gangbuk":    "Gangbuk",
    "seongbuk":   "Seongbuk",
    "eunpyeong":  "Eunpyeong",
    "guro":       "Guro",
    "gwanak":     "Gwanak",
    "mullae":     "Mullae",
}


# ---------------------------------------------------------------------------
# Precompiled alias patterns
# ---------------------------------------------------------------------------

def _alias_pattern(alias: str) -> re.Pattern[str]:
    """Word-boundary match for ASCII aliases; plain substring for non-ASCII (Korean)."""
    escaped = re.escape(alias)
    if alias.isascii():
        return re.compile(rf"\b{escaped}\b", re.IGNORECASE)
    return re.compile(escaped)


# Sorted by alias length descending so the longest match wins when scanning text.
# Fixes the "Mapo-gu Mangwon-dong" → mistakenly tagged mapo bug.
_ALIAS_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = sorted(
    [
        (area, alias, _alias_pattern(alias))
        for area, aliases in AREA_ALIASES.items()
        for alias in aliases
    ],
    key=lambda t: -len(t[1]),
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(d_lam / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def area_label(area: str) -> str:
    return _AREA_LABELS.get(area, area.title())


def infer_area(
    *,
    text: str | None = None,
    lat: Any = None,
    lng: Any = None,
) -> str | None:
    """Infer the canonical area key from address/name text, with a coords fallback.

    Longest-matching alias wins, so a string like "Mapo-gu Mangwon-dong" returns
    "mangwon" (the more specific match) instead of being absorbed by "mapo".
    """
    if text:
        text_lower = text.lower()
        for area, _alias, pattern in _ALIAS_PATTERNS:
            if pattern.search(text_lower):
                return area

    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (TypeError, ValueError):
        return None

    nearest_area: str | None = None
    nearest_dist = 9999.0
    for area, (clat, clng) in SEOUL_AREA_CENTERS.items():
        d = haversine_km(lat_f, lng_f, clat, clng)
        if d < nearest_dist:
            nearest_area = area
            nearest_dist = d

    return nearest_area if nearest_dist <= AREA_RADIUS_KM else None


def infer_area_from_fields(
    name: Any = "",
    address: Any = "",
    lat: Any = None,
    lng: Any = None,
) -> str | None:
    """Convenience wrapper used by planner.py — accepts name/address split fields."""
    text = f"{name or ''} {address or ''}"
    return infer_area(text=text, lat=lat, lng=lng)


def area_matches_requested(area: str | None, requested: str) -> bool:
    """True if `area` equals `requested` or is one of its walkably adjacent neighborhoods."""
    if not area:
        return False
    if area == requested:
        return True
    return area in _ADJACENT_AREAS.get(requested, {requested})
