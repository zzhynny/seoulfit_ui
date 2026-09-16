"""live_help.py — 여행 중 도우미 라우터 (주변 추천 · 응급실).

api.py 에 include_router 로 마운트한다.
여권분실은 앱에 번들한 assets/data/embassies.json 을 쓰므로 여기 없다 —
여권을 잃은 사람은 데이터로밍이 끊겨 있을 수 있다.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
import xml.etree.ElementTree as ET

import httpx
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

import stamp
import tourapi
from stamp import _HANGUL_RE, _romanize

router = APIRouter(tags=["live-help"])

_PLACES_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"

# 반경 1000m 고정. 더 넓히면 도보 20분 거리를 '내 위치 기반 추천'으로 내놓게 된다.
# 5개를 못 채우면 채워지는 만큼만 준다.
_RADIUS = 1000


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 사이 대권거리(미터)."""
    r = 6371000.0
    rad = math.radians
    a = (
        math.sin(rad(lat2 - lat1) / 2) ** 2
        + math.cos(rad(lat1)) * math.cos(rad(lat2)) * math.sin(rad(lng2 - lng1) / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def filter_places(results: list[dict], lat: float, lng: float) -> dict[str, dict]:
    """Places 결과에 거리를 붙여 place_id 로 키잉해 돌려준다.

    리뷰 수로 거르지 않는다 — 순수 거리순 추천. 구글은 리뷰가 하나도 없는 업소에서
    user_ratings_total 과 rating 을 아예 빼고 내려주므로 rating 은 None, reviews 는
    0 으로 남는다. 좌표 없는 행만 버린다.
    """
    out: dict[str, dict] = {}
    for p in results:
        loc = (p.get("geometry") or {}).get("location") or {}
        if "lat" not in loc or "lng" not in loc:
            continue
        pid = p.get("place_id") or p.get("name", "")
        # 사진은 photo_reference 만 넘긴다. 실제 이미지 URL 은 key 를 쿼리에
        # 달아야 해서 앱에 그대로 주면 Places 키가 통째로 노출된다.
        # 아래 /place-photo 가 서버에서 대신 받아 바이트만 돌려준다.
        photos = p.get("photos") or []
        out[pid] = {
            "name": p.get("name", ""),
            "photo_ref": (photos[0].get("photo_reference", "") if photos else ""),
            "address": p.get("vicinity", ""),
            "lat": loc["lat"],
            "lng": loc["lng"],
            "distance_m": round(haversine_m(lat, lng, loc["lat"], loc["lng"])),
            "rating": p.get("rating"),
            "reviews": p.get("user_ratings_total", 0),
            "open_now": (p.get("opening_hours") or {}).get("open_now"),
            "place_id": p.get("place_id", ""),
        }
    return out


class NearbyRequest(BaseModel):
    lat: float
    lng: float
    type: str = "cafe"
    want: int = 5


@router.post("/nearby")
def nearby(req: NearbyRequest):
    """현재 위치 도보권의 카페/음식점을 거리순으로 돌려준다."""
    key = os.getenv("GOOGLE_PLACES_API_KEY", "")
    if not key:
        raise HTTPException(status_code=500, detail="GOOGLE_PLACES_API_KEY is not set")

    # rankby=distance 는 radius 와 함께 못 쓴다. 반경을 고정하고 거리 정렬은
    # 하버사인으로 직접 한다.
    try:
        data = httpx.get(
            _PLACES_URL,
            params={
                "location": f"{req.lat},{req.lng}",
                "radius": _RADIUS,
                "type": req.type,
                "key": key,
                "language": "en",
            },
            timeout=15,
        ).json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Places request failed: {e}")

    status = data.get("status")
    if status not in ("OK", "ZERO_RESULTS"):
        raise HTTPException(
            status_code=502,
            detail=f"Places error {status}: {data.get('error_message', '')}",
        )

    found = filter_places(data.get("results", []), req.lat, req.lng)
    places = sorted(found.values(), key=lambda x: x["distance_m"])[: req.want]
    to_english(places, stamp._translate)
    return {"radius_used": _RADIUS, "places": places}


# language=en 이어도 구글에 영문 표기가 없는 업소("프랭키스")와 주소 일부("2층",
# "서교동")는 한글로 온다. 번역에 성공한 것만 기억한다 — 실패는 이번 응답만
# 로마자로 때우고 다음 요청에서 다시 번역한다.
# ponytail: 프로세스 메모리, 무제한. 서울 업소명 규모라 문제없다; 커지면 LRU.
_EN_CACHE: dict[str, str] = {}


def to_english(places: list[dict], translate) -> None:
    """places 의 name/address 에 남은 한글을 제자리에서 영어로 바꾼다 (Gemini 1회)."""
    fields = ("name", "address")
    pending = sorted({
        p[k] for p in places for k in fields
        if _HANGUL_RE.search(p[k]) and p[k] not in _EN_CACHE
    })
    got: dict = {}
    if pending:
        try:
            got = translate(pending) or {}
        except Exception as e:
            print(f"[nearby] translation failed, romanizing: {e}")
    for p in places:
        for k in fields:
            ko = p[k]
            if not _HANGUL_RE.search(ko):
                continue
            en = _EN_CACHE.get(ko) or str(got.get(ko) or "").strip()
            if en and not _HANGUL_RE.search(en):
                _EN_CACHE[ko] = en
                p[k] = en
            else:
                p[k] = _romanize(ko)


# ---------------------------------------------------------------------------
# 사진 프록시 — Google Place Photos.
#
# 사진 URL 은 https://maps.googleapis.com/maps/api/place/photo?...&key=<KEY> 라
# 키를 쿼리에 달아야만 열린다. 그 URL 을 앱에 내려보내면 트래픽만 봐도 키가
# 그대로 보인다. 그래서 앱에는 photo_ref 만 주고, 이미지는 여기서 대신 받아
# 바이트로 돌려준다. 키는 서버 밖으로 나가지 않는다.
# ---------------------------------------------------------------------------

_PHOTO_URL = "https://maps.googleapis.com/maps/api/place/photo"

# 앱 카드가 56px, 시트 헤더가 최대 400px 다. 그 위는 받아봐야 버리는 바이트고
# Places 사진 호출은 건당 과금이라 상한을 둔다. 200px 13KB / 400px 42KB.
_PHOTO_MIN_W, _PHOTO_MAX_W = 100, 800


@router.get("/place-photo")
def place_photo(ref: str, w: int = 400):
    """photo_reference 하나를 이미지 바이트로 바꿔 돌려준다."""
    key = os.getenv("GOOGLE_PLACES_API_KEY", "")
    if not key:
        raise HTTPException(status_code=503, detail="GOOGLE_PLACES_API_KEY is not set")
    # ref 는 구글이 준 불투명 문자열이다. 길이만 막아 두면 충분하다.
    if not ref or len(ref) > 1000:
        raise HTTPException(status_code=422, detail="invalid photo reference")
    width = max(_PHOTO_MIN_W, min(int(w), _PHOTO_MAX_W))
    try:
        r = httpx.get(_PHOTO_URL,
                      params={"maxwidth": width, "photo_reference": ref, "key": key},
                      timeout=20, follow_redirects=True)
    except httpx.HTTPError:
        # 예외 문자열에 요청 URL(=키)이 섞여 나오므로 그대로 올리지 않는다.
        raise HTTPException(status_code=502, detail="photo fetch failed")
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
        raise HTTPException(status_code=404, detail="photo not available")
    return Response(
        content=r.content,
        media_type=r.headers.get("content-type", "image/jpeg"),
        # 같은 사진을 스크롤할 때마다 다시 사 오지 않도록 하루 캐시한다.
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ---------------------------------------------------------------------------
# 응급실 — E-Gen (국립중앙의료원 전국 응급의료기관 정보 조회 서비스)
#
# 9개 오퍼레이션 중 2개만 쓴다:
#   getEgytLcinfoInqire                 좌표·거리를 주는 유일한 엔드포인트
#   getEmrrmRltmUsefulSckbdInfoInqire   dutyTel3(응급실 직통)·hvec(가용병상)의 유일한 출처
# hpid 로 조인하면 응급실을 운영하지 않는 일반 병원은 자동으로 떨어진다.
# ---------------------------------------------------------------------------

_EGEN_BASE = "https://apis.data.go.kr/B552657/ErmctInfoInqireService"
_BEDS_TTL = 60  # 서울 전체가 한 응답이라 60초 캐시하면 일일 1000콜 제한에 여유가 생긴다

_beds_cache: tuple[float, dict[str, dict]] | None = None
_beds_lock = threading.Lock()

# 위치 조회(getEgytLcinfoInqire)는 병상 조회와 달리 좌표마다 응답이 달라서 한
# 덩어리로 캐시할 수 없다. 대신 좌표를 반올림해 격자로 접는다 — 요청 1건이
# 곧 호출 1건이면 일 1,000회 한도가 8분 만에 사라지고, 그러면 응급실 화면이
# 그날 내내 죽는다. 되돌릴 방법도 없다.
_near_cache: dict[tuple, tuple[float, list]] = {}


def _egen(op: str, **params) -> list:
    key = os.getenv("EGEN_API_KEY", "")
    if not key:
        raise HTTPException(status_code=500, detail="EGEN_API_KEY is not set")
    try:
        r = httpx.get(
            f"{_EGEN_BASE}/{op}",
            params={"serviceKey": key, "pageNo": 1, "numOfRows": 1000, **params},
            timeout=25,
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"E-Gen {op} request failed: {e}")
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError:
        raise HTTPException(status_code=502, detail=f"E-Gen {op} returned non-XML")
    code = root.findtext(".//resultCode")
    if code not in (None, "00"):
        raise HTTPException(
            status_code=502,
            detail=f"E-Gen {op} returned {code}: {root.findtext('.//resultMsg')}",
        )
    items = root.findall(".//item")
    if code is None and not items:
        # data.go.kr 의 에러 봉투(quota 초과, Encoding 키를 잘못 넣었을 때 등)는
        # resultCode 자체가 없다 — None 을 성공으로 오인하면 빈 리스트가 그대로
        # HTTP 200 으로 나가 응급 화면이 조용히 빈 화면이 된다. resultCode 도
        # item 도 없는 응답만 에러로 취급한다 — resultCode == "00" 인데 item 이
        # 0개인 건 진짜 빈 결과이므로 (_seoul_beds, 위치조회 둘 다 여기 해당) 건드리지 않는다.
        header = root.find(".//cmmMsgHeader")
        reason = None
        if header is not None:
            reason = (
                header.findtext("returnAuthMsg")
                or header.findtext("errMsg")
                or "".join(header.itertext()).strip()
                or None
            )
        raise HTTPException(
            status_code=502,
            detail=f"E-Gen {op} returned an error envelope"
            + (f": {reason}" if reason else " with no resultCode or items"),
        )
    return items


def parse_beds(items: list) -> dict[str, dict]:
    """실시간 가용병상 item 들을 hpid 로 키잉한다."""
    beds: dict[str, dict] = {}
    for it in items:
        hpid = (it.findtext("hpid") or "").strip()
        if not hpid:
            continue
        raw = (it.findtext("hvec") or "0").strip()
        try:
            hvec = int(raw)
        except ValueError:
            hvec = 0
        beds[hpid] = {
            "er_phone": (it.findtext("dutyTel3") or "").strip(),
            "hvec": hvec,
            "updated_at": (it.findtext("hvidate") or "").strip(),
        }
    return beds


def _seoul_beds() -> dict[str, dict]:
    global _beds_cache
    now = time.time()
    if _beds_cache and now - _beds_cache[0] < _BEDS_TTL:
        return _beds_cache[1]
    with _beds_lock:
        # 락 대기 중 다른 스레드가 이미 갱신했을 수 있으니 다시 확인한다 —
        # 그러지 않으면 TTL 만료 시점에 동시 요청이 각각 E-Gen 을 또 부른다.
        now = time.time()
        if _beds_cache and now - _beds_cache[0] < _BEDS_TTL:
            return _beds_cache[1]
        beds = parse_beds(_egen("getEmrrmRltmUsefulSckbdInfoInqire", STAGE1="서울특별시"))
        _beds_cache = (now, beds)
        return beds


def join_er(near_items: list, beds: dict[str, dict], want: int) -> list[dict]:
    """위치조회 결과에 실시간 병상을 붙이고 거리순으로 자른다.

    실시간 목록에 없는 기관은 응급실 미운영 일반 병원이므로 여기서 떨어진다 —
    별도 필터링 로직이 필요 없다.
    """
    rows: list[dict] = []
    for it in near_items:
        hpid = (it.findtext("hpid") or "").strip()
        b = beds.get(hpid)
        if not b:
            continue
        rows.append({
            "name": (it.findtext("dutyName") or "").strip(),
            "address": (it.findtext("dutyAddr") or "").strip(),
            "lat": float(it.findtext("latitude") or 0),
            "lng": float(it.findtext("longitude") or 0),
            "distance_km": float(it.findtext("distance") or 0),
            "er_phone": b["er_phone"],
            "beds": b["hvec"],
            # hvec 는 정원 초과를 음수로 쓴다. 0 이하는 전부 '만원'.
            "beds_state": "available" if b["hvec"] > 0 else "full",
            "updated_at": b["updated_at"],
        })
    rows.sort(key=lambda x: x["distance_km"])
    return rows[:want]


class ErRequest(BaseModel):
    lat: float
    lng: float
    want: int = 5


@router.post("/emergency-rooms")
def emergency_rooms(req: ErRequest):
    """현재 위치에서 가까운, 실제로 운영 중인 응급실을 병상 상황과 함께 돌려준다."""
    key = (round(req.lat, 3), round(req.lng, 3))   # 약 110m 격자
    hit = _near_cache.get(key)
    if not (hit and time.time() - hit[0] < _BEDS_TTL):
        near = _egen("getEgytLcinfoInqire", WGS84_LON=req.lng, WGS84_LAT=req.lat)
        if len(_near_cache) > 500:
            _near_cache.clear()
        _near_cache[key] = hit = (time.time(), near)

    rows = join_er(hit[1], _seoul_beds(), req.want)
    return {"updated_at": rows[0]["updated_at"] if rows else "", "hospitals": rows}


# ---------------------------------------------------------------------------
# 주변 관광 POI — 한국관광공사 TourAPI(EngService2) locationBasedList2 실시간 조회
#
# 목록은 매번 공사 API 에서 받는다. 사전 수집분(431건)은 서울 전역을 미리 훑은
# 스냅샷이라 그 이후에 등록된 곳이 빠지고, locationBasedList2 는 거리(dist)까지
# 계산해서 준다.
#
# 다만 목록 응답에는 소개글·영업시간이 없다. POI 당 detailCommon2 를 부르면
# 20건짜리 화면 한 장이 21회 호출이 되어 일 1,000회 쿼터를 못 버틴다. 그래서
# 상세는 contentid 로 사전 수집분에서 채운다 — 목록은 최신, 상세는 스냅샷.
#
# dataset/tour_poi.json 은 그래서 남는다. 상세 보강용이자, 공사 API 가 죽었을
# 때의 폴백이다. 심사 중에 쿼터가 끊겨도 화면은 서야 한다.
# ---------------------------------------------------------------------------

# /nearby-poi · /nearby-shopping 공통 반경. 도보권 밖을 '주변' 이라고 부르지
# 않는다. 늘리려면 여기 한 곳만 고치면 된다.
_RADIUS_M = 1000

_POI_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataset", "tour_poi.json")

with open(_POI_PATH, encoding="utf-8") as _f:
    _TOUR_POIS: list[dict] = json.load(_f)
print(f"[live-help] tour_poi.json: loaded {len(_TOUR_POIS)} POIs")


# ---------------------------------------------------------------------------
# 주변 쇼핑 POI — 서울관광재단 Visit Seoul API 사전 수집분
# (dataset/shopping_poi.json, scripts/build_shopping_poi.py 산출물).
#
# 서울관광재단이 골라 쓴 '가볼 만한 쇼핑 장소' 310건. 전통시장·백화점·면세점
# 같은 하위 분류가 원본에 있어서 /nearby-poi 처럼 카테고리 칩을 받는다.
# ---------------------------------------------------------------------------

_SHOPPING_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "dataset", "shopping_poi.json"
)

with open(_SHOPPING_PATH, encoding="utf-8") as _f:
    _SHOPPING_POIS: list[dict] = json.load(_f)
print(f"[live-help] shopping_poi.json: loaded {len(_SHOPPING_POIS)} POIs")


class NearbyShoppingRequest(BaseModel):
    lat: float
    lng: float

    # None 이면 전체(칩의 'All'). SP/TM/MO/DS/DF/SW 중 하나.
    category: str | None = None

    want: int = 20


@router.post("/nearby-shopping")
def nearby_shopping(req: NearbyShoppingRequest):
    """현재 위치에서 가까운 쇼핑 POI 를 거리순으로 돌려준다.

    /nearby-poi 와 같이 _RADIUS_M 안쪽만 준다. 걸어갈 수 있는 곳이 아니면
    'On trip 중 지금 주변' 이라는 화면의 전제가 무너진다.
    """
    rows = _SHOPPING_POIS
    if req.category:
        rows = [p for p in rows if p["category"] == req.category]
    ranked = sorted(
        (
            d
            for d in (
                dict(p, distance_m=round(haversine_m(req.lat, req.lng, p["lat"], p["lng"])))
                for p in rows
            )
            if d["distance_m"] <= _RADIUS_M
        ),
        key=lambda p: p["distance_m"],
    )
    return {"pois": ranked[: req.want]}


class NearbyPoiRequest(BaseModel):
    lat: float
    lng: float

    # None 이면 전체(칩의 'All'). 그 외에는 lclsSystm1 코드 하나 — 앱의 칩이
    # 단일선택이라 리스트가 아니라 스칼라다.
    category: str | None = None

    want: int = 20


# 좌표 캐시 키는 소수 3자리 — 약 110m. 걸어가며 화면을 다시 열 때마다 공사
# API 를 치지 않도록 접고, 그보다 멀리 가면 새로 받는다.
#
# 항목 하나가 최대 300건의 POI 를 상세까지 들고 있어 50~150KB 다. 좌표를
# 0.001 씩 밀며 호출하면 캐시가 전부 miss 인 채로 무한히 자라 프로세스를
# OOM 으로 보낼 수 있어서 개수를 막는다.
_POI_CACHE_MAX = 500
_POI_CACHE: dict[tuple, tuple[float, list]] = {}
_POI_TTL = 600  # seconds

# contentid → 사전 수집분 한 줄. 목록 응답에 없는 상세를 여기서 채운다.
_POI_BY_ID: dict[str, dict] = {p["id"]: p for p in _TOUR_POIS}

# 목록 응답이 주는 것 말고, 상세 시트가 쓰는 필드들.
_DETAIL_FIELDS = ("overview", "hours", "closed", "fee", "parking", "tel", "homepage")


def _live_pois(lat: float, lng: float) -> list[dict]:
    """locationBasedList2 로 반경 안의 POI 를 받아 앱 스키마로 바꾼다."""
    rows, _ = tourapi.items(
        "locationBasedList2",
        mapX=lng,          # 공사 API 는 X 가 경도다. 뒤집으면 조용히 엉뚱한 곳이 나온다.
        mapY=lat,
        radius=_RADIUS_M,
        arrange="S",       # 거리순
    )
    out = []
    for r in rows:
        cid = r.get("contentid", "")
        cached = _POI_BY_ID.get(cid, {})
        out.append({
            "id": cid,
            "title": r.get("title", ""),
            "category": r.get("lclsSystm1", ""),
            "address": r.get("addr1", ""),
            "lat": float(r.get("mapy") or 0),
            "lng": float(r.get("mapx") or 0),
            "distance_m": round(float(r.get("dist") or 0)),
            # firstimage 가 비면 스냅샷에 남은 것이라도 쓴다.
            "image": r.get("firstimage") or cached.get("image", ""),
            # 결측이면 빈 문자열. 앱이 빈 줄을 통째로 숨긴다.
            **{f: cached.get(f, "") for f in _DETAIL_FIELDS},
        })
    return out


def _snapshot_pois(lat: float, lng: float) -> list[dict]:
    """폴백 — 사전 수집분 431건에서 직접 거리를 재 정렬한다."""
    return sorted(
        (
            d
            for d in (
                dict(p, distance_m=round(haversine_m(lat, lng, p["lat"], p["lng"])))
                for p in _TOUR_POIS
            )
            if d["distance_m"] <= _RADIUS_M
        ),
        key=lambda p: p["distance_m"],
    )


@router.post("/nearby-poi")
def nearby_poi(req: NearbyPoiRequest):
    """현재 위치에서 가까운 관광 POI 를 거리순으로 돌려준다.

    _RADIUS_M 안쪽만 준다. POI 밀도가 지역마다 10배 넘게 차이나서(경복궁 1km
    62건 vs 여의도 한 자릿수) 한산한 지역에서는 빈 리스트가 나온다 — 걸어서 못
    가는 6km 짜리를 '주변' 이라고 내미는 쪽이 더 나쁘다. 앱은 빈 상태를 그린다.

    상세 정보까지 한 응답에 담는다. 카드를 열 때 2차 호출이 없고, 20건이면
    25KB 남짓이다.
    """
    key = (round(req.lat, 3), round(req.lng, 3))
    hit = _POI_CACHE.get(key)
    if not (hit and (time.time() - hit[0]) < _POI_TTL):
        try:
            rows = _live_pois(req.lat, req.lng)
        except Exception as e:
            # 쿼터 소진·키 오류·공사 API 장애. 스냅샷으로 화면은 세운다.
            print(f"[live-help] locationBasedList2 failed, using snapshot: "
                  f"{type(e).__name__}: {tourapi.redact(e)}")
            rows = _snapshot_pois(req.lat, req.lng)
        if len(_POI_CACHE) > _POI_CACHE_MAX:
            _POI_CACHE.clear()
        _POI_CACHE[key] = hit = (time.time(), rows)

    rows = hit[1]
    if req.category:
        rows = [p for p in rows if p["category"] == req.category]
    return {"pois": rows[: req.want]}
