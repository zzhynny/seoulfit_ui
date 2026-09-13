"""
api.py — Seoul Travel Buddy FastAPI backend.

Local dev:
    uvicorn api:app --reload --port 8000

Production (Render binds $PORT):
    python -m uvicorn api:app --host 0.0.0.0 --port $PORT
"""

import json
import os
import sys
from urllib.parse import quote

# On Windows, a Python process's stdout/stderr default to the OS locale codec
# (cp949 on a Korean-locale machine) unless PYTHONUTF8=1 is set before the
# interpreter starts -- easy to forget when launching uvicorn directly. cp949
# can't encode most non-Korean/non-ASCII punctuation (e.g. an en dash "–"),
# so any print() of a course/POI name containing one crashes with
# UnicodeEncodeError. UTF-8 can encode any Unicode string, so reconfiguring
# here removes the whole class of failure without hunting down every print()
# call site. Must run before any other import: several modules
# (e.g. the lens/live-help data loaders) print on import.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure") and (_stream.encoding or "").lower() != "utf-8":
        _stream.reconfigure(encoding="utf-8")

# All backend modules (graph.py, state.py, planner.py, …) now live flat in
# this same directory, so add it to sys.path to stay import-safe regardless of
# where uvicorn is launched from.
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)

# ── Compatibility patch ────────────────────────────────────────────────────────
# langchain 0.3+ removed the `langchain.debug` / `langchain.verbose` module
# attributes; the supported way to set them is langchain.globals. Poking the
# module attributes directly (hasattr/setattr) now emits a deprecation warning,
# so use the official setters instead.
from langchain.globals import set_debug, set_verbose
set_debug(False)
set_verbose(False)
# ──────────────────────────────────────────────────────────────────────────────

from dotenv import load_dotenv
from pathlib import Path
import threading as _threading
import time as _time

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse as _JSONResponse
from typing import Optional
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage

# In dev we load .env from disk; in prod (Render) env vars are injected
# directly into the process so load_dotenv is a no-op.
load_dotenv(os.path.join(_here, ".env"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is not set. "
        "In dev, add it to flutter/backend/.env. "
        "In prod, set it as an environment variable on the host."
    )

# langchain-google-genai (used by rag.py for embeddings) checks
# GOOGLE_API_KEY first and only falls back to GEMINI_API_KEY in newer
# versions. To stay robust across versions, mirror GEMINI_API_KEY into
# GOOGLE_API_KEY when the latter isn't explicitly set.
if not os.getenv("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = GEMINI_API_KEY

from graph import build_graph, clear_thread, FIELD_QUESTIONS
from lens import router as lens_router
from live_help import router as live_help_router
from guardrail_gate import is_blocked
from checkin_store import save_checkin
from stamp import generate_stamp, request_stamp, stamp_status, valid_trip_id

# Canned reply when the input gatekeeper blocks an off-topic / injection /
# jailbreak message. Kept friendly and on-brand with collect_node's greeting.
_BLOCKED_REPLY = (
    "I can only help with planning your Seoul trip \U0001f425 "
    "Tell me your travel dates, interests, or which area you'd like to explore!"
)

_graph = build_graph(GEMINI_API_KEY)

# 코스 원본 페이지(visitseoul / visitkorea)에서 한 번 긁어둔 정거장 사진, 그리고
# 그 페이지에도 없어서 사람이 직접 찍어 넣은 사진(dataset/missing_poi_images/).
# {poi_name: image_url}. /poi-image 가 SerpApi 를 치기 전에 여기부터 뒤진다 —
# 아래 엔드포인트 주석 참고. 만드는 건 scripts/scrape_poi_images.py 와
# scripts/backfill_missing_images.py.
# 값이 "local:파일명" 이면 로컬 파일이다 — 아래 StaticFiles 마운트로 서빙하고,
# poi_image() 가 요청 시점의 호스트를 붙여 완전한 URL로 바꿔 돌려준다(로컬 개발/
# Render 배포 어느 쪽이든 호스트를 하드코딩하지 않아도 되게). 그 외 값은 이미
# 완전한 https:// URL이라 그대로 돌려준다.
# 파일이 없어도 동작한다. 그냥 전부 SerpApi 로 간다.
try:
    _POI_IMAGES = json.loads(
        (Path(_here) / "dataset" / "poi_images.json").read_text(encoding="utf-8")
    )
except FileNotFoundError:
    _POI_IMAGES = {}
    print("[poi-image] dataset/poi_images.json 없음 — 전량 SerpApi 로 처리")

_LOCAL_POI_IMAGES_DIR = Path(_here) / "dataset" / "missing_poi_images"

app = FastAPI(title="Seoul Travel Buddy API")

if _LOCAL_POI_IMAGES_DIR.is_dir():
    app.mount(
        "/static/poi_images",
        StaticFiles(directory=str(_LOCAL_POI_IMAGES_DIR)),
        name="poi_images_static",
    )

# Journey stamps (stamp.py) are written here after each checkin; create it up
# front so the mount succeeds even before the first stamp is generated.
_STAMPS_DIR = Path(_here) / "stamps"
_STAMPS_DIR.mkdir(exist_ok=True)
app.mount("/static/stamps", StaticFiles(directory=str(_STAMPS_DIR)), name="stamps_static")


# ---------------------------------------------------------------------------
# Rate limit — every endpoint below is unauthenticated, and the expensive ones
# spend real money per call (Gemini on /chat, /poi-*, /analyze-landmark; two
# Gemini calls plus a SerpApi search on /poi-image; Google Places on /nearby;
# E-Gen, which caps us at 1000 calls/day, on /emergency-rooms). Without a limit
# one loop from one browser tab drains the quota for everyone.
#
# Registered BEFORE CORSMiddleware so CORS ends up outermost and a 429 still
# carries Access-Control-Allow-Origin — otherwise the browser reports an opaque
# CORS failure instead of the real status.
#
# ponytail: in-process fixed window, so the budget is per worker and resets on
# deploy. Move to Redis if this ever runs more than one instance.
# ---------------------------------------------------------------------------
_METERED_PATHS = {
    "/chat", "/poi-summary", "/poi-detail", "/poi-image",
    "/analyze-landmark", "/nearby", "/nearby-poi", "/nearby-shopping",
    "/emergency-rooms", "/place-photo",
    # /reset really deletes a session's state now (it used to be a no-op),
    # and /day-plan writes day_specs -- both write to state protected only
    # by an unguessable thread id (there's no login), so an unmetered loop
    # can churn either one indefinitely.
    "/reset", "/day-plan",
    # Can fire a paid OpenAI images.edit (stamp.py) when generate_stamp is set —
    # an unmetered loop would spend real money per hit, not just DB I/O.
    "/trip/checkin",
}
# 120/min, not 30: user_selection_screen renders one card per candidate stop
# and each fires fetchPoiDetail on build, and final_itinerary_map_screen
# fires summary + image per stop, so a legitimate screen load is already a
# 20-40 call burst. An abuse loop does thousands, so the gap is wide enough.
_RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MIN", "120"))
_RATE_WINDOW = 60.0
_rate_hits: dict[str, tuple[float, int]] = {}
_rate_lock = _threading.Lock()


def _client_ip(request) -> str:
    # Render terminates TLS at its proxy, so request.client.host is the proxy.
    # Trust the first X-Forwarded-For hop only because we know we sit behind
    # exactly one. Direct-to-internet deploys must drop this branch: the header
    # is attacker-controlled and would make the limit trivially bypassable.
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def _rate_limit(request, call_next):
    if request.url.path not in _METERED_PATHS:
        return await call_next(request)
    now = _time.monotonic()
    ip = _client_ip(request)
    with _rate_lock:
        start, count = _rate_hits.get(ip, (now, 0))
        if now - start >= _RATE_WINDOW:
            start, count = now, 0
        count += 1
        _rate_hits[ip] = (start, count)
        if len(_rate_hits) > 10_000:  # bound the dict; drop stale windows
            _rate_hits.clear()
    if count > _RATE_LIMIT:
        retry_after = max(1, int(_RATE_WINDOW - (now - start)))
        return _JSONResponse(
            {"detail": "Rate limit exceeded. Try again shortly."},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
    return await call_next(request)

# CORS — in dev (FRONTEND_ORIGIN unset) we allow any origin so `flutter
# run -d chrome` and similar tools work without ceremony. In prod, set
# FRONTEND_ORIGIN to a comma-separated list of the deployed frontend URLs.
#
# Render's `fromService.property: host` returns a bare hostname like
# "seoul-buddy-web.onrender.com" with no scheme. Browsers send the full
# `https://...` form in the Origin header, so we have to normalize each
# entry to a full origin or CORS will silently reject every request.
def _normalize_origin(o: str) -> str:
    o = o.strip()
    if not o or o == "*":
        return o
    if "://" not in o:
        # Render production hosts are HTTPS-only; assume https for bare hosts.
        o = f"https://{o}"
    # Trim any accidental trailing slash so the comparison is exact.
    return o.rstrip("/")


_frontend_origin = os.getenv("FRONTEND_ORIGIN", "").strip()
_cors_origins = [
    _normalize_origin(o) for o in _frontend_origin.split(",") if o.strip()
]
# With FRONTEND_ORIGIN unset we used to fall back to "*", which let any page on
# the internet drive this API from a visitor's browser — and every /chat,
# /poi-*, /analyze-landmark call spends Gemini / SerpApi / Places quota. Fall
# back to localhost-any-port instead so `flutter run -d chrome` still works and
# a missing prod env var fails closed. Native iOS/Android send no Origin header
# and are unaffected by CORS either way.
_cors_kwargs = (
    {"allow_origins": _cors_origins}
    if _cors_origins
    else {"allow_origin_regex": r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"}
)
app.add_middleware(
    CORSMiddleware,
    allow_methods=["*"],
    allow_headers=["*"],
    **_cors_kwargs,
)

# Lens (camera → landmark) endpoints
app.include_router(lens_router)

# 여행 중 도우미 (주변 추천 · 응급실) endpoints
app.include_router(live_help_router)


# ---------------------------------------------------------------------------
# Health probe — Render / k8s style "is the process alive?" endpoint.
# ---------------------------------------------------------------------------
@app.get("/healthz")
def healthz():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

# Session ids are the only thing standing between one visitor's itinerary and
# another's (there is no login). The Flutter client generates
# "trip-<base36 ts>-<8 chars from Random.secure()>", so require an id long
# enough that guessing another session is impractical, and never fall back to a
# shared default — "travel-session-1" put every client that omitted the field
# on one conversation that anyone could read via /state or wipe via /reset.
# str(e) went straight to an unauthenticated client. The text is whatever
# Gemini / SerpApi / langchain raised — module paths, request shapes,
# sometimes a full request URL. Log it, do not serve it.
_INTERNAL_ERROR = "Internal error"

_THREAD_ID_MIN = 16
_THREAD_ID_MAX = 128


def _require_thread_id(thread_id: str) -> str:
    if not (_THREAD_ID_MIN <= len(thread_id) <= _THREAD_ID_MAX):
        raise HTTPException(
            status_code=422,
            detail=f"thread_id must be {_THREAD_ID_MIN}-{_THREAD_ID_MAX} characters",
        )
    return thread_id


class ChatRequest(BaseModel):
    thread_id: str
    message: Optional[str] = None  # None on first call → triggers greeting


class StateResponse(BaseModel):
    travel_dates: Optional[str] = None
    category: Optional[str] = None
    restrictions: Optional[str] = None
    companion: Optional[str] = None
    pace: Optional[str] = None
    purpose: Optional[str] = None
    day_specs: Optional[list[dict]] = None
    current_step: str
    # Which slot the buddy is waiting on right now, so the client can show the
    # matching quick replies / date picker. None outside the collecting step.
    current_field: Optional[str] = None
    confirmed: bool
    reply: Optional[str]
    itinerary: Optional[dict] = None


class TransitStop(BaseModel):
    name: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class TransitLegsRequest(BaseModel):
    stops: list[TransitStop]    # ordered list of selected stops


class ClosureCheckItem(BaseModel):
    poi_name: str
    address: str = ""
    visit_date: str            # "YYYY-MM-DD"


class ClosureCheckRequest(BaseModel):
    items: list[ClosureCheckItem]   # 한 일정당 15~25개 예상


class CheckinRequest(BaseModel):
    trip_id: str
    device_id: str
    itinerary: dict     # snapshot: planned stops per day + feasibility_score
    # Set only by Complete Check-in. Every checkbox tap also saves, and a paid
    # stamp generation per tap is what this flag exists to stop.
    generate_stamp: bool = False
    days: dict          # day number (as str) → {visited: [...], misses: {...}}


class SlotEdits(BaseModel):
    # POI에 안정적인 id가 없어서(critic_repair.as_output_poi에 id 필드 자체가
    # 없음) 전부 원래 poi_name 문자열로 식별한다 — build_candidate_pool과 동일한
    # normalize_text() 매칭 기준.
    excluded_ids: list[str] = []            # 제거된 POI 이름
    swapped_slots: dict[str, str] = {}      # {기존 POI 이름: 새 POI 이름}
    day_order: dict[str, list[str]] = {}    # {"1": [poi_name, ...]} 해당 day의 새 순서
    day_start_shift: dict[str, int] = {}    # {"2": 1} = Day 2가 Day 3으로 이동


class RevalidateRequest(BaseModel):
    thread_id: str
    edits: SlotEdits


class SwapCandidatesRequest(BaseModel):
    thread_id: str
    day: int
    slot_index: int
    current_poi: str
    day_area: str
    # 프론트가 이미 들고 있는 현재 POI의 type (Poi.type). candidate pool은
    # retrieved_courses/google_supplement에서만 채워지는데, LLM이 일정에 직접
    # 써넣은 POI(예: 호텔)는 pool에 아예 없을 수 있다 — 그 경우 pool 조회로
    # type을 못 찾아 카테고리 필터가 통째로 빠지면서 카페 자리에 호텔이,
    # 호텔 자리에 레스토랑이 뜨는 버그가 났다. 프론트가 보내는 이 값을
    # pool 조회보다 우선해서 항상 같은 카테고리로만 후보를 좁힌다.
    current_poi_type: Optional[str] = None
    time_window: Optional[str] = None
    purpose: Optional[str] = None
    excluded_ids: list[str] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _get_state(thread_id: str) -> dict:
    snapshot = _graph.get_state(_config(thread_id))
    if snapshot and snapshot.values:
        return snapshot.values
    return {
        "travel_dates": None, "category": None, "restrictions": None,
        "companion": None, "pace": None, "purpose": None, "day_specs": None,
        "current_step": "start", "confirmed": False, "messages": [],
    }


def _latest_ai_message(state: dict) -> Optional[str]:
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, AIMessage):
            return msg.content
    return None


def _state_response(state: dict, *, reply: Optional[str] = None) -> StateResponse:
    """StateResponse 를 만드는 유일한 곳. 필드가 늘 때마다 세 군데를 고치던 걸 막는다."""
    return StateResponse(
        travel_dates=state.get("travel_dates"),
        category=state.get("category"),
        restrictions=state.get("restrictions"),
        companion=state.get("companion"),
        pace=state.get("pace"),
        purpose=state.get("purpose"),
        day_specs=state.get("day_specs"),
        current_step=state.get("current_step", "start"),
        current_field=state.get("pending"),
        confirmed=state.get("confirmed", False),
        reply=reply if reply is not None else _latest_ai_message(state),
        itinerary=state.get("itinerary"),
    )


def _run(thread_id: str, user_input: Optional[str]) -> dict:
    # ponytail: only pass the new message — spreading the full state (including
    # the existing messages list) into invoke() causes add_messages to double
    # history on every turn because the reducer merges checkpoint + input.
    input_update = {"messages": [HumanMessage(content=user_input)]} if user_input else {"messages": []}
    return _graph.invoke(input_update, _config(thread_id))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/chat", response_model=StateResponse)
def chat(req: ChatRequest):
    """Send a message (or None for the initial greeting) and get back
    the updated state plus the latest AI reply."""
    _require_thread_id(req.thread_id)
    # Input gatekeeper (NeMo self-check): drop off-topic / prompt-injection /
    # jailbreak messages before they reach the planner. Empty message (the
    # greeting turn) is never blocked. Fails open on any guardrail error.
    #
    # The pending question goes with it: intake asks one thing at a time, so most
    # replies are fragments, and judging "none" without knowing it answers "Any
    # dietary or physical restrictions?" blocked it as chit-chat.
    state = _get_state(req.thread_id)
    pending_question = FIELD_QUESTIONS.get(state.get("pending") or "")
    if req.message and is_blocked(req.message, pending_question):
        return _state_response(state, reply=_BLOCKED_REPLY)

    try:
        new_state = _run(req.thread_id, req.message)
    except Exception as e:
        import traceback
        traceback.print_exc()          # prints full stack to uvicorn terminal
        raise HTTPException(status_code=500, detail=_INTERNAL_ERROR)

    return _state_response(new_state)


@app.get("/state", response_model=StateResponse)
def get_state(thread_id: str):
    """Return current state without invoking the graph."""
    state = _get_state(_require_thread_id(thread_id))
    return _state_response(state)


@app.post("/reset")
def reset(thread_id: str):
    """Clear one thread's conversation without touching any other sessions."""
    clear_thread(_require_thread_id(thread_id))
    return {"status": "reset"}


class DaySpec(BaseModel):
    day: int
    region: str
    interest: str


class DayPlanRequest(BaseModel):
    thread_id: str
    days: list[DaySpec]


@app.post("/day-plan", response_model=StateResponse)
def day_plan(req: DayPlanRequest):
    """Day Planner 화면이 정한 날짜별 지역·관심사를 저장하고 confirm 으로 넘긴다.

    어휘가 어긋나면 400 으로 시끄럽게 실패한다. retrieval 의 필터는 문자열
    비교라서, 통과시키면 조용히 0개를 반환하고 그날 앵커가 사라진다.
    """
    from graph import DAY_PLAN_REGIONS, INTEREST_LABELS
    from rag import _parse_num_days

    thread_id = _require_thread_id(req.thread_id)
    state = _get_state(thread_id)

    # A state conflict, not malformed input -- 409, distinct from the 400s
    # below. Without this, a thread that never finished intake (travel_dates
    # still None) sails through: _parse_num_days(None) == 1, so a 1-day plan
    # passes the length check trivially and current_step jumps to confirm
    # with every other slot still empty.
    if state.get("current_step") != "day_plan":
        raise HTTPException(status_code=409, detail="thread is not ready for a day plan")

    expected = _parse_num_days(state.get("travel_dates"))
    days = [d.model_dump() for d in req.days]

    if len(days) != expected:
        raise HTTPException(status_code=400, detail=f"expected {expected} days, got {len(days)}")
    if sorted(d["day"] for d in days) != list(range(1, expected + 1)):
        raise HTTPException(status_code=400, detail="day numbers must be 1..N with no gaps or repeats")
    for d in days:
        if d["region"] not in DAY_PLAN_REGIONS:
            raise HTTPException(status_code=400, detail=f"unknown region: {d['region']}")
        if d["interest"] not in INTEREST_LABELS:
            raise HTTPException(status_code=400, detail=f"unknown interest: {d['interest']}")

    days.sort(key=lambda d: d["day"])
    _graph.update_state(_config(thread_id), {"day_specs": days, "current_step": "confirm"})
    return _state_response(_get_state(thread_id))


class PoiSummaryRequest(BaseModel):
    name: str
    type: str = ""


def _grounded_poi_text(kind: str, req: PoiSummaryRequest) -> str:
    """poi_text.py's web-grounded, cached text; 503 without a Tavily key."""
    import poi_text

    try:
        return poi_text.poi_text(kind, req.name, req.type)
    except poi_text.NotConfigured:
        raise HTTPException(status_code=503, detail="TAVILY_API_KEY not configured")
    except Exception:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=_INTERNAL_ERROR)


@app.post("/poi-summary")
def poi_summary(req: PoiSummaryRequest):
    """1-2 sentence description of a Seoul POI, from a Tavily web search
    rewritten by Gemini (poi_text.py). Empty when the web has nothing on it."""
    return {"summary": _grounded_poi_text("summary", req)}


@app.post("/poi-image")
def poi_image(req: PoiSummaryRequest, request: Request):
    """Return the best-matching thumbnail for a Seoul POI.

    0. Look the name up in _POI_IMAGES — 코스 원본 페이지에서 미리 긁어둔 공식
       사진, 또는 그것도 없어서 사람이 직접 찍어 넣은 사진이다. 대부분의 정거장이
       여기서 끝난다. 공짜에 즉시 응답이고, 무엇보다 실제 그 장소의 사진이라 아래
       검색보다 정확하다.

    Miss 면(플래너가 끼워 넣은 식사 슬롯, 교체 후보, Google Places 로 들어온
    정거장) 그 장소의 Google Maps 사진(업주·리뷰어가 올린 사진)을 쓴다. Find Place 로
    첫 사진의 photo_reference 를 찾아 /place-photo 프록시 URL 로 돌려준다 — 키는
    서버 밖으로 나가지 않는다. 웹 이미지 검색과 달리 동명의 엉뚱한 장소 사진이
    섞이지 않고, Gemini 호출도 들지 않는다.
    """
    cached = _POI_IMAGES.get(req.name)
    if cached:
        if cached.startswith("local:"):
            filename = cached.removeprefix("local:")
            base = str(request.base_url).rstrip("/")
            cached = f"{base}/static/poi_images/{quote(filename)}"
        return {"image_url": cached}

    # 키 확인은 여기서 한다. 미리 긁어둔 사진만으로도 화면이 서므로, Places 키
    # 없이 띄운 백엔드가 알려진 POI 에서까지 503 을 뱉으면 안 된다.
    places_key = os.getenv("GOOGLE_PLACES_API_KEY", "")
    if not places_key:
        raise HTTPException(status_code=503, detail="GOOGLE_PLACES_API_KEY not configured")

    import planner

    ref = planner.find_place_photo_ref(name=req.name, api_key=places_key)
    if not ref:
        return {"image_url": ""}
    base = str(request.base_url).rstrip("/")
    return {"image_url": f"{base}/place-photo?ref={quote(ref, safe='')}&w=400"}


@app.post("/poi-detail")
def poi_detail(req: PoiSummaryRequest):
    """Return structured visitor bullet points for a Seoul POI (stop selection screen).

    Tavily fetches live web data (hours, fees, tips); Gemini rewrites only that
    into labeled bullet lines (poi_text.py), cached per place.
    """
    return {"detail": _grounded_poi_text("detail", req)}


class EventsRequest(BaseModel):
    category: str = "Concert"
    travel_dates: Optional[str] = None


# ── world.nol.com/en live scraping for /events ─────────────────────────────────
# NOL's English storefront. Card markup is in the initial HTML (Next.js, but
# server-rendered), it sits on CloudFront with no bot challenge, and the titles /
# dates / venues are already in English — so plain httpx + regex is enough.
# (The Korean nol.yanolja.com is behind a Cloudflare TLS challenge that 403s
# every plain HTTP client; that's why we don't scrape it.)
import re as _re
import time as _time
import html as _html

# The nine genres in world.nol.com/en/ticket's own nav, in its own order,
# keyed on the label the app puts on the chip. Slugs are read off the nav's
# hrefs (/en/ticket/genre/<slug>/products) -- note they are upper-case except
# play-stay, and that NOL's label and its slug disagree more often than not
# ("Play" is DRAMA, "Exhibitions" is EXHIBIT, "Family" is KIDS).
#
# The list used to be six entries with two labels NOL does not use, so Sports,
# Dance and Play&Stay were unreachable from the app.
_NOL_GENRE = {
    "play&stay": "play-stay",
    "concert": "CONCERT",
    "musical": "MUSICAL",
    "play": "DRAMA",
    "exhibitions": "EXHIBIT",
    "sports": "SPORTS",
    "dance": "DANCE",
    "classic": "CLASSIC",
    "family": "KIDS",
    # Labels older builds send. Kept so an app that has not been updated
    # still resolves rather than silently landing on Musical.
    "theater": "DRAMA",
    "exhibition": "EXHIBIT",
    "classical": "CLASSIC",
    "kids": "KIDS",
}
_NOL_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ponytail: module-level dict cache (~10 min TTL). Pages are ~270KB so we don't
# refetch per tab; if this ever runs multi-process, swap to Redis.
_EVENTS_CACHE: dict[str, tuple[float, list]] = {}
_EVENTS_TTL = 600  # seconds

# Card shape:
#   <a href="/en/ticket/places/26001042/products/26012554">
#     <img src="https://ticketimage.interpark.com/..." alt="TITLE">
#     <h2 ...>TITLE</h2>
#     <span ...>Oct 31, 2026 - Nov 02, 2026</span>
#     <span ...>S Factory</span>
#   </a>
_NOL_CARD_RE = _re.compile(
    r'<a\b[^>]*?href="(?P<href>/en/ticket/places/\d+/products/\d+)"', _re.S
)
_NOL_IMG_RE = _re.compile(r'<img\b[^>]*?\bsrc="(?P<src>https?://[^"]+)"', _re.S)
_NOL_H2_RE = _re.compile(r"<h2\b[^>]*>(?P<t>.*?)</h2>", _re.S)
_NOL_SPAN_RE = _re.compile(r"<span\b[^>]*>(?P<t>[^<]+)</span>", _re.S)
_NOL_DATE_RE = _re.compile(r"[A-Z][a-z]{2}\s+\d{1,2},\s*\d{4}")


def _nol_text(s: str) -> str:
    return _html.unescape(_re.sub(r"<[^>]+>", "", s)).strip()


def _parse_nol(html_text: str, cap: int = 20) -> list:
    out, seen = [], set()
    # Split on each <a so image / title / spans are scoped to one card.
    for block in _re.split(r"(?=<a\b)", html_text):
        m = _NOL_CARD_RE.match(block)
        if not m:
            continue
        im = _NOL_IMG_RE.search(block)
        h2 = _NOL_H2_RE.search(block)
        name = _nol_text(h2.group("t")) if h2 else ""
        if not name and im:  # promo cards carry the title only in <img alt>
            alt = _re.search(r'\balt="([^"]+)"', im.group(0))
            name = _html.unescape(alt.group(1)).strip() if alt else ""
        if not name or name in seen:
            continue
        spans = [t for t in (_html.unescape(s).strip() for s in _NOL_SPAN_RE.findall(block)) if t]
        date = next((s for s in spans if _NOL_DATE_RE.search(s)), "")
        venue = next((s for s in spans if s != date), "")
        seen.add(name)
        out.append({
            "name": name,
            "date": date,
            "venue": venue,
            "description": "",
            "image_url": _html.unescape(im.group("src")) if im else "",
            "landing_url": "https://world.nol.com" + m.group("href"),
        })
        if len(out) >= cap:
            break
    return out


@app.post("/events")
def get_events(req: EventsRequest):
    """Live-scrape world.nol.com/en ticket genre pages for real Seoul events.

    Returns a list of {name, date, venue, description, image_url, landing_url}.
    On ANY failure returns [] (never 500) — Flutter's empty state handles it."""
    cached = None
    try:
        slug = _NOL_GENRE.get((req.category or "").strip().lower(), "MUSICAL")

        cached = _EVENTS_CACHE.get(slug)
        if cached and (_time.time() - cached[0]) < _EVENTS_TTL:
            return cached[1]

        import httpx as _httpx

        resp = _httpx.get(
            f"https://world.nol.com/en/ticket/genre/{slug}/products",
            headers={"User-Agent": _NOL_UA},
            timeout=15,
            follow_redirects=True,
        )
        resp.raise_for_status()
        events = _parse_nol(resp.text)
        if not events:
            # Upstream block or markup change — say so, and keep the stale grid
            # rather than blanking it. Silence here looks like "no events today".
            print(f"[events] {slug}: fetched {len(resp.text)}B but parsed 0 events")
            return cached[1] if cached else []
        _EVENTS_CACHE[slug] = (_time.time(), events)
        return events
    except Exception as e:
        print(f"[events] {req.category!r} failed: {type(e).__name__}: {e}")
        return cached[1] if cached else []


@app.post("/transit-legs")
def transit_legs(req: TransitLegsRequest):
    """Recompute distance / walk / car / Kakao links / ODsay public-transit
    options for an arbitrary ordered list of stops.

    Used when the user re-selects a subset of stops on the route screen, so the
    transit between the *new* consecutive pairs is real ODsay data rather than a
    straight-line estimate. Returns one leg per consecutive pair (N-1 legs)."""
    from planner import compute_transit_legs

    pois = [
        {"name": s.name, "lat": s.lat, "lng": s.lng}
        for s in req.stops
    ]
    try:
        legs = compute_transit_legs(pois)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=_INTERNAL_ERROR)
    return {"transit_legs": legs}


@app.post("/poi-closure-check")
def poi_closure_check(req: ClosureCheckRequest):
    """Final Route 화면에서, 확정된 stops + 실제 방문일(visit_date)로 임시휴관
    여부를 Google Search grounding으로 확인한다.

    Best-effort: 어떤 실패든(API 오류, 타임아웃, 파싱 실패) 절대 500을 내지
    않고 해당 항목을 unknown으로 채워 반환한다 — 이 체크가 일정 생성/표시
    자체를 막아서는 안 된다."""
    from closure_check import check_batch, _unknown_result

    tuples = [(it.poi_name, it.address, it.visit_date) for it in req.items]
    try:
        results = check_batch(tuples)
    except Exception:
        import traceback
        traceback.print_exc()
        results = [_unknown_result(it.poi_name, it.visit_date) for it in req.items]
    return {"results": results}


@app.post("/trip/checkin")
def trip_checkin(req: CheckinRequest, background_tasks: BackgroundTasks):
    """Store one trip's check-in snapshot. Write-only: the client renders its
    recap from its own local copy, so there is no read path here. Returns
    stored=false rather than an error when persistence is unavailable."""
    # Trust-boundary validation: ids are used as a primary key, and the two
    # JSON blobs come straight off the wire.
    # trip_id also becomes the stamp's file name, so [A-Za-z0-9_-] only.
    if not valid_trip_id(req.trip_id):
        raise HTTPException(status_code=422, detail="invalid trip_id")
    if not req.device_id or len(req.device_id) > 128:
        raise HTTPException(status_code=422, detail="invalid device_id")
    payload_bytes = len(json.dumps(req.itinerary)) + len(json.dumps(req.days))
    if payload_bytes > 256_000:
        raise HTTPException(status_code=413, detail="payload too large")

    stored = save_checkin(req.trip_id, req.device_id, req.itinerary, req.days)
    # `stored` is False when this trip_id belongs to another device, and that
    # device's stamp must not be repainted with someone else's visits.
    if stored and req.generate_stamp and request_stamp(req.trip_id, req.itinerary, req.days):
        # Fire-and-forget: a ~60s image edit must never make the save hang.
        background_tasks.add_task(generate_stamp, req.trip_id, req.itinerary, req.days)
    return {"stored": stored}


@app.get("/trip/stamp/{trip_id}")
def trip_stamp(trip_id: str):
    """The trip's journey stamp: generating | ready (+version, for
    cache-busting) | failed | none. Polled by the recap while it's painted."""
    if not valid_trip_id(trip_id):
        raise HTTPException(status_code=422, detail="invalid trip_id")
    return stamp_status(trip_id)


@app.post("/revalidate")
def revalidate(req: RevalidateRequest):
    """User Selection 화면에서 사용자가 편집한 슬롯 상태(제외/교체/재정렬/day
    이동)를 반영한 뒤, CriticAgent -> RepairAgent -> CriticAgent 순서로 다시
    돌려서 이슈/점수를 before-after로 준다. graph.py의 critic_repair 노드는
    /chat 한 턴 안에서만 도는데, 여기가 User Selection 이후 재검증하는 유일한
    경로다 — day_start_shift로 day 번호가 바뀌면 실제 요일도 바뀌므로,
    요일 기반 규칙(CLOSED_ON_ASSIGNED_DAY 등)이 여기서 새로 체크된다.

    끝나면 새 itinerary를 체크포인트에 저장한다(update_state) — 이어지는
    편집(재교체, 재정렬)이 이 결과 위에서 계속되도록."""
    from critic_repair import CriticAgent, RepairAgent, apply_slot_edits, build_candidate_pool
    from planner import compute_transit_legs

    thread_id = _require_thread_id(req.thread_id)
    state = _get_state(thread_id)
    if not state.get("itinerary"):
        raise HTTPException(status_code=404, detail="no itinerary for this thread_id")

    try:
        pool = build_candidate_pool(state)
        edited_itinerary = apply_slot_edits(
            state["itinerary"], req.edits.model_dump(), pool
        )
        edited_state = {**state, "itinerary": edited_itinerary}

        critic = CriticAgent()
        before_report = critic.evaluate(edited_state)

        repaired_itinerary, repair_log = RepairAgent().repair(edited_state, before_report)
        for day in repaired_itinerary.get("days") or []:
            day["transit_legs"] = compute_transit_legs(day.get("pois") or [])

        after_state = {**edited_state, "itinerary": repaired_itinerary}
        after_report = critic.evaluate(after_state)

        _graph.update_state(_config(thread_id), {"itinerary": repaired_itinerary})
    except HTTPException:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=_INTERNAL_ERROR)

    return {
        "before": before_report,
        "after": after_report,
        "repaired_itinerary": repaired_itinerary,
        "repair_log": repair_log,
    }


@app.post("/swap-candidates")
def swap_candidates(req: SwapCandidatesRequest):
    """current_poi와 같은 슬롯 성격(식당/카페 등)의 대체 후보 최대 3개를,
    같은 area 안에서 찾아 반환한다. 각 후보에는 사전 검증 경고가 붙는다 —
    특히 closed_weekday와 이 day의 실제 요일(trip_start_date + day로 계산)이
    겹치면 "화요일 정기휴무" 식으로 미리 알려준다.

    is_generic_activity/is_transit_marker/requires_review로 걸러진 POI는
    build_candidate_pool 단계에서 이미 후보 풀에 없으므로 여기서 따로 걸러낼
    필요가 없다.

    v1 범위: time_window/purpose는 스키마에는 받지만 아직 후보 필터링에는
    안 쓴다(슬롯별 시간대·목적 매칭에 쓸 신호가 POI 데이터에 없음) — 나중에
    확장 여지로 받아만 둔 상태임을 명시."""
    from critic_repair import (
        build_candidate_pool, candidates_for_area, google_fallback_candidates, normalize_text,
    )
    from date_utils import weekday_for_day
    from planner import GOOGLE_PLACES_API_KEY

    thread_id = _require_thread_id(req.thread_id)
    state = _get_state(thread_id)
    if not state.get("itinerary"):
        raise HTTPException(status_code=404, detail="no itinerary for this thread_id")

    try:
        pool = build_candidate_pool(state)
        current = pool.get(normalize_text(req.current_poi))
        # current_poi_type(프론트가 보낸 실제 type)을 pool 조회보다 우선한다 —
        # pool에 없는 POI(호텔 등 LLM이 직접 써넣은 것)라도 카테고리 필터가
        # 반드시 걸리도록.
        type_hint = req.current_poi_type or (current["type"] if current else None)
        preferred_types = {normalize_text(type_hint)} if type_hint else set()

        exclude = {normalize_text(x) for x in req.excluded_ids}
        exclude.add(normalize_text(req.current_poi))

        # candidates_for_area's own sort order (source_kind/type) is shared with
        # RepairAgent's fill-in logic -- don't touch it. Re-sort its output by
        # rating on top instead, so this endpoint prefers rated candidates
        # without changing repair's existing behavior.
        filtered = candidates_for_area(
            pool, req.day_area, exclude=exclude, preferred_types=preferred_types,
        )

        # The existing pool (retrieved_courses + google_supplement) was never
        # built to cover every area+type combination a user might swap on --
        # a zero result above means the pool never checked, not that no real
        # candidates exist nearby. Only hit Google when the pool truly came
        # up empty (never on top of a non-empty result, to avoid the extra
        # cost/latency), centered on current_poi's own coordinates.
        if not filtered:
            fallback_lat = current.get("lat") if current else None
            fallback_lng = current.get("lng") if current else None
            if fallback_lat is None or fallback_lng is None:
                print(
                    f"[swap fallback] current_poi {req.current_poi!r} has no known "
                    "coordinates (not in pool) -- skipping Google fallback"
                )
            elif not GOOGLE_PLACES_API_KEY:
                print("[swap fallback] GOOGLE_PLACES_API_KEY 없음 -- 폴백 생략")
            else:
                filtered = google_fallback_candidates(
                    lat=fallback_lat, lng=fallback_lng, place_type=type_hint,
                    exclude=exclude, api_key=GOOGLE_PLACES_API_KEY,
                )
                if filtered:
                    # /revalidate only swaps in names it finds in
                    # build_candidate_pool(state). Google-only candidates have
                    # to be on the thread, or picking one silently keeps the
                    # original stop.
                    ctx = state.get("planning_context") or {}
                    _graph.update_state(_config(thread_id), {"planning_context": {
                        **ctx,
                        "google_supplement": [*(ctx.get("google_supplement") or []), *filtered],
                    }})

        rated = sorted(
            (i for i in filtered if i.get("rating") is not None),
            key=lambda i: -i["rating"],
        )
        unrated = [i for i in filtered if i.get("rating") is None]
        ranked = (rated + unrated)[:3]

        weekday = None
        trip_start_date = state.get("trip_start_date")
        if trip_start_date:
            try:
                weekday = weekday_for_day(trip_start_date, req.day, lang="en")
            except (ValueError, TypeError):
                weekday = None  # 폴백 -- 요일 경고만 생략, 나머지는 계속 진행

        candidates = []
        for item in ranked:
            warnings: list[str] = []
            closed = item.get("closed_weekday") or []
            if weekday and weekday in closed:
                warnings.append(f"{weekday} 정기휴무 — Day {req.day}과 겹칠 수 있음")
            if item.get("is_area_type"):
                warnings.append("특정 업체가 아니라 지역/거리 전체를 가리키는 POI")

            candidates.append({
                "poi_name": item.get("name"),
                "poi_type": item.get("type"),
                "address": item.get("address"),
                "lat": item.get("lat"),
                "lng": item.get("lng"),
                "rating": item.get("rating"),
                "warnings": warnings,
            })
    except HTTPException:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=_INTERNAL_ERROR)

    return {"candidates": candidates}


if __name__ == "__main__":
    # Parser self-check: `python api.py` — prefers a saved fixture
    # (backend/_fixtures/nol_musical.html); falls back to a live fetch.
    import pathlib

    fixture = pathlib.Path(_here) / "_fixtures" / "nol_musical.html"
    if fixture.exists():
        html_text = fixture.read_text(encoding="utf-8")
        print(f"[selfcheck] using fixture {fixture}")
    else:
        import httpx
        html_text = httpx.get(
            "https://world.nol.com/en/ticket/genre/MUSICAL/products",
            headers={"User-Agent": _NOL_UA},
            timeout=15,
            follow_redirects=True,
        ).text
        print("[selfcheck] using live fetch (no fixture found)")

    events = _parse_nol(html_text)
    assert events, "parser extracted 0 events"
    first = events[0]
    assert first["name"], "first event has empty name"
    assert first["image_url"], "first event has empty image_url"
    assert first["landing_url"].startswith("https://world.nol.com/en/ticket/")
    assert set(first) >= {"name", "date", "venue", "description", "image_url", "landing_url"}
    print(f"[selfcheck] OK — {len(events)} events; first = {first['name']!r} / {first['date']!r}")
