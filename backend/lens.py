"""
lens.py — SeoulFit Lens router (merged from camera_web_app/backend/main.py).

Pipeline: Gemini Vision → seoul.json RAG (Tavily web fallback) → Gemini
podcast narration. /lens/speech turns that narration into an OpenAI TTS mp3.
Mounted into api.py via app.include_router(router).
"""

from __future__ import annotations

import hashlib
import os
import json
import re
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from poi_text import _web_search

# ──────────────────────────────────────────
# Gemini client — reuses GEMINI_API_KEY already loaded by api.py
# ──────────────────────────────────────────
_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not _GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is required for the lens router")

_gemini_client = genai.Client(api_key=_GEMINI_API_KEY)
_GEMINI_MODEL = "gemini-3.8-flash"
_TTS_MODEL = "gpt-4o-mini-tts-2025-12-15"
_TTS_VOICE = "marin"

# api.py serves this dir at /static/lens_audio. Files are named by the text's
# hash, so replaying or rescanning the same place never pays for TTS twice.
AUDIO_DIR = Path(__file__).resolve().parent / "lens_audio"
AUDIO_DIR.mkdir(exist_ok=True)

# ──────────────────────────────────────────
# Local Seoul RAG dataset
# ──────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SEOUL_DATA_PATH = os.path.join(_HERE, "dataset", "seoul.json")
_KOREAN_SLUG_RE = re.compile(r"^https://korean\.visitseoul\.net/attractions/([^/?]+)")
_ANY_SLUG_RE = re.compile(r"^https://\w+\.visitseoul\.net/attractions/([^/?]+)")


def _normalize(s: str) -> str:
    return re.sub(r"[\W_]+", "", (s or "").lower(), flags=re.UNICODE)


def _join_keys(row: dict) -> list[tuple]:
    """Language-independent keys for pairing a Korean row with its English twin.

    post_sn does NOT match across languages and the slug only matches when
    visitseoul used a numeric id (149/475); for the rest the Korean slug is
    Hangul and the English one is romanized. The postal code plus the first
    two street numbers recovers most of the remainder.
    """
    keys: list[tuple] = []
    m = _ANY_SLUG_RE.match(row.get("post_url") or "")
    if m:
        keys.append(("slug", m.group(1)))
    addr = row.get("new_address") or row.get("address") or ""
    z = re.match(r"\s*(\d{5})", addr)
    if z:
        nums = re.findall(r"\d+", addr[z.end():])
        if nums:
            keys.append(("addr", z.group(1), tuple(nums[:2])))
    return keys


def _zip_of(row: dict) -> str:
    m = re.match(r"\s*(\d{5})", row.get("new_address") or row.get("address") or "")
    return m.group(1) if m else ""


def _phone_of(row: dict) -> str:
    d = re.sub(r"\D", "", row.get("cmmn_telno") or "")
    d = d[2:] if d.startswith("82") else d   # 영문 레코드는 국가번호를 붙인다
    d = d.lstrip("0")
    return d if len(d) >= 8 else ""


def _contradicts(kr: dict, en: dict) -> bool:
    """둘이 명백히 다른 장소인가.

    주소 키(우편번호+번지)는 같은 블록의 이웃 시설을 묶어버린다 — 반포대교
    야경이 세빛섬으로, 서울올림픽기념관이 백제어린이박물관으로 붙었다.
    양쪽에 다 있는 우편번호·전화번호가 어긋나면 그 페어는 버린다.
    """
    kz, ez = _zip_of(kr), _zip_of(en)
    if kz and ez and kz != ez:
        return True
    kp, ep = _phone_of(kr), _phone_of(en)
    # 한쪽이 상대의 접두사면 자릿수 잘림이지 다른 번호가 아니다.
    if kp and ep and not (kp.startswith(ep) or ep.startswith(kp)):
        return True
    return False


def _load_seoul_dataset() -> tuple[list[dict], int]:
    with open(_SEOUL_DATA_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    rows = raw.get("DATA", []) if isinstance(raw, dict) else (raw or [])

    # Index the English rows by join key, dropping any key that is ambiguous —
    # a wrong pairing would show the visitor another place's address.
    en_index: dict[tuple, list[dict]] = {}
    for r in rows:
        if not (r.get("post_url") or "").startswith("https://english"):
            continue
        for k in _join_keys(r):
            en_index.setdefault(k, []).append(r)

    out: list[dict] = []
    paired = 0
    for r in rows:
        url = (r.get("post_url") or "")
        if not url.startswith("https://korean"):
            continue
        m = _KOREAN_SLUG_RE.match(url)
        if not m:
            continue
        slug = m.group(1)
        enriched = dict(r)
        enriched["_slug"] = slug
        enriched["_slug_norm"] = _normalize(slug)
        enriched["_post_sj_norm"] = _normalize(r.get("post_sj") or "")
        for k in _join_keys(r):
            twin = en_index.get(k)
            if twin and len(twin) == 1 and not _contradicts(r, twin[0]):
                enriched["_en"] = twin[0]
                paired += 1
                break
        out.append(enriched)
    return out, paired


_SEOUL_ROWS, _SEOUL_EN_PAIRED = _load_seoul_dataset()
print(
    f"[lens] seoul.json: loaded {len(_SEOUL_ROWS)} Korean entries "
    f"({_SEOUL_EN_PAIRED} with official English)"
)

router = APIRouter(tags=["lens"])


# ──────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────
def _resolve_content_type(file: UploadFile) -> str:
    filename = (file.filename or "").lower()
    if filename.endswith(".png"):
        return "image/png"
    if filename.endswith(".jpg") or filename.endswith(".jpeg"):
        return "image/jpeg"
    if filename.endswith(".webp"):
        return "image/webp"
    if filename.endswith(".heic") or filename.endswith(".heif"):
        return "image/heic"
    ct = (file.content_type or "").lower()
    if ct in {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}:
        return ct
    return "image/jpeg"


# ══════════════════════════════════════════
# STEP 1 — Gemini Vision identification
# ══════════════════════════════════════════
def _identify_with_gemini(image_bytes: bytes, mime_type: str) -> dict:
    prompt_text = (
        "You are an expert guide for tourists visiting Seoul, South Korea. "
        "Analyze this image and identify whatever is shown — statues, monuments, "
        "palace buildings, city landmarks, gates, markets, streets, signs, parks, "
        "rivers, restaurants, shops, or any recognizable object or place in Seoul. "
        "Be specific: not just 'a statue' but 'Admiral Yi Sun-sin Statue at Gwanghwamun Square'.\n\n"
        "Respond with a JSON object in this exact shape:\n"
        "{\n"
        '  "name_korean": "광화문",\n'
        '  "name_english": "Gwanghwamun Gate",\n'
        '  "aliases_korean": ["경복궁", "광화문 광장"],\n'
        '  "confidence": 99,\n'
        '  "category": "Gate"\n'
        "}\n\n"
        "aliases_korean RULES (very important — used to look up the official "
        "Seoul tourism database keyed in Korean):\n"
        "- 1 to 4 Korean (Hangul) names this subject is known by.\n"
        "- ALWAYS include the parent complex if the subject is a part of one. "
        "Examples: photo of 광화문 → include '경복궁'. "
        "Photo of a hall at 창덕궁 → include '창덕궁'. "
        "Photo of a building inside 국립중앙박물관 → include '국립중앙박물관'.\n"
        "- Include common shorter / longer Korean variants (e.g. '청계천', '청계천 광장').\n"
        "- Hangul only, no English, no descriptions, no quotes within.\n"
        "- If you only know one good Korean name, return a list with just that one.\n\n"
        "category MUST be exactly one of these values:\n"
        "Palace, Temple, Gate, Statue, Monument, Museum, Tower, Bridge, "
        "Traditional Architecture, Modern Landmark, Historic Site, "
        "Park, Mountain, River, Stream, Garden, Nature, "
        "Cultural Venue, Theater, Art Gallery, Performance Hall, Entertainment, "
        "Restaurant, Cafe, Market, Food, Street Food, "
        "Shopping, Department Store, Mall, Shop, Other\n\n"
        "If truly unidentifiable: set confidence to 0, name_korean to '알 수 없음', "
        "name_english to 'Unknown', and aliases_korean to []."
    )

    try:
        response = _gemini_client.models.generate_content(
            model=_GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                prompt_text,
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                # Thinking tokens count against this budget; 1024 can truncate the JSON.
                max_output_tokens=4096,
            ),
        )

        raw_text = (response.text or "").strip()
        cleaned = re.sub(r"```(?:json)?", "", raw_text).replace("```", "").strip()

        try:
            result = json.loads(cleaned)
            raw_aliases = result.get("aliases_korean")
            if isinstance(raw_aliases, list):
                result["aliases_korean"] = [
                    str(a).strip() for a in raw_aliases if str(a).strip()
                ]
            elif isinstance(raw_aliases, str) and raw_aliases.strip():
                result["aliases_korean"] = [raw_aliases.strip()]
            else:
                result["aliases_korean"] = []
        except json.JSONDecodeError:
            result = {
                "name_korean": "알 수 없음",
                "name_english": "Unknown",
                "aliases_korean": [],
                "confidence": 0,
                "category": "Other",
            }

        return result

    except Exception as e:
        print(f"[lens] Gemini API error: {e}")
        return {
            "name_korean": "알 수 없음",
            "name_english": "Unknown",
            "aliases_korean": [],
            "confidence": 0,
            "category": "Other",
        }


# ══════════════════════════════════════════
# STEP 2 — Local seoul.json RAG
# ══════════════════════════════════════════
def _lookup_in_seoul_json(candidates: list[str]) -> tuple[dict | None, bool]:
    norm_candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for c in candidates:
        if not c:
            continue
        n = _normalize(c)
        if not n or n in seen:
            continue
        if c.strip().lower() == "unknown" or c.strip() == "알 수 없음":
            continue
        seen.add(n)
        norm_candidates.append((c, n))

    if not norm_candidates:
        return None, False

    for _, key in norm_candidates:
        for r in _SEOUL_ROWS:
            if r["_slug_norm"] == key or r["_post_sj_norm"] == key:
                return r, True

    # Candidate order is priority order: name_korean first, then aliases. The
    # vision prompt deliberately adds the parent complex as an alias (a photo
    # of 숭례문 includes 한양도성, the city-wall system it's part of), and that
    # alias can fuzzy-match some *other* wall landmark more tightly than the
    # subject's own name matches its own row. Picking one best match across
    # every candidate let that shorter, wrong-landmark match win. Instead,
    # score each candidate's own best match separately and take the first
    # candidate (highest priority) that matches anything at all.
    for _, key in norm_candidates:
        best = None
        best_diff = None
        for r in _SEOUL_ROWS:
            for field_name in ("_slug_norm", "_post_sj_norm"):
                fv = r[field_name]
                if not fv:
                    continue
                if fv in key or key in fv:
                    diff = abs(len(fv) - len(key))
                    if best_diff is None or diff < best_diff:
                        best_diff = diff
                        best = r
        if best is not None:
            return best, True

    return None, False


def _extract_fields(row: dict) -> dict:
    return {
        "name":        row.get("post_sj") or "",
        "address":     row.get("new_address") or row.get("address") or "",
        "hours":       row.get("cmmn_use_time") or "",
        "open_days":   row.get("cmmn_bsnde") or "",
        "closed_days": row.get("cmmn_rstde") or "",
        "subway":      row.get("subway_info") or "",
        "phone":       row.get("cmmn_telno") or "",
        "website":     row.get("cmmn_hmpg_url") or row.get("post_url") or "",
        "tags":        row.get("tag") or "",
    }


# ──────────────────────────────────────────
# Korean public_info → English translation (memoized per post_sn)
# ──────────────────────────────────────────
_TRANSLATION_CACHE: dict[int, dict] = {}
_TRANSLATABLE_KEYS = ("address", "hours", "open_days", "closed_days", "subway", "tags")


def _translate_public_data(public_data: dict, post_sn: int | None) -> dict:
    if not public_data:
        return {}

    if post_sn is not None and post_sn in _TRANSLATION_CACHE:
        return _TRANSLATION_CACHE[post_sn]

    # Collapse whitespace (esp. the \r\n in multi-line `hours`) to single
    # spaces first — raw newlines make Gemini echo them into its JSON string
    # values, producing "Unterminated string" and falling back to Korean.
    payload = {
        k: re.sub(r"\s+", " ", str(public_data.get(k, "") or "")).strip()
        for k in _TRANSLATABLE_KEYS
    }
    if not any(v.strip() for v in payload.values() if isinstance(v, str)):
        return {**public_data}

    translation_prompt = (
        "Translate the following Korean tourist-information fields into natural, "
        "concise English suitable for a foreign visitor.\n\n"
        "Rules:\n"
        "- Keep numeric formats untouched: times like '10:00 ~ 18:00', 5-digit postal codes, phone numbers.\n"
        "- Addresses: romanize street/district names (e.g. '종로구' -> 'Jongno-gu', '사직로' -> 'Sajik-ro'). "
        "Keep the postal code at the start.\n"
        "- Subway: translate '지하철 3호선 안국역 1번 출구' -> 'Subway Line 3, Anguk Station, Exit 1'.\n"
        "- Tags: keep as a single comma-separated English string.\n"
        "- If a field is empty or just whitespace, return an empty string for it.\n\n"
        "Return ONLY a JSON object with the same keys.\n\n"
        f"Input:\n{json.dumps(payload, ensure_ascii=False)}"
    )

    try:
        response = _gemini_client.models.generate_content(
            model=_GEMINI_MODEL,
            contents=[translation_prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                # gemini-2.5-flash spends part of this budget on thinking tokens;
                # 1024 truncated the JSON mid-string on full records (long hours +
                # 14 tags) → JSONDecodeError → Korean fallback. 4096 clears it.
                max_output_tokens=4096,
            ),
        )
        raw = (response.text or "").strip()
        cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
        translated_raw = json.loads(cleaned)
        if not isinstance(translated_raw, dict):
            raise ValueError("translation response was not a JSON object")
        translated = {
            k: str(translated_raw.get(k, "") or "").strip()
            for k in _TRANSLATABLE_KEYS
        }
    except Exception as e:
        print(f"[lens] translation failed, returning Korean originals: {e}")
        translated = {k: payload[k] for k in _TRANSLATABLE_KEYS}

    merged = {**public_data, **translated}

    if post_sn is not None:
        _TRANSLATION_CACHE[post_sn] = merged

    return merged


# ──────────────────────────────────────────
# No seoul.json match → Tavily web search fills the same fields
# ──────────────────────────────────────────
def _web_public_data(landmark_info: dict) -> dict:
    """English public_info fields from the web; "" for anything it doesn't state."""
    name_en = landmark_info.get("name_english") or ""
    if not os.getenv("TAVILY_API_KEY") or not landmark_info.get("confidence") or name_en == "Unknown":
        return {}

    try:
        web = _web_search(
            f"{name_en} {landmark_info.get('name_korean') or ''} Seoul address "
            "opening hours closed days nearest subway station"
        )
        if not web:
            return {}
        response = _gemini_client.models.generate_content(
            model=_GEMINI_MODEL,
            contents=[
                f"Web search results about '{name_en}' in Seoul:\n\n{web}\n\n"
                "Using ONLY those results, return a JSON object with exactly these "
                f"keys: {', '.join(_TRANSLATABLE_KEYS)}.\n"
                "- address: street address in English.\n"
                "- hours: opening hours, e.g. '09:00 ~ 18:00'.\n"
                "- open_days / closed_days: which days it opens / closes.\n"
                "- subway: nearest subway line, station and exit.\n"
                "- tags: 3-6 short comma-separated English keywords.\n"
                "Use an empty string for any field the results don't clearly state "
                "for this specific place. Never guess."
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                max_output_tokens=4096,
            ),
        )
        cleaned = re.sub(r"```(?:json)?", "", response.text or "").replace("```", "").strip()
        raw = json.loads(cleaned)
    except Exception as e:
        print(f"[lens] web fallback failed: {e}")
        return {}
    if not isinstance(raw, dict):
        return {}
    facts = {k: str(raw.get(k) or "").strip() for k in _TRANSLATABLE_KEYS}
    # Gemini sometimes says "N/A" despite being told to leave the field empty.
    facts = {k: "" if v.lower().rstrip(".") in {"n/a", "na", "none", "unknown", "-"} else v
             for k, v in facts.items()}
    return facts if any(facts.values()) else {}


# ══════════════════════════════════════════
# STEP 3 — English narration
# ══════════════════════════════════════════
def _generate_english_guide(
    landmark_info: dict,
    public_data: dict,
    source: str,
) -> str:
    """source: "official" (seoul.json), "web" (Tavily) or "none"."""
    if public_data:
        facts = []
        if public_data.get("address"):
            facts.append(f"Address: {public_data['address']}")
        if public_data.get("hours"):
            facts.append(f"Hours: {public_data['hours']}")
        if public_data.get("open_days"):
            facts.append(f"Open: {public_data['open_days']}")
        if public_data.get("closed_days"):
            facts.append(f"Closed: {public_data['closed_days']}")
        if public_data.get("subway"):
            facts.append(f"Access: {public_data['subway']}")
        if public_data.get("tags"):
            facts.append(f"Keywords: {public_data['tags']}")

        label = (
            "Seoul Official Public Data — Verified Facts" if source == "official"
            else "Facts Found on the Web"
        )
        data_context = (
            f"\n\n[{label}]\n"
            + "\n".join(facts)
            + "\nWeave the useful ones (hours, how to get there) in naturally; skip the rest."
        )
        accuracy_warning = ""
    else:
        data_context = ""
        accuracy_warning = (
            " (Note: no verified data was found — stick to well-known facts and "
            "don't state hours, prices or addresses.)"
        )

    system_prompt = (
        "You host a short travel podcast for foreign visitors to Seoul, South Korea. "
        "This episode is a single segment about the place the listener is standing "
        "in front of right now — make it come alive, don't recite facts.\n\n"
        "Shape:\n"
        "1. Cold open — a vivid hook: a moment in history, a surprising fact, a sensory detail\n"
        "2. The story — what happened here, who built it, why it mattered to Koreans\n"
        "3. Look around — what the listener can spot in front of them right now\n"
        "4. Sign-off — one memorable detail or a practical tip to leave them with\n\n"
        "Rules:\n"
        "- 130 to 180 words, one host speaking directly to 'you'\n"
        "- Conversational podcast voice: warm, curious, a little playful; contractions, "
        "short sentences, the odd rhetorical question\n"
        "- It will be read aloud by text-to-speech: plain prose only — no markdown, "
        "no headings, no emoji, no stage directions or [music] cues, no speaker labels\n"
        "- No generic openers like 'Welcome to' or 'This place is famous for'"
    )

    user_prompt = (
        f"Create an audio guide narration for a tourist standing in front of:\n"
        f"Name: {landmark_info['name_english']} ({landmark_info['name_korean']})\n"
        f"Category: {landmark_info['category']}"
        f"{data_context}"
        f"{accuracy_warning}"
    )

    try:
        response = _gemini_client.models.generate_content(
            model=_GEMINI_MODEL,
            contents=[user_prompt],
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=4096,
            ),
        )
        return (response.text or "").strip()
    except Exception as e:
        print(f"[lens] narration error: {e}")
        return "Audio guide temporarily unavailable. Please try again in a moment."


# ══════════════════════════════════════════
# Endpoint
# ══════════════════════════════════════════
@router.post("/analyze-landmark")
def analyze_landmark(file: UploadFile = File(...)):
    """사진 한 장 → Gemini Vision → seoul.json RAG → 영문 해설.

    async 가 아니다. 안에서 부르는 Gemini 호출 셋이 전부 동기라서, async def
    로 두면 그 8~12초 동안 이벤트 루프가 잡혀 서버가 /healthz 조차 응답하지
    못한다 — 심사위원 한 명이 렌즈를 쓰는 동안 나머지 전원이 멈춘다. 평범한
    def 이면 FastAPI 가 threadpool 로 돌려서 겹쳐 처리된다. 되돌리지 말 것.
    """
    content_type = _resolve_content_type(file)
    allowed = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
    if content_type not in allowed:
        raise HTTPException(400, f"Unsupported image type: {content_type}")

    image_bytes = file.file.read()
    if len(image_bytes) == 0:
        raise HTTPException(400, "Empty file")
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(400, "Image larger than 10 MB")

    landmark_info = _identify_with_gemini(image_bytes, content_type)

    candidates = [landmark_info["name_korean"]] + list(
        landmark_info.get("aliases_korean") or []
    )
    matched_row, has_public_data = _lookup_in_seoul_json(candidates)
    public_data = _extract_fields(matched_row) if matched_row else {}
    post_sn = matched_row.get("post_sn") if matched_row else None

    # visitseoul publishes its own English record for ~57% of these places.
    # When we have it, use it: it is the official wording, costs no Gemini
    # call, and cannot hallucinate an address. Translate only the rest.
    en_row = matched_row.get("_en") if matched_row else None
    if not has_public_data:
        public_data_en = _web_public_data(landmark_info)
        en_source = "web" if public_data_en else "none"
    elif en_row:
        public_data_en = {**public_data, **_extract_fields(en_row)}
        en_source = "visitseoul-en"
    else:
        public_data_en = _translate_public_data(public_data, post_sn)
        en_source = "gemini"
    # Narrate from the English-translated facts, not the raw Korean, so no
    # Korean address/hours/station names leak into the guide text.
    description = _generate_english_guide(
        landmark_info,
        public_data_en or public_data,
        "official" if has_public_data else en_source,
    )

    return {
        "name_korean":    landmark_info["name_korean"],
        "name_english":   landmark_info["name_english"],
        "confidence":     landmark_info["confidence"],
        "category":       landmark_info["category"],
        "description":    description,
        "data_verified":  has_public_data,
        "data_source":    (
            "seoul.json (korean.visitseoul.net)" if has_public_data
            else "web (Tavily)" if en_source == "web"
            else "none"
        ),
        "en_source":      en_source,
        "public_info":    public_data,
        "public_info_en": public_data_en,
    }


class SpeechRequest(BaseModel):
    # OpenAI's speech input limit.
    text: str = Field(min_length=1, max_length=4096)


def _synthesize(text: str) -> bytes:
    from openai import OpenAI

    response = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=60).audio.speech.create(
        model=_TTS_MODEL,
        voice=_TTS_VOICE,
        input=text,
        instructions=(
            "Speak like a warm, curious travel-podcast host talking to one listener: "
            "relaxed pace, natural pauses, a smile in your voice."
        ),
        response_format="mp3",
    )
    return response.content


# Seam for tests.
_tts = _synthesize


@router.post("/lens/speech")
def lens_speech(req: SpeechRequest):
    """Narration text → mp3 under /static/lens_audio. Sync for the same reason as above."""
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "Empty text")
    name = hashlib.sha256(text.encode("utf-8")).hexdigest()[:32] + ".mp3"
    path = AUDIO_DIR / name
    if not path.exists():
        if not os.getenv("OPENAI_API_KEY"):
            raise HTTPException(503, "OPENAI_API_KEY not configured")
        try:
            audio = _tts(text)
        except Exception as e:
            print(f"[lens] TTS failed: {e}")
            raise HTTPException(502, "Speech generation failed")
        print(f"[lens] TTS {_TTS_MODEL}: {len(text)} chars → {len(audio)} bytes")
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(audio)
        tmp.replace(path)
    return {"url": f"/static/lens_audio/{name}"}


@router.get("/lens/health")
async def lens_health():
    return {"status": "ok", "seoul_rows": len(_SEOUL_ROWS)}
