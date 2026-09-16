"""ODsay 대중교통 길찾기 — itinerary leg 별 옵션 (지하철/버스/환승) 조회.

`fetch_odsay_options(start_lat, start_lng, end_lat, end_lng)` 가 핵심 진입점.

설계 원칙:
- 키 없거나 호출 실패 → 빈 리스트 반환 (graceful, 예외 안 던짐)
- timeout 짧게, 실패는 로그만 남기고 진행
- 결과는 좌표쌍별로 디스크에 캐시한다. 같은 구간은 일정을 새로 짜거나 다시
  검증할 때마다 또 조회되는데, ODsay 는 일일 한도가 있다. 오류(한도 초과,
  네트워크)는 경로에 대한 답이 아니므로 캐시하지 않는다.
- 실제로 ODsay 를 부를 때만 호출 간격(CALL_GAP_SECONDS)을 둔다.

환경변수:
- ODSAY_API_KEY        : 발급된 apiKey
- ODSAY_SERVICE_URI    : ODsay 콘솔에 등록한 Service URI (Referer 헤더로 사용)
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

# Secrets live in backend/.env (gitignored), not in source. ODsay stays
# dormant (is_enabled() == False) if the key is unset, same as the other keys.
ODSAY_API_KEY     = os.getenv("ODSAY_API_KEY", "")
ODSAY_SERVICE_URI = os.getenv("ODSAY_SERVICE_URI", "http://localhost:8888")

ODSAY_ENDPOINT = "https://api.odsay.com/v1/api/searchPubTransPathT"

# Hops shorter than this are shown as a walk; compute_transit_legs doesn't ask.
WALKABLE_KM = 0.7

# Lines and fares change rarely; a month keeps the cache from going stale.
CACHE_TTL = 30 * 24 * 3600
CACHE_PATH = Path(__file__).resolve().parent / "_odsay_cache.json"
CALL_GAP_SECONDS = 0.2

# ponytail: one JSON file rewritten on every new route. Fine for a few thousand
# hops on one worker; move to SQLite/Redis if it grows or runs multi-worker.
_CACHE: dict[str, list] = {}   # key -> [expires_at, options]
_lock = threading.Lock()


_PATH_TYPE_LABEL = {
    1: "🚇 Subway",
    2: "🚌 Bus",
    3: "🚇🚌 Subway+Bus",
}


def is_enabled() -> bool:
    """ODsay 호출 가능 여부 — 키 있어야 enabled."""
    return bool(ODSAY_API_KEY)


def _load_cache_from_disk() -> None:
    try:
        raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        # 파일 없음/손상 — 빈 캐시로 시작. 캐시가 기능을 막아선 안 된다.
        raw = {}
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
        print(f"[ODsay] cache write failed: {e}")


def _cache_key(start_lat: float, start_lng: float, end_lat: float, end_lng: float) -> str:
    # 4 decimals ≈ 11 m: the same stop always lands on the same key.
    return f"{start_lat:.4f},{start_lng:.4f}>{end_lat:.4f},{end_lng:.4f}"


def _fetch_all_paths(start_lat: float, start_lng: float,
                     end_lat: float, end_lng: float,
                     *, opt: int = 1, timeout: int = 5) -> list[dict[str, Any]] | None:
    """ODsay 호출 — 모든 후보 path 리스트. 호출 실패/오류 응답이면 None
    (경로가 없다는 답과 구분해야 오류를 캐시하지 않는다)."""
    if not ODSAY_API_KEY:
        return None

    encoded_key = quote(ODSAY_API_KEY, safe="")
    # lang=1 → English station/line names (default 0 = Korean). The structural
    # labels below are emitted in English to match.
    url = (
        f"{ODSAY_ENDPOINT}"
        f"?SX={start_lng}&SY={start_lat}"
        f"&EX={end_lng}&EY={end_lat}"
        f"&OPT={opt}&lang=1&apiKey={encoded_key}"
    )
    headers: dict[str, str] = {}
    if ODSAY_SERVICE_URI:
        headers["Referer"] = ODSAY_SERVICE_URI
        headers["Origin"]  = ODSAY_SERVICE_URI

    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[ODsay] request error: {e}")
        return None

    if "error" in data:
        print(f"[ODsay] error: {data['error']}")
        return None

    return (data.get("result") or {}).get("path") or []


def _best_per_path_type(paths: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """pathType 별로 totalTime 이 가장 짧은 path 만 골라 시간 오름차순."""
    best: dict[int, dict[str, Any]] = {}
    for p in paths:
        ptype = p.get("pathType")
        total = (p.get("info") or {}).get("totalTime")
        if ptype is None or total is None:
            continue
        cur = best.get(ptype)
        cur_total = (cur or {}).get("info", {}).get("totalTime")
        if cur is None or total < cur_total:
            best[ptype] = p

    return sorted(
        best.values(),
        key=lambda p: (p.get("info") or {}).get("totalTime", float("inf")),
    )


def _lane_name(lane: Any) -> str:
    if isinstance(lane, list) and lane:
        return " / ".join(l.get("name") or l.get("busNo") or "?" for l in lane)
    if isinstance(lane, dict):
        return lane.get("name") or lane.get("busNo") or "?"
    return "?"


def _format_subpath(subpath: list[dict[str, Any]] | None) -> list[str]:
    """subPath → 한 줄짜리 segment 문자열 리스트."""
    icons = {1: "🚇 Subway", 2: "🚌 Bus", 3: "🚶 Walk"}
    lines: list[str] = []
    for seg in subpath or []:
        ttype = seg.get("trafficType")
        sec_time = seg.get("sectionTime")
        dist = seg.get("distance")
        icon = icons.get(ttype, "·")

        if ttype == 3:
            lines.append(f"{icon} {sec_time} min ({dist}m)")
            continue

        lane = _lane_name(seg.get("lane"))
        start = seg.get("startName") or "?"
        end   = seg.get("endName")   or "?"
        n_stop = seg.get("stationCount")
        extra = f", {n_stop} stops" if n_stop is not None else ""
        lines.append(f"{icon} {lane}  {start} → {end}  ({sec_time} min{extra})")
    return lines


def fetch_odsay_options(start_lat: float, start_lng: float,
                        end_lat: float, end_lng: float) -> list[dict[str, Any]]:
    """한 leg 의 (지하철/버스/환승) 옵션 리스트, 시간 오름차순.

    각 옵션:
      {
        "type": 1|2|3,
        "type_label": "🚇 지하철",
        "total_minutes": int,
        "fare_won": int,
        "walk_meters": int,
        "subway_rides": int,
        "bus_rides": int,
        "transfers": int,          # = subway_rides + bus_rides - 1 (>=0)
        "segments": list[str],     # 구간별 사람 읽기 좋은 라인
      }
    """
    key = _cache_key(start_lat, start_lng, end_lat, end_lng)
    with _lock:
        entry = _CACHE.get(key)
    if entry and time.time() < entry[0]:
        return [dict(o) for o in entry[1]]

    paths = _fetch_all_paths(start_lat, start_lng, end_lat, end_lng)
    time.sleep(CALL_GAP_SECONDS)  # rate-limit 안전 — 실제 호출일 때만
    if paths is None:
        return []

    options: list[dict[str, Any]] = []
    for path in _best_per_path_type(paths):
        info = path.get("info") or {}
        ptype = path.get("pathType")
        subway_n = info.get("subwayTransitCount") or 0
        bus_n    = info.get("busTransitCount") or 0
        total_rides = subway_n + bus_n
        transfers = max(0, total_rides - 1)

        options.append({
            "type":          ptype,
            "type_label":    _PATH_TYPE_LABEL.get(ptype, f"Other({ptype})"),
            "total_minutes": info.get("totalTime"),
            "fare_won":      info.get("payment"),
            "walk_meters":   info.get("totalWalk"),
            "subway_rides":  subway_n,
            "bus_rides":     bus_n,
            "transfers":     transfers,
            "segments":      _format_subpath(path.get("subPath")),
        })

    with _lock:
        _CACHE[key] = [time.time() + CACHE_TTL, options]
    _flush_cache_to_disk()
    return [dict(o) for o in options]


_load_cache_from_disk()
