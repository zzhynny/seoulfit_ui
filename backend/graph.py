from __future__ import annotations

import re
import json
from datetime import date, datetime
from typing import Any
from types import SimpleNamespace
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from state import TravelState
from planner import make_retrieve_node, plan_node
from critic_repair import make_critic_repair_node
from retrieval import DAY_PLAN_REGION_ORDER

# ---------------------------------------------------------------------------
# Module-level API key (set by build_graph)
# ---------------------------------------------------------------------------

_api_key: str = ""


# ---------------------------------------------------------------------------
# Direct Gemini helpers (replaces DSPy — avoids response_schema incompatibility)
# ---------------------------------------------------------------------------

def _gemini_raw(prompt: str) -> str:
    """Single Gemini JSON-mode call → raw text. Seam for testing + retry."""
    from google import genai as _genai
    client = _genai.Client(api_key=_api_key)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config={"response_mime_type": "application/json"},
    )
    return response.text or ""


def _gemini_json(prompt: str) -> dict:
    text = _gemini_raw(prompt)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # factor 9: feed the malformed output back so the model self-corrects (one retry).
        retry = (
            f"{prompt}\n\nYour previous reply was NOT valid JSON:\n{text}\n"
            "Return ONLY valid JSON, no markdown, no commentary."
        )
        try:
            return json.loads(_gemini_raw(retry))
        # ponytail: the retry is a 2nd live call — catch anything (429/5xx/network),
        # not just bad JSON, so a flaky retry keeps today's silent-{} floor instead
        # of surfacing as a user-facing apology. First call's errors still propagate.
        except Exception:
            return {}


def _classify_intent(user_message: str) -> SimpleNamespace:
    prompt = (
        f'Classify what the user wants to do with their Seoul trip plan.\n'
        f'Message: "{user_message}"\n\n'
        "Return JSON with exactly this field:\n"
        '- intent: "CONFIRM" if user confirms/agrees/wants to proceed. '
        "Otherwise return exactly one of: travel_dates, restrictions, companion, pace, purpose "
        "(the field they want to change)."
    )
    data = _gemini_json(prompt)
    return SimpleNamespace(intent=str(data.get("intent", "CONFIRM")))


# ---------------------------------------------------------------------------
# Field metadata
# ---------------------------------------------------------------------------

FIELD_LABELS = {
    "travel_dates": "Travel Dates",
    "restrictions": "Restrictions",
    "companion":    "Traveling With",
    "pace":         "Trip Style",
    "purpose":      "Trip Purpose",
}

ALL_FIELDS = list(FIELD_LABELS.keys())

FIELD_QUESTIONS = {
    # No "or how many days?" — a typed duration is exactly what the picker-only
    # rule rejects, so the question must not invite one.
    "travel_dates": "When are you travelling? Tap the calendar to pick your dates "
                    "(up to 7 days).",
    "restrictions": "Any dietary or physical restrictions? (or 'none')",
    "companion":    "Who are you traveling with? (solo/couple/friends/family)",
    "pace":         "Packed schedule or relaxed pace?",
    # 자유 서술이다. 라벨로 정규화하지 않는다 — 뭉개면 임베딩할 게 없어진다.
    # 이 문장이 코스 purpose 와의 유사도 순위를 정한다.
    "purpose":      "Last one -- what's this trip for? (e.g. 'first time with my "
                    "parents', 'a free afternoon on a work trip')",
}

# 한 턴에 한 필드씩 묻는 순서. purpose 가 마지막인 이유는 앞의 답들로
# 여행 성격이 이미 잡힌 다음에 물어야 "뭐 얘기하지" 없이 답하기 쉽기 때문이다.
# region 과 관심사(category)는 여기 없다 — 날짜마다 다른 게 정상이라 Day Planner
# 화면이 날마다 받는다. 채팅에서 먼저 물으면 같은 질문을 두 번 하게 된다.
FIELD_ORDER = ["travel_dates", "companion", "pace", "restrictions", "purpose"]

# One JSON instruction line per field, fed to _extract_field. Lifted verbatim
# from the old combined extraction prompt so behaviour per field is unchanged.
FIELD_EXTRACT = {
    "travel_dates": 'travel_dates: dates or duration like "June 15-17", "3 days". '
                    '"MISSING" if the reply does not answer the question.',
    "companion":    'companion: solo/couple/friends/family. "MISSING" if the reply does '
                    'not answer the question.',
    "pace":         'pace: "packed" for busy or "relaxed" for slow pace. "MISSING" if the '
                    'reply does not answer the question.',
    "restrictions": 'restrictions: dietary or physical restrictions. "none" if the user '
                    'says they have no restrictions. "MISSING" if the reply does not '
                    'answer the question.',
    "purpose":      'purpose: the traveller\'s own words for what this trip is for, '
                    'copied verbatim and translated to English if needed. Do NOT '
                    'summarise into a category. "MISSING" if they skipped, declined, '
                    'or did not answer.',
}


# 앱의 관심사 어휘. Day Planner 드롭다운(Flutter kInterestLabels),
# course_descriptions.json 의 interests 가 전부 이 문자열을 그대로 쓴다.
INTEREST_LABELS = [
    "Culture & History", "Food & Cafes", "Shopping",
    "K-POP & Hallyu", "Nature & Relaxation",
]

# Day Planner 화면이 제시하는 12개 지역(lib/models/travel_state.dart의
# kRegionLabels와 동일한 키·순서). geo.SEOUL_AREA_CENTERS는 33개 키를 갖고
# 있어 앱이 절대 주지 않는 21개(nowon, dobong, gwanak, dmc, ...)까지 통과
# 시킨다 — 코스 풀이 1~3개뿐인 지역이 그대로 새면 그날 앵커가 거의 없다.
# DAY_PLAN_REGION_ORDER와 같은 객체를 그대로 쓰므로 둘이 어긋날 수 없다.
DAY_PLAN_REGIONS = DAY_PLAN_REGION_ORDER


def _extract_field(field: str, text: str) -> str:
    """Pull ONE slot out of the reply to that slot's own question.

    Strict one-at-a-time: anything else the traveller volunteers is ignored,
    because the very next turn asks for it directly.
    """
    prompt = (
        f'The user was asked: "{FIELD_QUESTIONS[field]}"\n'
        f'They replied: "{text}"\n\n'
        "Return JSON with exactly this field:\n"
        f"- {FIELD_EXTRACT[field]}"
    )
    data = _gemini_json(prompt)
    return str(data.get(field, "MISSING")).strip()


def build_summary(state: TravelState) -> str:
    lines = "\n".join(
        f"{FIELD_LABELS[f]}: {state.get(f) or '--'}" for f in ALL_FIELDS
    )
    return (
        f"Here's your Seoul trip summary:\n\n{lines}\n\n"
        "Ready to generate your itinerary? Type 'confirm'.\n"
        "Want to change something? Just tell me (e.g. 'change purpose', 'edit dates')."
    )


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

# The date question is answered by the client's date picker, never by typing.
# formatDateRange() in conversational_intake_screen.dart emits exactly this:
# "September 6, 2026" or "September 30, 2026 to October 2, 2026".
_PICKED_DATES_RE = re.compile(
    r"^([A-Za-z]+ \d{1,2}, \d{4})(?:\s+to\s+([A-Za-z]+ \d{1,2}, \d{4}))?$"
)

MAX_TRIP_DAYS = 7


def _parse_picked_dates(text: str) -> tuple[date, date] | None:
    """Parse the picker's output into (start, end), or None for typed text.

    Deliberately strict — anything that isn't the picker's own format is a
    hand-typed answer, and collect_node bounces those back to the calendar
    rather than guessing. Nothing here is fuzzy, so no LLM call and no
    dateutil: the picker already resolved the ambiguity.
    """
    m = _PICKED_DATES_RE.match(text.strip())
    if not m:
        return None
    try:
        start = datetime.strptime(m.group(1), "%B %d, %Y").date()
        end = datetime.strptime(m.group(2), "%B %d, %Y").date() if m.group(2) else start
    except ValueError:
        return None            # real-looking but impossible ("February 30, 2026")
    return (start, end) if end >= start else (end, start)


def _format_date(d: date) -> str:
    # Not strftime("%-d"): that flag isn't portable, and %d would print "June 05".
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def _describe_trip(start: date, end: date) -> tuple[int, str]:
    """Inclusive day count plus the label stored in travel_dates.

    date subtraction does the calendar work, so month and year boundaries need
    no special case: Sept 30 -> Oct 2 is (2 days) + 1 = 3, same as any other
    three-day span. The "(N days)" suffix is what rag._parse_num_days reads,
    and an explicit count beats it having to re-derive the span from the text.
    """
    days = (end - start).days + 1
    label = _format_date(start) if start == end else f"{_format_date(start)} to {_format_date(end)}"
    return days, f"{label} ({days} day{'s' if days != 1 else ''})"


def _next_field(state: TravelState) -> str | None:
    """The first field we haven't put a question to yet, or None when done.

    Keyed on `asked`, not on which slots are empty: a field the traveller
    skipped or answered unintelligibly stays empty, and asking it again would
    loop forever. Every field gets exactly one question.
    """
    asked = state.get("asked") or []
    return next((f for f in FIELD_ORDER if f not in asked), None)


def _store(field: str, raw: str, state: TravelState) -> dict:
    """Turn one extracted value into the state update for its slot."""
    value = (raw or "").strip()

    if field == "purpose":
        # collect_node re-asks before a MISSING purpose ever reaches here (see
        # the purpose branch there), so this only fires for a direct _store
        # call. Keep the same "empty means skipped" contract for callers that
        # bypass the chat flow entirely (tests, scripts).
        return {"purpose": "" if not value or value.upper() == "MISSING" else value}

    if not value or value.upper() == "MISSING":
        return {}

    return {field: value}


DEFAULT_INTEREST = "Culture & History"


def default_day_specs(state: TravelState) -> list[dict[str, Any]]:
    """day_plan 단계에 들어가는 순간 채워 넣는 날짜별 기본값.

    화면은 이 값을 GET /state 로 읽어 보여주기만 한다. 기본값 로직을 서버와
    화면 양쪽에 두면 반드시 어긋나므로 여기 한 곳에만 둔다. 그리고 day_specs 가
    항상 존재하므로 "비어 있을 때" 라는 분기가 생기지 않는다.

    지역은 코스 풀이 넓은 곳부터 서로 다르게 배분한다 — 그대로 두어도 권역이
    다양한 무난한 여행이 된다. 관심사는 기본값으로 시작하고 여행자가 날마다 고른다.
    """
    from rag import _parse_num_days

    days = _parse_num_days(state.get("travel_dates"))
    order = DAY_PLAN_REGION_ORDER
    return [
        {"day": i + 1, "region": order[i % len(order)], "interest": DEFAULT_INTEREST}
        for i in range(days)
    ]


def _ask(state: TravelState, updates: dict, field: str | None) -> TravelState:
    """Apply `updates`, then either ask `field` or fall through.

    `field is None` fires in two different situations, and they must not be
    treated the same:
    - Intake just finished for the first time (no day_specs yet) -> fill in
      the day-plan defaults and send the traveller there.
    - The traveller edited one field from the confirm screen (`asked` stays
      full across that re-ask, so this reads as "no more fields" again) ->
      day_specs already holds their own picks, so land back on confirm
      without recomputing anything. Recomputing here would silently wipe a
      custom day plan on every unrelated field edit.

    The second case has its own edge: if the edited field was travel_dates
    and the trip is now a different length, the existing day_specs no longer
    covers the trip (Task 6's retrieve_node walks day_specs to decide how
    many days to build). So "keep it" only holds while the length still
    matches -- otherwise this collapses back into the first case.
    """
    from rag import _parse_num_days

    if field is None:
        merged = {**state, **updates}
        specs = merged.get("day_specs")
        if specs and len(specs) == _parse_num_days(merged.get("travel_dates")):
            return {**merged, "pending": None, "current_step": "confirm"}
        return {
            **merged,
            "pending": None,
            "current_step": "day_plan",
            "day_specs": default_day_specs(merged),
            "messages": [AIMessage(content=(
                "Got it. Now pick an area and a focus for each day -- "
                "I've filled in a starting point you can change."
            ))],
        }
    return {
        **state, **updates,
        "pending": field,
        "asked": [*(state.get("asked") or []), field],
        "current_step": "collecting",
        "messages": [AIMessage(content=FIELD_QUESTIONS[field])],
    }


def collect_node(state: TravelState) -> TravelState:
    """One question per turn: ask `pending`, bank the answer, ask the next."""
    step = state.get("current_step", "start")
    messages = state.get("messages", [])

    if step == "start":
        first = FIELD_ORDER[0]
        greeting = (
            "Hi! I'm SeoulFit Buddy \U0001f425\n"
            "I'll ask a few quick questions, one at a time, "
            "and then build your Seoul trip.\n\n"
            f"\U0001f5d3 {FIELD_QUESTIONS[first]}"
        )
        return {**state, "current_step": "collecting", "pending": first,
                "asked": [first], "messages": [AIMessage(content=greeting)]}

    last_human = next((m.content for m in reversed(messages) if isinstance(m, HumanMessage)), None)
    if not last_human:
        return state

    # Note: no "confirm"/"yes"/"ok" shortcut here any more. With one question per
    # turn those are ordinary answers ("Any restrictions?" -> "no"), and swallowing
    # them as a confirm skipped the rest of intake. Confirming is handle_confirm's
    # job, reached only from current_step == "confirm".
    field = state.get("pending") or _next_field(state)
    if field is None:
        # Route through _ask instead of jumping to confirm directly: this
        # was the one path that could reach confirm without day_specs ever
        # existing (unreachable today only by luck of the current routing),
        # while every downstream consumer of day_specs assumes it's always
        # there once current_step reaches confirm.
        return _ask(state, {}, None)

    if field == "travel_dates":
        # Picker-only: no extraction, no LLM. Both rejections leave `pending`
        # on travel_dates, so the next message is read as another attempt.
        picked = _parse_picked_dates(last_human)
        if picked is None:
            return {**state, "messages": [AIMessage(content=(
                "Please tap the calendar icon \U0001f5d3 to pick your travel dates.\n"
                "That way I get the exact days and can check what's actually open."
            ))]}
        days, label = _describe_trip(*picked)
        if days > MAX_TRIP_DAYS:
            return {**state, "messages": [AIMessage(content=(
                f"That's {days} days — I can plan up to {MAX_TRIP_DAYS} at a time.\n"
                "Tap the calendar again and pick a shorter range."
            ))]}
        return _ask(
            state,
            {"travel_dates": label, "trip_start_date": picked[0].isoformat()},
            _next_field(state),
        )

    try:
        raw = _extract_field(field, last_human)
    except Exception as e:
        # Leave `pending` where it is so the same question is re-asked.
        return {**state, "messages": [AIMessage(
            content=f"Sorry, I had trouble understanding that. Could you try again? ({e})"
        )]}

    if field == "purpose" and (not raw.strip() or raw.strip().upper() == "MISSING"):
        # Every other field tolerates MISSING and moves on -- purpose used to
        # as well ("Or tap skip"), but it's the one slot planner.py has no
        # good default for: a blank purpose meant guessing a sentence out of
        # pace/companion/interests instead of what the traveller actually
        # wants. `pending` stays put, same as the travel_dates retry above.
        return {**state, "messages": [AIMessage(content=(
            "I'd like an actual answer here -- even a few words ('birthday trip', "
            "'layover, killing time') is enough. What's this trip for?"
        ))]}

    updates = _store(field, raw, state)

    # _next_field reads `asked`, which already contains `field` -- so this is the
    # next unasked one, and None once every field has had its turn.
    return _ask(state, updates, _next_field(state))


def confirm_node(state: TravelState) -> TravelState:
    return {**state, "current_step": "confirm",
            "messages": [AIMessage(content=build_summary(state))]}


def handle_confirm_node(state: TravelState) -> TravelState:
    messages = state.get("messages", [])
    last_human = next((m.content for m in reversed(messages) if isinstance(m, HumanMessage)), None)
    if not last_human:
        return state

    try:
        result = _classify_intent(last_human)
        intent = result.intent.strip().upper()
    except Exception as e:
        return {**state, "messages": [AIMessage(
            content=f"Error occurred. Please try again. ({e})"
        )]}

    if intent == "CONFIRM":
        lines = "\n".join(f"{FIELD_LABELS[f]}: {state.get(f) or '--'}" for f in ALL_FIELDS)
        return {
            **state,
            "confirmed": True,
            "current_step": "retrieving",
            "messages": [AIMessage(
                content=f"Let's build your Seoul itinerary!\n\n{lines}\n\n"
                        "Searching the Seoul course catalogue..."
            )]
        }

    field = intent.lower()
    if field in ALL_FIELDS:
        # Re-ask this one field only. `asked` deliberately stays full, so
        # _next_field returns None after the answer and we land back on the
        # summary instead of restarting the whole questionnaire.
        reset: dict = {field: None, "pending": field}
        if field == "travel_dates":
            # travel_dates가 다시 채워질 때까지 묵은 trip_start_date가 남아있지
            # 않도록 같이 지운다 (다음 턴에 collecting_basics에서 둘 다 새로 채워짐).
            reset["trip_start_date"] = None
        return {
            **state,
            **reset,
            "current_step": "collecting",
            "messages": [AIMessage(content=f"Got it! {FIELD_QUESTIONS[field]}")]
        }

    return {**state, "messages": [AIMessage(
        content="Type 'confirm' to proceed, or tell me what you'd like to change."
    )]}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def route_entry(state: TravelState) -> str:
    if state.get("itinerary"):
        return END

    step = state.get("current_step", "start")

    if step == "retrieving":
        return "retrieve"
    if step == "planning":
        return "plan"
    if step == "critic":
        return "critic_repair"

    if step == "day_plan":
        # 화면이 POST /day-plan 으로 넘어가기 전까지는 그래프가 할 일이 없다.
        return END

    if step == "confirm":
        messages = state.get("messages", [])
        if messages and isinstance(messages[-1], HumanMessage):
            return "handle_confirm"
        return "confirm"

    return "collect"


def _after_collect(state: TravelState) -> str:
    # 마지막 질문에 답하면 day_plan 으로 넘어간다. 그래프는 여기서 멈추고,
    # 다음 진입은 POST /day-plan 이 current_step 을 confirm 으로 옮긴 뒤다.
    return END


def _after_handle_confirm(state: TravelState) -> str:
    if state.get("current_step") == "retrieving":
        return "retrieve"
    return END


def _after_retrieve(state: TravelState) -> str:
    return "plan" if state.get("current_step") == "planning" else END


def _after_plan(state: TravelState) -> str:
    return "critic_repair" if state.get("current_step") == "critic" else END


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph(api_key: str):
    global _api_key
    _api_key = api_key

    builder = StateGraph(TravelState)

    builder.add_node("collect", collect_node)
    builder.add_node("confirm", confirm_node)
    builder.add_node("handle_confirm", handle_confirm_node)
    builder.add_node("retrieve", make_retrieve_node(api_key))
    builder.add_node("plan", plan_node)
    builder.add_node("critic_repair", make_critic_repair_node())

    builder.set_conditional_entry_point(route_entry, {
        "collect":        "collect",
        "confirm":        "confirm",
        "handle_confirm": "handle_confirm",
        "retrieve":       "retrieve",
        "plan":           "plan",
        "critic_repair":  "critic_repair",
        END:              END,
    })

    builder.add_conditional_edges("collect", _after_collect, {END: END})

    builder.add_edge("confirm", END)

    builder.add_conditional_edges(
        "handle_confirm",
        _after_handle_confirm,
        {"retrieve": "retrieve", END: END},
    )

    builder.add_conditional_edges(
        "retrieve",
        _after_retrieve,
        {"plan": "plan", END: END},
    )

    builder.add_conditional_edges(
        "plan",
        _after_plan,
        {"critic_repair": "critic_repair", END: END},
    )

    builder.add_edge("critic_repair", END)

    global _memory
    _memory = MemorySaver()
    return builder.compile(checkpointer=_memory)


_memory: MemorySaver | None = None


def clear_thread(thread_id: str) -> None:
    """Delete one thread's checkpoints from the in-memory store.

    `MemorySaver.storage` is keyed by plain thread-id strings, not the
    tuples an earlier version of this function filtered for, so that
    filter never matched anything and /reset was a silent no-op. Use the
    checkpointer's own `delete_thread`, which also clears `writes` and
    `blobs` for the thread.
    """
    if _memory is None:
        return
    _memory.delete_thread(thread_id)
