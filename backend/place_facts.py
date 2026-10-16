"""Google Places facts for the course POIs and Michelin restaurants, looked up
once offline (scripts/enrich_place_facts.py) and keyed by normalized name.

Each row is what evals/bench_verify.fact_for returns: Google `periods`,
`closed_permanently`, and Gemini labels read from Google's reviews
(english_support, cash_only, reservation_required, cultural_friction; 1/0/None).
A missing file or name gives {} -- every caller treats that as "unknown".
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

PATH = Path(__file__).resolve().parent / "dataset" / "place_facts.json"
# Google legacy periods number days from Sunday = 0.
_GOOGLE_DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


def key(name: str | None) -> str:
    """Same as evals/bench_metrics.normalize, which keyed the file."""
    return re.sub(r"[^0-9a-z가-힣]", "", (name or "").lower())


@lru_cache(maxsize=1)
def _all() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


# Hours looked up while planning, for stops the file doesn't cover (Google
# supplements found at request time). Kept for the process, misses included.
# ponytail: unbounded and never expires; a TTL if the server runs for weeks.
_live: dict[str, dict[str, Any]] = {}


def learn(name: str | None, periods: list[dict[str, Any]] | None) -> None:
    _live[key(name)] = {"found": True, "periods": periods}


def known(name: str | None) -> bool:
    """Looked up already, by the offline script or at runtime (hit or miss)."""
    k = key(name)
    return k in _live or k in _all()


def fact(name: str | None) -> dict[str, Any]:
    k = key(name)
    f = _live.get(k) or _all().get(k) or {}
    return f if f.get("found") else {}


def hours(name: str | None) -> dict[str, list[str]] | None:
    """{"Monday": ["10:30-20:30"], "Tuesday": [], ...}, restaurant.json's
    opening_hours shape, so meal_slots reads it as is. An empty day is closed.
    None when Google has no hours for the place."""
    periods = fact(name).get("periods")
    if not periods:
        return None
    out: dict[str, list[str]] = {d: [] for d in _GOOGLE_DAYS}
    for p in periods:
        o, c = p.get("open") or {}, p.get("close")
        if c is None:  # Google's "open 24 hours"
            return {d: ["00:00-24:00"] for d in _GOOGLE_DAYS}
        try:
            out[_GOOGLE_DAYS[o["day"]]].append(
                f"{o['time'][:2]}:{o['time'][2:]}-{c['time'][:2]}:{c['time'][2:]}")
        except (KeyError, IndexError, TypeError):
            continue
    return out


def closed_weekdays(name: str | None) -> list[str] | None:
    h = hours(name)
    return None if h is None else [d for d, ranges in h.items() if not ranges]


_TIPS = (
    ("cash_only", 1, "Cash only, so bring won."),
    ("reservation_required", 1, "Book ahead; walk-ins are often turned away."),
    ("english_support", 0, "Little English is spoken, so have the name in Korean ready."),
)


def tips(name: str | None) -> str:
    """Practical lines for a foreign visitor, only where the facts say so."""
    f = fact(name)
    out = [tip for field, value, tip in _TIPS if f.get(field) == value]
    if f.get("cultural_friction") == 1 and f.get("evidence"):
        out.append(f"Heads-up: {f['evidence']}")
    return " ".join(out)
