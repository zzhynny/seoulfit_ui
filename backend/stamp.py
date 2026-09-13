"""stamp.py — one AI-illustrated journey stamp per trip.

The recap card's visited/partial/empty state is drawn natively (paw-stamp
overlays in trip_recap_screen.dart); this module only repaints the background
so the traveller's real route shows up in it: every visited place, grouped by
day, in the order visited, laid along the railway track.

Pipeline: POST /trip/checkin with generate_stamp -> request_stamp (dedupe,
mark generating) -> BackgroundTasks generate_stamp -> OpenAI images.edit on the
static base template -> backend/stamps/{trip_id}.png. The recap polls
GET /trip/stamp/{trip_id} (stamp_status) to know when to show it.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading

from openai import OpenAI

logger = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
_TEMPLATE_PATH = os.path.join(_HERE, "assets", "journey_template.png")
_STAMPS_DIR = os.path.join(_HERE, "stamps")

_client: OpenAI | None = None

# trip_id is chosen by an unauthenticated client and becomes a file name, so no
# dots or slashes: "../x" must never reach os.path.join.
_TRIP_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")

# ponytail: in-process state. A restart forgets "generating"/"failed" and the
# dedupe memory (status falls back to the file on disk, and one repeat
# generation becomes possible). Move to the DB if this ever runs multi-worker.
_lock = threading.Lock()
_state: dict[str, str] = {}          # trip_id -> "generating" | "failed"
_last_route: dict[str, list] = {}    # trip_id -> route last requested


def valid_trip_id(trip_id: str) -> bool:
    return bool(_TRIP_ID_RE.fullmatch(trip_id or ""))


def visited_by_day(itinerary: dict, days: dict) -> list[tuple[int, list[str]]]:
    """(day, visited place names in plan order) for every day with a visit.

    `planned` and `visited` both hold POI display names (Flutter's
    TripActivity.id is the POI name), so no lookup is needed.
    """
    planned: dict = itinerary.get("planned") or {}
    route = []
    for day_str in sorted(planned, key=int):
        visited = set((days.get(day_str) or {}).get("visited") or [])
        stops = [name for name in planned[day_str] or [] if name in visited]
        if stops:
            route.append((int(day_str), stops))
    return route


_TRANSLATION_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _label_name(name: str) -> str:
    """Drops a trailing bracketed translation ("Bukchon Hanok Village
    (북촌한옥마을)" -> "Bukchon Hanok Village"): shorter labels come out spelled
    right more often. A name that is nothing but brackets is kept whole."""
    return _TRANSLATION_RE.sub("", name) or name


_HANGUL_RE = re.compile(r"[ᄀ-ᇿ㄰-㆏가-힣]")

# Revised Romanization, syllable by syllable. No sound-change rules (갤러리 ->
# "gaelreori", not "gaelleori") — it's only the fallback when translation fails.
_RR_INITIALS = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
_RR_VOWELS = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i"]
_RR_FINALS = ["", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l", "p", "l", "m", "p", "p", "t", "t", "ng", "t", "t", "k", "t", "p", "t"]


def _romanize(text: str) -> str:
    out = []
    for ch in text:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out.append(_RR_INITIALS[code // 588] + _RR_VOWELS[(code % 588) // 28] + _RR_FINALS[code % 28])
        else:
            out.append(ch)
    return " ".join(word.capitalize() for word in "".join(out).split())


def english_labels(names: list[str], translate) -> dict[str, str]:
    """name -> an English-only label for the stamp. No Korean ever reaches it.

    English names pass through (minus a bracketed translation); a mixed name
    keeps its English part ("모드곤 MODGONE" -> "MODGONE"); Korean-only names go
    to `translate` in one batch. A failed, missing, or still-Korean translation
    falls back to romanization.
    """
    labels: dict[str, str] = {}
    pending: list[str] = []
    for name in names:
        base = _label_name(name)
        if not _HANGUL_RE.search(base):
            labels[name] = base
            continue
        latin = " ".join(_HANGUL_RE.sub(" ", base).split())
        if re.search(r"[A-Za-z]", latin):
            labels[name] = latin
        else:
            pending.append(name)
    if pending:
        try:
            translated = translate([_label_name(n) for n in pending]) or {}
        except Exception:
            logger.exception("stamp: translating %d place names failed", len(pending))
            translated = {}
        for name in pending:
            base = _label_name(name)
            label = str(translated.get(base) or "").strip()
            labels[name] = label if label and not _HANGUL_RE.search(label) else _romanize(base)
    return labels


def _translate_with_gemini(names: list[str]) -> dict:
    """One JSON-mode Gemini call: Korean place names -> short English map labels."""
    from google import genai

    prompt = (
        "These are names of places in Seoul, to be printed as short labels on an "
        "English travel map. For each, give the name an English-speaking visitor "
        "would recognise: keep brand names, translate descriptive words, and "
        "romanize proper nouns. Use English letters only, no Korean. Return a JSON "
        "object mapping each input string exactly to its label.\n"
        + json.dumps(names, ensure_ascii=False)
    )
    response = genai.Client(api_key=os.getenv("GEMINI_API_KEY")).models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config={"response_mime_type": "application/json"},
    )
    data = json.loads(response.text or "{}")
    return data if isinstance(data, dict) else {}


# Seam for tests, like _client.
_translate = _translate_with_gemini


def build_prompt(
    route: list[tuple[int, list[str]]],
    types: dict | None = None,
    labels: dict | None = None,
) -> str:
    """The route, numbered in order under each day, for the model to lay along
    the track with a number-and-name label beside each building.

    States the exact count and each place's type: bare names like "ANAM" give
    the model nothing to draw, and without a count it merges or drops places.
    Types sit in square brackets so they aren't mistaken for label text. The
    labels can still come out misspelled — the recap's list is the exact record.
    """
    types = types or {}
    labels = labels or {}
    total = sum(len(stops) for _, stops in route)
    lines: list[str] = []
    n = 0
    for day, stops in route:
        lines.append(f"Day {day}:")
        for name in stops:
            n += 1
            kind = str(types.get(name) or "").strip()
            label = labels.get(name) or _label_name(name)
            lines.append(f"{n}. {label}" + (f" [{kind}]" if kind else ""))
    listing = "\n".join(lines)
    return (
        "Using the reference image as the base, keep its watercolor illustration "
        "style, color palette, the railway track, the green flag at the start "
        "and the tram at the end. The track is the traveller's route. Along it, "
        f"from the flag to the tram, draw exactly {total} small illustrated "
        "buildings or scenes: one for each place below, in this exact order, "
        "each clearly separate and showing what kind of place it is (its type "
        "is in square brackets). Remove every other landmark or building from "
        "the reference image, so each one on the map is one of these places. "
        "Beside each building, next to the track, write a small, clearly legible "
        f"label with its number and name exactly as spelled below: exactly {total} "
        f"labels in all, numbered 1 to {total}, where each number appears exactly "
        "once. Label nothing else, never write the square-bracketed type, and add "
        "no other text:\n"
        f"{listing}"
    )


def request_stamp(trip_id: str, itinerary: dict, days: dict) -> bool:
    """Marks the trip's stamp as generating; True when one should be painted.

    False when nothing was visited, or when these exact visits were already
    requested and didn't fail — completing check-in again must not pay twice.
    """
    route = visited_by_day(itinerary, days)
    if not route:
        return False
    with _lock:
        if _last_route.get(trip_id) == route and _state.get(trip_id) != "failed":
            return False
        _last_route[trip_id] = route
        _state[trip_id] = "generating"
    return True


def stamp_status(trip_id: str) -> dict:
    """generating | ready (+version: file mtime in ms, for cache-busting) |
    failed | none. A failed regeneration still reports the previous stamp."""
    with _lock:
        state = _state.get(trip_id)
    if state == "generating":
        return {"status": "generating"}
    path = os.path.join(_STAMPS_DIR, f"{trip_id}.png")
    if os.path.exists(path):
        return {"status": "ready", "version": os.stat(path).st_mtime_ns // 1_000_000}
    return {"status": state or "none"}


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for stamp generation")
        _client = OpenAI(api_key=api_key)
    return _client


def generate_stamp(trip_id: str, itinerary: dict, days: dict) -> None:
    """Paint and save the trip's stamp. Best-effort: any failure is logged,
    reported as "failed", and leaves an existing stamp file untouched."""
    route = visited_by_day(itinerary, days)
    if not route:
        return
    try:
        labels = english_labels([name for _, stops in route for name in stops], _translate)
        with open(_TEMPLATE_PATH, "rb") as f:
            result = _get_client().images.edit(
                model="gpt-image-2.5-flare",
                image=f,
                prompt=build_prompt(route, itinerary.get("types"), labels),
                quality="medium",
                size="1024x1536",  # portrait, closest to the 345x444 recap card
            )
        image_bytes = base64.b64decode(result.data[0].b64_json)
        os.makedirs(_STAMPS_DIR, exist_ok=True)
        out_path = os.path.join(_STAMPS_DIR, f"{trip_id}.png")
        tmp_path = out_path + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(image_bytes)
        os.replace(tmp_path, out_path)  # atomic: never serves a half-written file
        with _lock:
            _state.pop(trip_id, None)
    except Exception:
        logger.exception("stamp: generate_stamp failed for trip_id=%s", trip_id)
        with _lock:
            _state[trip_id] = "failed"
