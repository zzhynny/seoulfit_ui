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
}

DEFAULT_CENTER: tuple[float, float] = (37.5665, 126.9780)

# Walkably adjacent neighborhoods — "this counts as the same trip area".
_ADJACENT_AREAS: dict[str, set[str]] = {
    "hongdae": {"hongdae", "hapjeong", "mangwon", "yeonnam", "mapo"},
    "seongsu": {"seongsu", "wangsimni"},
    "gangnam": {"gangnam", "sinsa", "garosu-gil"},
    "jongno": {"jongno", "insadong", "myeongdong"},
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


def extract_requested_areas(
    location: str | None,
    purpose: str | None = None,
) -> list[str]:
    """Extract requested Seoul neighborhoods from user free-text.

    Areas are returned in the order they first appear in the text (location is
    scanned before purpose), so a "Gangnam and Hongdae" request maps Day 1 to
    Gangnam — matching what the user actually typed rather than an arbitrary
    alias-table order.
    """
    text = f"{location or ''} {purpose or ''}".lower()
    positions: dict[str, int] = {}
    for area, _alias, pattern in _ALIAS_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        pos = match.start()
        if area not in positions or pos < positions[area]:
            positions[area] = pos
    return sorted(positions, key=lambda area: positions[area])


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


def infer_poi_area(poi: dict[str, Any]) -> str | None:
    """Convenience wrapper used by rag.py — accepts a raw POI dict."""
    text = " ".join([
        str(poi.get("poi_name") or ""),
        str(poi.get("address_en") or ""),
        str(poi.get("address_ko") or ""),
    ])
    return infer_area(text=text, lat=poi.get("lat"), lng=poi.get("lng"))


def get_area_center(area_or_location: str) -> tuple[float, float]:
    """Resolve a free-text location to a (lat, lng) center, defaulting to Seoul city center."""
    text = re.sub(r"\s+", " ", str(area_or_location or "").strip().lower())
    inferred = infer_area(text=text)
    if inferred and inferred in SEOUL_AREA_CENTERS:
        return SEOUL_AREA_CENTERS[inferred]
    return DEFAULT_CENTER


def area_matches_requested(area: str | None, requested: str) -> bool:
    """True if `area` equals `requested` or is one of its walkably adjacent neighborhoods."""
    if not area:
        return False
    if area == requested:
        return True
    return area in _ADJACENT_AREAS.get(requested, {requested})
