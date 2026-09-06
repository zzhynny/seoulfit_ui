"""
lens.py — SeoulFit Lens router (merged from camera_web_app/backend/main.py).

Pipeline: Gemini Vision → seoul.json RAG → Gemini narration.
Mounted into api.py via app.include_router(router).
"""

from __future__ import annotations

import os
import json
import re

from fastapi import APIRouter, UploadFile, File, HTTPException
from google import genai
from google.genai import types

# ──────────────────────────────────────────
# Gemini client — reuses GEMINI_API_KEY already loaded by api.py
# ──────────────────────────────────────────
_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not _GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is required for the lens router")

_gemini_client = genai.Client(api_key=_GEMINI_API_KEY)
_GEMINI_MODEL = "gemini-2.5-flash"

# ──────────────────────────────────────────
# Local Seoul RAG dataset
# ──────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SEOUL_DATA_PATH = os.path.join(_HERE, "dataset", "seoul.json")
_KOREAN_SLUG_RE = re.compile(r"^https://korean\.visitseoul\.net/attractions/([^/?]+)")


def _normalize(s: str) -> str:
    return re.sub(r"[\W_]+", "", (s or "").lower(), flags=re.UNICODE)


def _load_seoul_dataset() -> list[dict]:
    with open(_SEOUL_DATA_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    rows = raw.get("DATA", []) if isinstance(raw, dict) else (raw or [])
    out: list[dict] = []
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
        out.append(enriched)
    return out


_SEOUL_ROWS: list[dict] = _load_seoul_dataset()
print(f"[lens] seoul.json: loaded {len(_SEOUL_ROWS)} Korean entries")

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
async def _identify_with_gemini(image_bytes: bytes, mime_type: str) -> dict:
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
                max_output_tokens=1024,
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

    best = None
    best_diff = None
    for _, key in norm_candidates:
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


async def _translate_public_data(public_data: dict, post_sn: int | None) -> dict:
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


# ══════════════════════════════════════════
# STEP 3 — English narration
# ══════════════════════════════════════════
async def _generate_english_guide(
    landmark_info: dict,
    public_data: dict,
    has_public_data: bool,
) -> str:
    if has_public_data and public_data:
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

        data_context = (
            "\n\n[Seoul Official Public Data — Verified Facts]\n"
            + "\n".join(facts)
            + "\nWeave these verified facts naturally into your narration."
        )
        accuracy_warning = ""
    else:
        data_context = ""
        accuracy_warning = (
            " (Note: No official public data was found — "
            "this narration is based on general knowledge and accuracy cannot be fully guaranteed.)"
        )

    system_prompt = (
        "You are an expert audio guide narrator for foreign tourists visiting Seoul, South Korea. "
        "Your mission is to make the city come alive — NOT to list facts.\n\n"
        "Craft a narration that answers: 'Why does this place matter? Why should I care right now?'\n\n"
        "Structure:\n"
        "1. Hook — a vivid moment in history, a surprising fact, or a sensory detail\n"
        "2. Significance — what happened here, who built this, what it meant to Koreans\n"
        "3. Present connection — what the visitor can observe right now in front of them\n"
        "4. Memorable close — one detail that will stick with them\n\n"
        "Rules:\n"
        "- 4 to 5 sentences total — vivid and rich, not dense\n"
        "- Warm storytelling tone, like a knowledgeable local friend\n"
        "- No generic openers like 'Welcome to' or 'This place is famous for'\n"
        "- Natural spoken rhythm — written to be heard while walking"
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
                max_output_tokens=1024,
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
async def analyze_landmark(file: UploadFile = File(...)):
    content_type = _resolve_content_type(file)
    allowed = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
    if content_type not in allowed:
        raise HTTPException(400, f"Unsupported image type: {content_type}")

    image_bytes = await file.read()
    if len(image_bytes) == 0:
        raise HTTPException(400, "Empty file")
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(400, "Image larger than 10 MB")

    landmark_info = await _identify_with_gemini(image_bytes, content_type)

    candidates = [landmark_info["name_korean"]] + list(
        landmark_info.get("aliases_korean") or []
    )
    matched_row, has_public_data = _lookup_in_seoul_json(candidates)
    public_data = _extract_fields(matched_row) if matched_row else {}
    post_sn = matched_row.get("post_sn") if matched_row else None

    public_data_en = (
        await _translate_public_data(public_data, post_sn)
        if has_public_data
        else {}
    )
    # Narrate from the English-translated facts, not the raw Korean, so no
    # Korean address/hours/station names leak into the guide text.
    description = await _generate_english_guide(
        landmark_info, public_data_en or public_data, has_public_data
    )

    return {
        "name_korean":    landmark_info["name_korean"],
        "name_english":   landmark_info["name_english"],
        "confidence":     landmark_info["confidence"],
        "category":       landmark_info["category"],
        "description":    description,
        "data_verified":  has_public_data,
        "data_source":    "seoul.json (korean.visitseoul.net)" if has_public_data else "none",
        "public_info":    public_data,
        "public_info_en": public_data_en,
    }


@router.get("/lens/health")
async def lens_health():
    return {"status": "ok", "seoul_rows": len(_SEOUL_ROWS)}
