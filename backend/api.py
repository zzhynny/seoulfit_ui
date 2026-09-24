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
import datetime as _dt
import functools
import re as _re
import threading as _threading
import time as _time

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse as _JSONResponse
from typing import Optional
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, AIMessage

# In dev we load .env from disk; in prod (Render) env vars are injected
# directly into the process so load_dotenv is a no-op.
load_dotenv(os.path.join(_here, ".env"))

import tourapi  # 한국관광공사 TourAPI 런타임 클라이언트
from stamp import _HANGUL_RE  # 로마자 변환기가 쓰는 것과 같은 판정

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
    # 아래 넷은 리스트를 받아 항목마다 외부 호출을 한다. 한 요청이 수백 회로
    # 불어나므로 요청 수로 재는 이 리밋만으로는 부족하고, 모델 쪽 max_length
    # 와 같이 걸어야 의미가 있다.
    "/revalidate",         # Critic → Repair → Critic, 요청당 Gemini 여러 번
    "/swap-candidates",    # Google Places 유료 호출로 떨어질 수 있다
    "/events",             # 공사 API 2회 (캐시 miss 시)
    # 탭 한 번에 공사 API 2회. contentid 를 바꿔가며 돌리면 캐시가 안 먹어서
    # /events 와 달리 호출이 그대로 상류로 나간다 — 일일 쿼터가 표적이 된다.
    "/event-detail",
}
# 120/min, not 30: user_selection_screen renders one card per candidate stop
# and each fires fetchPoiDetail on build, and final_itinerary_map_screen
# fires summary + image per stop, so a legitimate screen load is already a
# 20-40 call burst. An abuse loop does thousands, so the gap is wide enough.
#
# 600, not 120: the bucket is per IP, and a classroom on campus Wi-Fi or phones
# behind a carrier NAT all share one. At 120 a handful of people opening their
# itineraries in the same minute got 429s. 600 covers ~15-20 of them and still
# caps a scripted loop at 10 requests a second.
_RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MIN", "600"))
_RATE_WINDOW = 60.0
# 프록시 뒤인가. Render/Fly 처럼 TLS 를 종단하는 앞단이 있으면 1(기본).
# 직접 인터넷에 노출한다면 0 으로 두어야 X-Forwarded-For 를 아예 안 믿는다.
#
# ⚠ 이것만으로는 부족하다. uvicorn 의 ProxyHeadersMiddleware 가 기본으로 켜져
# 있고, 그건 X-Forwarded-For 의 **첫** 값(= 클라이언트가 위조할 수 있는 값)으로
# request.client.host 를 덮어쓴다. 그러면 TRUST_PROXY=0 이어도 아래 fallback 이
# 이미 오염된 값을 읽는다. 반드시 `--no-proxy-headers` 로 띄울 것 — 실측으로
# 둘 중 하나만 닫으면 헤더 한 줄에 리밋이 통째로 뚫린다.
_TRUST_PROXY = os.getenv("TRUST_PROXY", "1") not in ("0", "false", "False")

_rate_hits: dict[str, tuple[float, int]] = {}
_rate_lock = _threading.Lock()


def _client_ip(request) -> str:
    """레이트 리밋 버킷 키. 프록시 뒤에 있을 때 진짜 클라이언트를 고른다.

    X-Forwarded-For 는 왼쪽이 원본, 오른쪽이 가장 가까운 프록시다. 단 왼쪽은
    클라이언트가 보낸 값을 그대로 이어받은 것이라 통째로 위조된다 — 첫 홉을
    믿으면 `-H 'X-Forwarded-For: $RANDOM'` 한 줄로 매 요청이 새 버킷이 되고
    레이트 리밋이 없는 것과 같아진다.

    우리 프록시가 직접 덧붙인 마지막 홉만 믿는다. 프록시가 정확히 하나라는
    전제이고, 그게 아니면(직접 노출, 프록시 2단) 이 분기를 지워야 한다.
    """
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd and _TRUST_PROXY:
        return fwd.split(",")[-1].strip()
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
        if len(_rate_hits) > 10_000:
            # 통째로 clear() 하면 한도를 채운 쪽까지 같이 풀려난다 — 위조 IP 로
            # 딕셔너리를 불리는 것만으로 전원의 리밋을 리셋할 수 있었다.
            # 창이 끝난 것만 버린다.
            for k in [k for k, (t, _) in _rate_hits.items() if now - t >= _RATE_WINDOW]:
                del _rate_hits[k]
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
    # "*" 를 그대로 통과시키면 아래에서 공들여 막아놓은 구멍이 환경변수 한 줄로
    # 다시 열린다 — 인터넷의 아무 페이지나 방문자 브라우저를 통해 이 API 를
    # 부리고 Gemini/SerpApi/Places 요금을 태울 수 있다. 설정 실수로 그렇게 되는
    # 쪽보다 시끄럽게 죽는 쪽이 낫다.
    if o == "*":
        raise RuntimeError(
            "FRONTEND_ORIGIN=* is not allowed — list the deployed frontend "
            "origins explicitly (comma-separated)."
        )
    if not o:
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
print(f"[ratelimit] {_RATE_LIMIT}/min on {len(_METERED_PATHS)} paths · "
      f"X-Forwarded-For {'trusted (last hop)' if _TRUST_PROXY else 'ignored'} · "
      f"run with --no-proxy-headers or uvicorn overrides this")

if _cors_origins:
    print(f"[cors] allowing {', '.join(_cors_origins)}")
else:
    # 이 상태로 배포하면 브라우저가 모든 요청을 막고 앱은 빈 화면이 된다.
    # 콘솔에 아무 말도 없으면 원인을 찾는 데만 한나절이 간다.
    print("[cors] FRONTEND_ORIGIN unset — allowing localhost only. "
          "A deployed web frontend WILL be blocked; set FRONTEND_ORIGIN.")

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


# One graph turn per session at a time. The app gives up on generation after
# 180s while the server keeps going; a retry then resumed from the last
# checkpoint (route_entry -> retrieve/plan) and ran a second generation
# alongside the first -- double the Gemini/Places spend, last write wins. The
# same read-modify-write race hit /revalidate and /swap-candidates. Blocking,
# not 409: the retry waits for the run in flight and returns its itinerary.
#
# ponytail: one small Lock per session id, never evicted -- grows with
# sessions exactly like MemorySaver does, and goes away with it on restart.
_session_locks: dict[str, _threading.Lock] = {}
_session_locks_guard = _threading.Lock()


def _session_lock(thread_id: str) -> _threading.Lock:
    with _session_locks_guard:
        return _session_locks.setdefault(thread_id, _threading.Lock())


def _one_turn_per_session(endpoint):
    """Serialise an endpoint whose body (`req`) names a thread_id."""
    @functools.wraps(endpoint)
    def wrapper(req, *args, **kwargs):
        with _session_lock(_require_thread_id(req.thread_id)):
            return endpoint(req, *args, **kwargs)
    return wrapper


class ChatRequest(BaseModel):
    thread_id: str
    # None on first call → triggers greeting. 상한은 가드레일과 플래너 양쪽
    # Gemini 호출에 그대로 들어가는 값이라 건다 — 사람이 채팅창에 치는 한 문장은
    # 수백 자를 넘지 않는다.
    message: Optional[str] = Field(None, max_length=2000)


class StateResponse(BaseModel):
    travel_dates: Optional[str] = None
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
    current_poi: str = Field(max_length=200)
    day_area: str = Field(max_length=100)
    # 프론트가 이미 들고 있는 현재 POI의 type (Poi.type). candidate pool은
    # retrieved_courses/google_supplement에서만 채워지는데, LLM이 일정에 직접
    # 써넣은 POI(예: 호텔)는 pool에 아예 없을 수 있다 — 그 경우 pool 조회로
    # type을 못 찾아 카테고리 필터가 통째로 빠지면서 카페 자리에 호텔이,
    # 호텔 자리에 레스토랑이 뜨는 버그가 났다. 프론트가 보내는 이 값을
    # pool 조회보다 우선해서 항상 같은 카테고리로만 후보를 좁힌다.
    current_poi_type: Optional[str] = None
    excluded_ids: list[str] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config(thread_id: str) -> dict:
    # metadata.thread_id is the key LangSmith groups a conversation's traces by,
    # and the join key back to evals.db.
    return {"configurable": {"thread_id": thread_id},
            "metadata": {"thread_id": thread_id}}


def _get_state(thread_id: str) -> dict:
    snapshot = _graph.get_state(_config(thread_id))
    if snapshot and snapshot.values:
        return snapshot.values
    return {
        "travel_dates": None, "restrictions": None,
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
@_one_turn_per_session
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
    with _session_lock(_require_thread_id(thread_id)):
        clear_thread(thread_id)
    return {"status": "reset"}


class DaySpec(BaseModel):
    day: int
    region: str
    # 선택 메모. 그날의 검색 질의와 프롬프트에 들어가므로 길이를 막는다.
    note: str = Field("", max_length=200)


# The question the note field answers -- handed to the input rail so it judges
# a short note ("mom's birthday") as an answer, not as chit-chat.
_NOTE_QUESTION = "Anything special you want from this day of your Seoul trip?"


def _read_note(note: str) -> tuple[str, list[dict[str, str]]]:
    """(note to keep, its search keywords). A blocked note is dropped, not
    rejected: it's optional, and a 400 here reaches the traveller only as a
    generic failure. Neither call raises -- the rail fails open, extraction
    returns []."""
    from graph import _extract_purpose_keywords

    note = note.strip()
    if not note:
        return "", []
    if is_blocked(note, _NOTE_QUESTION):
        print(f"[day-plan] note blocked by input rail, dropped: {note[:60]!r}")
        return "", []
    return note, _extract_purpose_keywords(note)


class DayPlanRequest(BaseModel):
    thread_id: str
    days: list[DaySpec] = Field(max_length=30)   # 한 달 넘는 일정은 받지 않는다


@app.post("/day-plan", response_model=StateResponse)
@_one_turn_per_session
def day_plan(req: DayPlanRequest):
    """Day Planner 화면이 정한 날짜별 구역·메모를 저장하고 confirm 으로 넘긴다.

    구역이 어긋나면 400 으로 시끄럽게 실패한다. 통과시키면 retrieval 이 조용히
    0개를 반환하고 그날 앵커가 사라진다. 메모마다 검색어를 여기서 뽑는다 —
    인테이크의 여행 목적과 같은 이유로, 일정 생성 시간에 얹지 않으려고.
    """
    from concurrent.futures import ThreadPoolExecutor

    from graph import DAY_PLAN_REGIONS
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

    with ThreadPoolExecutor(max_workers=len(days)) as pool:
        for d, (note, keywords) in zip(days, pool.map(_read_note, [d["note"] for d in days])):
            d["note"], d["keywords"] = note, keywords

    days.sort(key=lambda d: d["day"])
    _graph.update_state(_config(thread_id), {"day_specs": days, "current_step": "confirm"})
    return _state_response(_get_state(thread_id))


class PoiSummaryRequest(BaseModel):
    # name 은 Tavily 질의와 Gemini 프롬프트가 되고, _poi_text_cache.json 의
    # 키로 영구히 남는다 — 긴 이름을 반복해 보내면 그 파일이 무한히 커진다.
    name: str = Field(max_length=200)
    type: str = Field("", max_length=100)


def _norm_poi_name(title: str) -> str:
    """이름 대조용 정규화. 공사 제목과 앱이 보내는 정거장 이름을 같은 자로 만든다.

    공사 제목은 `English (한글)` 이고 앱은 영문만 보낸다. 거기에 대소문자와
    `&`/`-` 같은 기호, 공백이 흔들려서 그대로 비교하면 거의 안 붙는다.
    """
    return _re.sub(r"[^a-z0-9]", "", tourapi.name_of(title).lower())


# ── 한국관광공사 TourAPI 로 채우는 POI 텍스트·사진 ─────────────────────────────
#
# /poi-summary · /poi-detail · /poi-image 는 이름으로만 조회된다(앱이 코스의
# 정거장 이름을 그대로 보낸다). 공사 API 는 contentid 로 움직이므로 그 사이를
# 이어줄 이름 색인이 필요하다.
#
# 색인은 사전 수집분 431건에서 만든다. 여기에 걸리면 소개글은 detailCommon2 로
# 실시간으로 받고(공사 공식 영문), 사진도 공사 CDN 것을 쓴다. 안 걸리면 기존
# Tavily + Gemini 경로가 그대로 받는다 — 코스 정거장 중에는 공사 DB 에 없는
# 골목·카페가 많아서 그 경로를 없앨 수는 없다.
_POI_SNAP: dict[str, dict] = {}
try:
    for _p in json.loads(
        (Path(_here) / "dataset" / "tour_poi.json").read_text(encoding="utf-8")
    ):
        _POI_SNAP.setdefault(_norm_poi_name(_p["title"]), _p)
except Exception as _e:  # 파일이 없어도 서버는 떠야 한다 — 폴백 경로가 있다.
    print(f"[poi] tour_poi.json index skipped: {_e}")
print(f"[poi] TourAPI name index: {len(_POI_SNAP)} entries")

# ── 미쉐린 가이드 restaurant.json 로 채우는 식당 텍스트·사진 ───────────────────
#
# 잠긴 점심·저녁 슬롯과 /swap-candidates 후보는 전부 이 파일에서 온다. 그런데
# 그 180곳 중 공사 DB(_POI_SNAP)에 걸리는 곳은 0곳이라, 지금까지 전부 Tavily
# 검색 + Gemini 생성으로 소개글을 새로 써 왔다 — 파일 안에 미쉐린 자신의 영문
# 리뷰(180/180)와 사진(180/180)이 이미 들어 있는데도. 이름 색인 하나를 앞에
# 두어 그 호출을 없앤다. 3일 일정이면 식당 6곳 × (Tavily + Gemini + Places 사진).
_MICHELIN_SNAP: dict[str, dict] = {}
try:
    import meal_slots as _meal_slots

    for _r in _meal_slots.load_restaurants():
        _MICHELIN_SNAP.setdefault(_norm_poi_name(_r["name"]), _r)
except Exception as _e:  # 파일이 없어도 서버는 떠야 한다 — 폴백 경로가 있다.
    print(f"[poi] restaurant.json index skipped: {_e}")
print(f"[poi] Michelin name index: {len(_MICHELIN_SNAP)} entries")


def _michelin(name: str) -> Optional[dict]:
    return _MICHELIN_SNAP.get(_norm_poi_name(name))

# ponytail: in-memory dict, 24시간 TTL. 공사 데이터는 하루 1회 갱신이라 그 이상
# 잡아둘 이유가 없다. 재시작하면 비지만, 한 번 받는 비용이 1회 호출이라 괜찮다.
_COMMON_CACHE: dict[str, tuple[float, dict]] = {}
_COMMON_TTL = 24 * 3600


def _tour_common(name: str) -> Optional[dict]:
    """이름이 공사 DB 에 있으면 detailCommon2 한 줄을 돌려준다. 없으면 None.

    실패는 삼킨다 — 부르는 쪽마다 Tavily/Places 폴백이 있어서, 여기서 예외를
    올리면 공사 API 장애가 곧 화면 장애가 된다.
    """
    snap = _POI_SNAP.get(_norm_poi_name(name))
    if not snap:
        return None
    cid = snap["id"]

    hit = _COMMON_CACHE.get(cid)
    if hit and (_time.time() - hit[0]) < _COMMON_TTL:
        return hit[1]

    try:
        rows, _ = tourapi.items("detailCommon2", contentId=cid)
    except Exception as e:
        print(f"[poi] detailCommon2({cid}) failed: {type(e).__name__}: {tourapi.redact(e)}")
        return None
    if not rows:
        return None

    _COMMON_CACHE[cid] = (_time.time(), rows[0])
    return rows[0]


def _first_sentences(text: str, n: int = 2) -> str:
    """소개글 앞 n 문장. overview 는 평균 600자라 카드에 그대로 못 넣는다."""
    parts = _re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return " ".join(parts[:n]).strip()


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
    """1-2 sentence description of a Seoul POI.

    한국관광공사 TourAPI 에 있는 곳이면 공사의 공식 영문 소개글(detailCommon2)
    앞 두 문장을 쓴다. 없는 곳만 Tavily 웹 검색 + Gemini 로 넘긴다."""
    michelin = _michelin(req.name)
    if michelin and (michelin.get("review") or "").strip():
        return {"summary": _first_sentences(michelin["review"])}
    common = _tour_common(req.name)
    if common and (common.get("overview") or "").strip():
        return {"summary": _first_sentences(common["overview"])}
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
    # 미쉐린 식당이면 가이드 CDN 사진. 그 식당의 실제 사진이고 출처가 분명하다.
    michelin = _michelin(req.name)
    if michelin and (michelin.get("image") or "").strip():
        return {"image_url": michelin["image"].strip()}

    # 공사 DB 에 있는 곳이면 공사 CDN 사진을 먼저 쓴다. 출처가 분명하고,
    # 아래 스크래핑 캐시나 Places 사진과 달리 저작권 표기가 가능한 이미지다.
    common = _tour_common(req.name)
    if common:
        official = (common.get("firstimage") or "").strip()
        if not official:
            # 대표 이미지가 비어 있을 때만 사진 목록을 따로 부른다.
            try:
                shots, _ = tourapi.items(
                    "detailImage2", contentId=common["contentid"], imageYN="Y")
                official = (shots[0].get("originimgurl") or "").strip() if shots else ""
            except Exception as e:
                print(f"[poi] detailImage2 failed: {type(e).__name__}: {tourapi.redact(e)}")
        if official:
            return {"image_url": official}

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


# 'Before you go' 한 줄씩. 결측이 흔해서 있는 것만 쓴다.
#
# 영업시간·휴무일·요금은 detailCommon2 응답에 없다 — detailIntro2 소관이고, 그건
# 관광타입마다 필드명이 다르다(restdate / restdateculture / restdatefood ...).
# 배치(fetch_tourapi.py --detail)가 이미 그 정규화를 해서 tour_poi.json 에 넣어
# 두었으므로 POI 당 호출을 하나 더 만들지 않고 그 값을 쓴다.
_DETAIL_LINES = (
    ("Hours", "hours"),
    ("Closed", "closed"),
    ("Entry", "fee"),
    ("Parking", "parking"),
)


@app.post("/poi-detail")
def poi_detail(req: PoiSummaryRequest):
    """Return structured visitor bullet points for a Seoul POI (stop selection screen).

    한국관광공사 TourAPI 에 있는 곳이면 공사 데이터(detailCommon2)로 줄을 세운다 —
    영업시간·휴무일·요금이 공식 값이고 LLM 이 끼지 않는다. 공사 DB 에 없는 골목
    가게 같은 곳만 Tavily + Gemini 경로로 간다.
    """
    michelin = _michelin(req.name)
    if michelin:
        closed_days = [
            day for day, ranges in (michelin.get("opening_hours") or {}).items()
            if not [r for r in (ranges or []) if r != "closed"]
        ]
        lines = [
            f"• {label}: {value}"
            for label, value in (
                ("Michelin", _MICHELIN_GRADE_EN.get(michelin.get("grade"), michelin.get("grade"))),
                ("Cuisine", michelin.get("cuisine")),
                ("Price", michelin.get("price")),
                # From opening_hours, which 137 of 180 rows carry. A row without
                # it yields no line rather than a wrong "open daily".
                ("Closed", ", ".join(closed_days) if closed_days else ""),
                ("Phone", michelin.get("tel")),
            )
            if str(value or "").strip()
        ]
        highlight = (michelin.get("review_full") or michelin.get("review") or "").strip()
        if highlight:
            lines.append(f"• Highlight: {_first_sentences(highlight, 1)}")
        if len(lines) >= 2:
            return {"detail": "\n".join(lines)}

    snap = _POI_SNAP.get(_norm_poi_name(req.name))
    common = _tour_common(req.name)
    if common and snap:
        lines = [f"• {label}: {' '.join(str(snap.get(field) or '').split())}"
                 for label, field in _DETAIL_LINES
                 if str(snap.get(field) or "").strip()]
        overview = (common.get("overview") or "").strip()
        if overview:
            lines.append(f"• Highlight: {_first_sentences(overview, 1)}")
        # 한 줄짜리는 화면이 허전하다. 그럴 바엔 기존 경로가 낫다.
        if len(lines) >= 2:
            return {"detail": "\n".join(lines)}
    return {"detail": _grounded_poi_text("detail", req)}


class EventsRequest(BaseModel):
    # kEventCategories 의 첫 칩. 모르는 값은 _chip_filter 가 전체로 떨어뜨린다.
    category: str = Field("All", max_length=40)
    travel_dates: Optional[str] = Field(None, max_length=100)


# ── /events — 한국관광공사 TourAPI(EngService2) 실시간 조회 ────────────────────
# 두 오퍼레이션을 합친다. 어느 한쪽만으로는 화면이 안 선다.
#
#   searchFestival2   기간이 박힌 축제. 날짜가 정확한 대신 서울에 14건뿐이다.
#   areaBasedList2    lclsSystm1=EV 전량 79건. 수문장 교대의식처럼 상시로 하는
#                     공연이 여기 있고, 그게 방한 여행자가 실제로 보러 가는 것이다.
#
# contentid 로 겹치는 것을 접고 나면 85건 남짓. 칩은 이 통합본을 메모리에서
# 거르므로, 칩을 몇 번 누르든 공사 API 호출은 10분에 두 번이다.

# lclsSystm2 → 앱 칩. cat1~3 은 EngService2 응답에서 전부 빈 문자열이라 못 쓴다.
_EV_CHIP = {
    "Festivals": "EV01",
    "Performances": "EV02",
    "Exhibitions": "EV03",
}

# ponytail: module-level dict cache (10분 TTL). 공사 데이터는 하루 1회 갱신이라
# 더 길게 잡아도 되지만, 심사 기간에 호출 이력이 남아야 해서 10분으로 둔다.
_EVENTS_CACHE: dict[str, tuple[float, list]] = {}
_EVENTS_TTL = 600  # seconds

# contentsView.do?vcontsId= 는 400 을 낸다 — vcontsId 는 공사 API 의 contentid 와
# 다른 ID 체계다. 카드 탭이 전건 오류 페이지로 가던 원인. 이쪽은 contentid 를
# 그대로 받는다. 살아 있는지는 selfcheck 가 실제로 쳐서 확인한다.
_EVENT_LANDING = "https://english.visitkorea.or.kr/enu/ATR/SI_EN_3_1_1_1.jsp?cid={cid}"


def _event_date(row: dict) -> str:
    """`20261002`/`20261004` → `Oct 02, 2026 - Oct 04, 2026`.

    areaBasedList2 로 들어온 상설 항목은 날짜 필드가 없다. 그때는 빈 문자열이고,
    Flutter 의 SeoulEvent 가 이미 빈 날짜를 처리한다.
    """
    def fmt(s: str) -> str:
        try:
            return _dt.datetime.strptime(s, "%Y%m%d").strftime("%b %d, %Y")
        except (ValueError, TypeError):
            return ""

    start, end = fmt(row.get("eventstartdate", "")), fmt(row.get("eventenddate", ""))
    if start and end and start != end:
        return f"{start} - {end}"
    return start or end


def _venue_of(row: dict) -> str:
    """카드 한 줄에 들어갈 장소. 영문 UI 라 영문인 쪽을 고른다.

    영문 서비스인데도 주소가 한글로 오는 행이 섞여 있다 — addr1(도로명)은 99건
    전부 차 있지만 41건이 한글이고, addr2(장소명)는 43건만 차 있고 그중 30건이
    한글이다. 어느 한 필드를 고정으로 쓰면 어느 쪽을 골라도 한글이 샌다.
    """
    addr1, addr2 = (row.get("addr1") or "").strip(), (row.get("addr2") or "").strip()
    for value in (addr1, addr2):
        if value and not _HANGUL_RE.search(value):
            return value
    return addr1 or addr2


def _coord(value) -> Optional[float]:
    """TourAPI 의 mapx/mapy 는 문자열이고, 가끔 빈 값이 온다."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_event(row: dict) -> dict:
    # contentid 는 /event-detail 이 상세를 받아올 때 쓴다. mapx/mapy 는 목록 응답에
    # 80/80 들어 있어서, 상세 시트의 카카오맵 버튼이 추가 호출 없이 선다.
    return {
        "contentid": row.get("contentid", ""),
        "name": tourapi.name_of(row.get("title", "")),
        "date": _event_date(row),
        "venue": _venue_of(row),
        "description": "",
        "image_url": row.get("firstimage") or "",
        "landing_url": _EVENT_LANDING.format(cid=row.get("contentid", "")),
        "lat": _coord(row.get("mapy")),
        "lng": _coord(row.get("mapx")),
        "_chip": row.get("lclsSystm2", ""),
    }


def _fetch_events() -> list[dict]:
    """공사 API 두 번 → contentid 로 접은 통합 목록. 실패하면 예외를 올린다."""
    today = _dt.date.today().strftime("%Y%m%d")

    # 90일 전부터 받아야 '이미 시작해서 아직 하는' 축제가 들어온다. eventStartDate
    # 는 시작일 하한이라 오늘로 잡으면 진행 중인 것이 통째로 빠진다.
    since = (_dt.date.today() - _dt.timedelta(days=90)).strftime("%Y%m%d")
    festivals, _ = tourapi.items(
        "searchFestival2", eventStartDate=since, lDongRegnCd=tourapi.SEOUL, arrange="A"
    )
    festivals = [r for r in festivals if (r.get("eventenddate") or "") >= today]

    standing, _ = tourapi.items(
        "areaBasedList2", lDongRegnCd=tourapi.SEOUL, lclsSystm1="EV", arrange="Q"
    )

    merged: dict[str, dict] = {}
    for row in festivals + standing:  # 축제가 먼저다 — 날짜가 있는 쪽을 남긴다
        cid = row.get("contentid")
        if cid and cid not in merged:
            merged[cid] = _to_event(row)
    return list(merged.values())


@app.post("/events")
def get_events(req: EventsRequest):
    """한국관광공사 TourAPI 로 조회한 서울의 축제·공연·행사.

    Returns a list of {name, date, venue, description, image_url, landing_url}.
    On ANY failure returns [] (never 500) — Flutter's empty state handles it."""
    cached = _EVENTS_CACHE.get("all")
    try:
        if not (cached and (_time.time() - cached[0]) < _EVENTS_TTL):
            events = _fetch_events()
            if not events:
                # 공사 쪽이 0건을 준 것. 지난 목록을 지우느니 그대로 두는 편이 낫다.
                print("[events] TourAPI returned 0 rows")
                return _chip_filter(cached[1], req.category) if cached else []
            _EVENTS_CACHE["all"] = cached = (_time.time(), events)
        return _chip_filter(cached[1], req.category)
    except Exception as e:
        print(f"[events] {req.category!r} failed: {type(e).__name__}: {tourapi.redact(e)}")
        return _chip_filter(cached[1], req.category) if cached else []


def _chip_filter(events: list[dict], category: str | None) -> list[dict]:
    """칩 하나로 통합본을 거른다. 'All' 과 모르는 라벨은 전체."""
    code = _EV_CHIP.get((category or "").strip())
    rows = [e for e in events if e["_chip"] == code] if code else events
    return [{k: v for k, v in e.items() if k != "_chip"} for e in rows]


class EventDetailRequest(BaseModel):
    # /events 가 돌려준 contentid. 공사 API 의 키라 숫자 문자열이다.
    contentid: str = Field(..., min_length=1, max_length=20)


# ponytail: _COMMON_CACHE 와 같은 모양 — 모듈 dict, 24시간 TTL. 공사 데이터는
# 하루 1회 갱신이라 그 이상 잡을 이유가 없고, 재시작하면 비어도 한 건 다시
# 받는 비용이 2회 호출이라 괜찮다. 탭한 행사만 받으므로 80건을 미리 받지 않는다.
_EVENT_DETAIL_CACHE: dict[str, tuple[float, dict]] = {}
_EVENT_DETAIL_TTL = 24 * 3600

# 서울 행사는 전건 contenttypeid=85 다. detailIntro2 는 타입별로 응답 스키마가
# 달라서 contentTypeId 를 같이 보내야 한다.
_EVENT_CONTENT_TYPE = "85"


def _first_url(raw: str) -> str:
    """공사의 homepage 필드에서 열 수 있는 URL 하나.

    스킴 없이 호스트만 온다('www.kh.or.kr'). 그대로 url_launcher 에 넘기면
    상대 경로로 읽혀 열리지 않는다. 줄이 여러 개인 것도 섞여 있다
    ('ssaf.or.kr/index\nInstagram: www.instagram.com/...') — 첫 줄만 쓴다.
    """
    line = raw.strip().splitlines()[0].strip() if raw.strip() else ""
    if line.startswith(("http://", "https://")):
        return line  # 라벨 제거보다 먼저 — 안 그러면 'https:' 가 라벨로 잘린다
    line = _re.sub(r"^[A-Za-z ]{,12}:\s*", "", line)  # 'Website: ' 같은 라벨
    return f"https://{line}" if line else ""


def _event_detail(cid: str) -> dict:
    """detailCommon2 + detailIntro2 를 합친 한 건. 실패는 삼키고 빈 칸을 남긴다.

    실측(표본 14건) 기준 채움률이 고르지 않다 — eventplace 13, overview 7,
    playtime 7. 그래서 빈 필드는 빼지 않고 빈 문자열로 내려보내고, 시트가
    '없음' 문구로 떨어뜨린다. 여기서 예외를 올리면 공사 API 장애가 곧 화면
    장애가 된다.
    """
    hit = _EVENT_DETAIL_CACHE.get(cid)
    if hit and (_time.time() - hit[0]) < _EVENT_DETAIL_TTL:
        return hit[1]

    common: dict = {}
    intro: dict = {}
    try:
        rows, _ = tourapi.items("detailCommon2", contentId=cid)
        common = rows[0] if rows else {}
    except Exception as e:
        print(f"[event-detail] detailCommon2({cid}) failed: "
              f"{type(e).__name__}: {tourapi.redact(e)}")
    try:
        rows, _ = tourapi.items(
            "detailIntro2", contentId=cid, contentTypeId=_EVENT_CONTENT_TYPE)
        intro = rows[0] if rows else {}
    except Exception as e:
        print(f"[event-detail] detailIntro2({cid}) failed: "
              f"{type(e).__name__}: {tourapi.redact(e)}")

    def pick(src: dict, key: str) -> str:
        return (src.get(key) or "").strip()

    detail = {
        "overview": pick(common, "overview"),
        "homepage": _first_url(common.get("homepage") or ""),
        "tel": pick(common, "tel"),
        # 공사가 주는 영문 장소명. 목록의 addr1/addr2 휴리스틱보다 한글이 덜 샌다.
        "place": pick(intro, "eventplace"),
        "hours": pick(intro, "playtime"),
        "fee": pick(intro, "usetimefestival"),
        "program": pick(intro, "program"),
        "age_limit": pick(intro, "agelimit"),
    }
    # 두 호출이 다 빈손이면 캐시에 넣지 않는다 — 일시적 장애를 24시간 굳히게 된다.
    if any(detail.values()):
        _EVENT_DETAIL_CACHE[cid] = (_time.time(), detail)
    return detail


@app.post("/event-detail")
def get_event_detail(req: EventDetailRequest):
    """한 행사의 상세. 카드를 탭할 때만 불린다.

    Returns {overview, homepage, tel, place, hours, fee, program, age_limit}
    — 값이 없는 필드는 빈 문자열. 절대 500 을 내지 않는다.

    sponsor1(주최)은 뺐다. 표본 16건 중 10건이 한글이라 영문 UI 에 그대로
    못 올린다. 거르느니 안 쓰는 편이 낫다 — 여행자가 볼 이유도 적다."""
    try:
        return _event_detail(req.contentid)
    except Exception as e:
        print(f"[event-detail] {req.contentid!r} failed: "
              f"{type(e).__name__}: {tourapi.redact(e)}")
        return {}


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
@_one_turn_per_session
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


_MICHELIN_GRADE_EN = {
    "3스타": "3 Michelin Stars", "2스타": "2 Michelin Stars", "1스타": "1 Michelin Star",
    "빕구르망": "Bib Gourmand", "Selected": "Michelin Selected",
}


def _closed_warning(weekday: str, day_num: int) -> str:
    """Shown as-is in the swap sheet, so it is written for the traveller.

    Both candidate paths (Michelin and pool/Google) emit this, and keeping the
    wording in one place stops them drifting apart.
    """
    return f"Usually closed on {weekday}s — Day {day_num} is a {weekday}"


def _itinerary_poi(state: dict, day_num: int, slot_index: int, name: str) -> Optional[dict]:
    """The POI the traveller tapped, read off the itinerary itself.

    Not build_candidate_pool: a locked meal is inserted by the validator from
    meal_slots, so it appears in neither retrieved_courses nor google_supplement
    and a pool lookup returns None for exactly the POIs this endpoint most needs
    coordinates and a meal_slot for. Matched by name first, since slot_index
    comes from the client's own list ordering; index is the fallback.
    """
    days = ((state.get("itinerary") or {}).get("days")) or []
    day = next((d for d in days if d.get("day") == day_num), None)
    if not day:
        return None
    pois = day.get("pois") or []
    key = _re.sub(r"\s+", " ", str(name or "").strip().lower())
    for poi in pois:
        if _re.sub(r"\s+", " ", str(poi.get("name") or "").strip().lower()) == key:
            return poi
    return pois[slot_index] if 0 <= slot_index < len(pois) else None


def _leave_on_thread(thread_id: str, state: dict, candidates: list[dict]) -> None:
    """Park offered candidates on the thread so /revalidate can swap them in.

    apply_slot_edits looks the traveller's pick up in build_candidate_pool(state)
    -- retrieved_courses + planning_context.google_supplement -- and silently
    keeps the original stop when it misses. Candidates from Google's fallback
    and from restaurant.json are in neither, so both paths have to leave their
    offer here first. candidate_from_google reads poi_name/name either way, so
    response-shaped and pool-shaped rows both survive the round trip.
    """
    ctx = state.get("planning_context") or {}
    _graph.update_state(_config(thread_id), {"planning_context": {
        **ctx,
        "google_supplement": [*(ctx.get("google_supplement") or []), *candidates],
    }})


@app.post("/swap-candidates")
@_one_turn_per_session
def swap_candidates(req: SwapCandidatesRequest):
    """current_poi와 같은 슬롯 성격(식당/카페 등)의 대체 후보 최대 3개를,
    같은 area 안에서 찾아 반환한다. 각 후보에는 사전 검증 경고가 붙는다 —
    특히 closed_weekday와 이 day의 실제 요일(trip_start_date + day로 계산)이
    겹치면 "화요일 정기휴무" 식으로 미리 알려준다.

    is_generic_activity/is_transit_marker/requires_review로 걸러진 POI는
    build_candidate_pool 단계에서 이미 후보 풀에 없으므로 여기서 따로 걸러낼
    필요가 없다."""
    from critic_repair import (
        build_candidate_pool, candidates_for_area, google_fallback_candidates, normalize_text,
    )
    from date_utils import weekday_for_day
    from planner import GOOGLE_PLACES_API_KEY
    import meal_slots

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

        # Computed here rather than after the candidate search: the Michelin
        # branch below needs it to flag a restaurant that is shut that day.
        weekday = None
        trip_start_date = state.get("trip_start_date")
        if trip_start_date:
            try:
                weekday = weekday_for_day(trip_start_date, req.day, lang="en")
            except (ValueError, TypeError):
                weekday = None  # 폴백 -- 요일 경고만 생략, 나머지는 계속 진행

        # A restaurant slot swaps to Michelin only, nearest first. The pool's
        # restaurants are Google's prominence ranking of whoever is near the
        # area centre; restaurant.json is the same curated set every locked meal
        # already comes from, so a swap stays within the quality bar the day was
        # built to. Falls through to the pool/Google path below when nothing
        # Michelin is within SWAP_RADIUS_KM, so the sheet is never empty.
        here = _itinerary_poi(state, req.day, req.slot_index, req.current_poi) or current or {}

        # A diet traveller only sees Michelin rows of that diet's cuisines. Halal
        # has none verified, so its sheet goes straight to the pool/Google path.
        diet = state.get("diet")
        cuisines = meal_slots.DIET_RULES[diet]["cuisines"] if diet else None
        if (normalize_text(req.current_poi_type or (current or {}).get("type")) == "restaurant"
                and cuisines != ()):
            lat, lng = here.get("lat"), here.get("lng")
            if lat is None or lng is None:
                print(f"[swap michelin] {req.current_poi!r} has no coordinates -- pool path")
            else:
                hits = meal_slots.nearest_michelin(
                    lat=float(lat), lng=float(lng), weekday=weekday,
                    meal_slot=here.get("meal_slot"),
                    exclude_names=tuple(
                        [req.current_poi, *req.excluded_ids]
                    ),
                    cuisines=cuisines,
                )
                if hits:
                    michelin = [{
                        "poi_name": r.get("name"),
                        "poi_type": "restaurant",
                        "address": r.get("street"),
                        "lat": r.get("lat"),
                        "lng": r.get("lon"),
                        # Michelin rows carry a grade, not a 5-point score.
                        "rating": None,
                        "grade": _MICHELIN_GRADE_EN.get(r.get("grade"), r.get("grade")),
                        "distance_km": r.get("distance_km"),
                        "warnings": (
                            [_closed_warning(weekday, req.day)]
                            if r.get("closed") else
                            ["Opening hours unknown — worth checking before you go"]
                            if r.get("closed") is None else []
                        ),
                    } for r in hits]
                    _leave_on_thread(thread_id, state, michelin)
                    return {"candidates": michelin}
                print(f"[swap michelin] no Michelin within "
                      f"{meal_slots.SWAP_RADIUS_KM}km of {req.current_poi!r} -- pool path")

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
            # From the itinerary, not the pool: build_candidate_pool holds
            # retrieved_courses + google_supplement, so a locked meal (inserted by
            # the validator from meal_slots) and anything the LLM wrote in itself
            # are both absent from it. Reading coordinates off `current` alone
            # meant the fallback silently skipped for exactly those POIs -- and a
            # locked meal is the one a traveller is most likely to swap.
            fallback_lat = here.get("lat")
            fallback_lng = here.get("lng")
            if fallback_lat is None or fallback_lng is None:
                print(
                    f"[swap fallback] current_poi {req.current_poi!r} has no known "
                    "coordinates (not in itinerary or pool) -- skipping Google fallback"
                )
            elif not GOOGLE_PLACES_API_KEY:
                print("[swap fallback] GOOGLE_PLACES_API_KEY 없음 -- 폴백 생략")
            else:
                filtered = google_fallback_candidates(
                    lat=fallback_lat, lng=fallback_lng, place_type=type_hint,
                    exclude=exclude, api_key=GOOGLE_PLACES_API_KEY,
                )
                if filtered:
                    _leave_on_thread(thread_id, state, filtered)

        rated = sorted(
            (i for i in filtered if i.get("rating") is not None),
            key=lambda i: -i["rating"],
        )
        unrated = [i for i in filtered if i.get("rating") is None]
        ranked = (rated + unrated)[:3]

        candidates = []
        for item in ranked:
            warnings: list[str] = []
            closed = item.get("closed_weekday") or []
            if weekday and weekday in closed:
                warnings.append(_closed_warning(weekday, req.day))
            if item.get("is_area_type"):
                warnings.append("This is an area or street, not a single venue")

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
    # `python api.py` — 공사 API 를 실제로 쳐서 통합·칩 필터를 확인한다.
    rows = _fetch_events()
    assert rows, "TourAPI returned 0 events"
    assert len({r["landing_url"] for r in rows}) == len(rows), "contentid dedupe failed"

    chips = {c: len(_chip_filter(rows, c)) for c in ("All", *_EV_CHIP)}
    assert chips["All"] == len(rows), "All chip must not filter"
    assert sum(v for k, v in chips.items() if k != "All") == len(rows), "chips must partition"
    assert "_chip" not in rows[0] or "_chip" not in _chip_filter(rows, "All")[0], "_chip leaked"

    # 탭이 실제로 열리는지. 모양만 맞고 죽어 있던 적이 있어서 한 건 쳐 본다.
    import httpx as _httpx
    _probe = _httpx.get(rows[0]["landing_url"], timeout=12, follow_redirects=True,
                        headers={"User-Agent": "Mozilla/5.0"})
    assert _probe.status_code == 200, (
        f"landing_url dead ({_probe.status_code}): {rows[0]['landing_url']}")

    _detail = _event_detail(rows[0]["contentid"])
    print(f"[selfcheck] landing 200 · detail filled="
          f"{sum(1 for v in _detail.values() if v)}/{len(_detail)}")

    dated = [r for r in rows if r["date"]]
    print(f"[selfcheck] OK — {len(rows)} events {chips}; dated={len(dated)}")
    print(f"             first = {rows[0]['name']!r} / {rows[0]['date']!r}")
