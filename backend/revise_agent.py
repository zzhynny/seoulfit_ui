"""ReAct variant of the one-shot day call, used in two places:

- revise_days, for days the critic flagged (REVISE_MODE=react);
- plan_node, for a null day the judge found no course for (on unless
  NULL_DAY_REACT=0).

The agent gets the same day prompt plus two read-only tools: find places in an
area, and check a place's hours on a weekday. Places a tool returned ride along
as `_found`, so the caller can add them to the validator's candidates --
otherwise the validator drops them as unknown. Any failure falls back to the
one-shot call for that day.

Model: gemini-3.x needs thought_signature echoed back on function-call parts,
which langchain-google-genai 2.1.12 doesn't do (400 on the second turn), so
this defaults to gemini-2.5-flash -- a model confound when A/B'd against the
one-shot path, which runs on gemini-3.8-flash.
"""
from __future__ import annotations

import os
import time
from collections import Counter
from typing import Any

from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent
from langsmith import traceable

import critic_repair
import place_facts
import planner

MAX_TOOL_CALLS = 3
DEADLINE_S = 45  # ponytail: soft wall-clock via the tool guard; each LLM call is bounded by timeout=25
STATS: Counter = Counter()  # ponytail: eval-only counters, not thread-exact

SYSTEM = (
    "You may call tools at most 3 times to find places or check opening hours. "
    "Places a tool returns count as provided candidates. Finish with ONLY the day JSON "
    "in the schema the user message gives."
)


def _model():  # monkeypatched in the test
    return ChatGoogleGenerativeAI(
        model=os.getenv("REVISE_REACT_MODEL", "gemini-2.5-flash"),
        google_api_key=planner._PLANNER_GEMINI_KEY,
        temperature=1.0, timeout=25, max_retries=1,
    )


def _tools(state, used: set[str], found: list[dict[str, Any]], calls: list[int], deadline: float):
    pool = critic_repair.build_candidate_pool(state)
    norm = critic_repair.normalize_text

    def spent() -> bool:
        calls[0] += 1
        return calls[0] > MAX_TOOL_CALLS or time.monotonic() > deadline

    @tool
    def search_places(area: str, category: str) -> str:
        """Find up to 8 places in a Seoul area (e.g. "jongno") of a category
        (e.g. "museum", "cafe", "park") that no other day uses."""
        if spent():
            return "Tool budget used up. Return the day JSON now."
        items = critic_repair.candidates_for_area(
            pool, area, exclude=used, preferred_types={norm(category)})[:8]
        center = critic_repair.SEOUL_AREA_CENTERS.get(norm(area))
        if len(items) < 3 and planner.GOOGLE_PLACES_API_KEY and center:
            items += critic_repair.google_fallback_candidates(
                lat=center[0], lng=center[1], place_type=category,
                exclude=used | {norm(i["name"]) for i in items},
                api_key=planner.GOOGLE_PLACES_API_KEY)[:8 - len(items)]
        if not items:
            return f"No {category} found in {area}."
        for i in items:  # supplement shape, so the validator accepts them
            found.append({"poi_name": i["name"], "poi_type": i.get("type"),
                          "address_en": i.get("address"), "lat": i.get("lat"),
                          "lng": i.get("lng"), "area": i.get("area")})
        return "\n".join(f"- {i['name']} ({i.get('type')}, {i.get('area')})" for i in items)

    @tool
    def opening_hours(place_name: str, weekday: str) -> str:
        """Opening hours of a place on a weekday (e.g. "Tuesday")."""
        if spent():
            return "Tool budget used up. Return the day JSON now."
        known = pool.get(norm(place_name)) or next(
            ({"lat": f["lat"], "lng": f["lng"]} for f in found
             if norm(f["poi_name"]) == norm(place_name)), {})
        if planner.GOOGLE_PLACES_API_KEY:
            critic_repair._learn_hours(
                [{"name": place_name, "lat": known.get("lat"), "lng": known.get("lng")}], state)
        h = place_facts.hours(place_name)
        if h is None:
            return f"{place_name}: no published hours."
        day = weekday.strip().capitalize()
        ranges = h.get(day)
        if ranges is None:
            return f"Unknown weekday {weekday!r}."
        return f"{place_name}: open {', '.join(ranges)} on {day}." if ranges else f"{place_name}: closed on {day}."

    return [search_places, opening_hours]


@traceable(run_type="chain", name="day_react")
def react_day(seg: dict[str, Any], *, state, used: set[str], **kw: Any) -> dict[str, Any]:
    """Same contract as planner._generate_day, plus `_found` (supplement rows
    the tools returned). `state` must carry the candidates the tools search:
    retrieved_courses and planning_context.google_supplement."""
    found: list[dict[str, Any]] = []
    calls = [0]
    try:
        agent = create_react_agent(
            _model(), _tools(state, used, found, calls, time.monotonic() + DEADLINE_S), prompt=SYSTEM)
        out = agent.invoke({"messages": [("user", planner._day_prompt(seg, **kw))]},
                           {"recursion_limit": 2 * MAX_TOOL_CALLS + 4})
        day = planner._parse_itinerary_json(out["messages"][-1].text())
        if not isinstance(day, dict):
            raise ValueError("not a JSON object")
        STATS["ok"] += 1
        STATS["tool_calls"] += calls[0]
        return {**day, "day": planner._day_num(seg), "_found": found}
    except Exception as e:
        print(f"[react] day {planner._day_num(seg)} fell back: {type(e).__name__}: {e}")
        STATS["fallback"] += 1
        return planner._generate_day(seg, **kw)
