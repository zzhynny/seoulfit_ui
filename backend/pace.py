"""Shared per-day POI-count bounds driven by trip pace (relaxed/packed).

Single source of truth for planner.py (LLM prompt guidance + the generator
validator's fill/trim step) and critic_repair.py (Critic's TOO_FEW_POIS
check + RepairAgent's under-fill step), so every layer that decides "how
many POIs should a day have" reads the same numbers instead of each keeping
its own copy that can drift (see planner.py's now-former _pace_bounds,
which critic_repair.py never read at all -- it had a separate hardcoded 5).

Pulled out into its own module (not left in planner.py) so critic_repair.py
doesn't have to import planner.py -- a heavy dspy/FAISS/Google-Places
dependency -- just for two integers.
"""

from __future__ import annotations

# (min, max) POIs per day, keyed by the pace value collected during intake
# (graph.FIELD_QUESTIONS["pace"]: "packed"/"relaxed").
PACE_BOUNDS: dict[str, tuple[int, int]] = {
    "relaxed": (5, 6),
    "packed": (7, 8),
}

# No pace on record (unset, unrecognized, or a state/test fixture that never
# set it) -- a middling default, not a guess at either extreme. This was
# already planner.py's only fallback value; kept as-is so unifying the two
# modules doesn't also change what "no pace" means.
DEFAULT_BOUNDS: tuple[int, int] = (6, 7)


def pace_bounds(pace: str | None) -> tuple[int, int]:
    """(min, max) POIs/day for a raw `pace` value, e.g. state.get("pace")."""
    return PACE_BOUNDS.get((pace or "").strip().lower(), DEFAULT_BOUNDS)
