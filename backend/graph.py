from __future__ import annotations

import re
import json
from datetime import date, datetime
from types import SimpleNamespace
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from state import TravelState
from planner import make_retrieve_node, plan_node
from critic_repair import make_critic_repair_node

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
        "Otherwise return exactly one of: travel_dates, category, restrictions, companion, pace, region "
        "(the field they want to change)."
    )
    data = _gemini_json(prompt)
    return SimpleNamespace(intent=str(data.get("intent", "CONFIRM")))


# ---------------------------------------------------------------------------
# Field metadata
# ---------------------------------------------------------------------------

FIELD_LABELS = {
    "travel_dates": "Travel Dates",
    "category":     "Interests",
    "restrictions": "Restrictions",
    "companion":    "Traveling With",
    "pace":         "Trip Style",
    "region":       "Seoul Area",
}

ALL_FIELDS = list(FIELD_LABELS.keys())

FIELD_QUESTIONS = {
    # No "or how many days?" — a typed duration is exactly what the picker-only
    # rule rejects, so the question must not invite one.
    "travel_dates": "When are you travelling? Tap the calendar to pick your dates "
                    "(up to 7 days).",
    "category":     "What are your main interests? (beauty, history, food, shopping, activity)",
    "restrictions": "Any dietary or physical restrictions? (or 'none')",
    "companion":    "Who are you traveling with? (solo/couple/friends/family)",
    "pace":         "Packed schedule or relaxed pace?",
    "region":       "Which area of Seoul? (e.g. Hongdae, Gangnam, Itaewon) -- or I can recommend!",
}

# The order the buddy asks in, one field per turn. Deliberately not
# ALL_FIELDS order: region goes last so _recommend_region has a category to
# work from when the traveller wants a suggestion instead of picking an area.
FIELD_ORDER = ["travel_dates", "category", "companion", "pace", "restrictions", "region"]

# One JSON instruction line per field, fed to _extract_field. Lifted verbatim
# from the old combined extraction prompt so behaviour per field is unchanged.
FIELD_EXTRACT = {
    "travel_dates": 'travel_dates: dates or duration like "June 15-17", "3 days". '
                    '"MISSING" if the reply does not answer the question.',
    "category":     'category: interests normalized to K-POP/Cafe/Beauty/Food/Shopping/'
                    'History/Activity. Comma-separated if multiple. "MISSING" if the '
                    'reply does not answer the question.',
    "companion":    'companion: solo/couple/friends/family. "MISSING" if the reply does '
                    'not answer the question.',
    "pace":         'pace: "packed" for busy or "relaxed" for slow pace. "MISSING" if the '
                    'reply does not answer the question.',
    "restrictions": 'restrictions: dietary or physical restrictions. "none" if the user '
                    'says they have no restrictions. "MISSING" if the reply does not '
                    'answer the question.',
    "region":       'region: one or more areas from Hongdae/Seongsu/Gangnam/Itaewon/'
                    'Myeongdong/Jongno/Bukchon/Mapo/Insadong/Dongdaemun/Sinchon/Apgujeong. '
                    'Comma-separated if multiple. "NONE" if the user asks for a '
                    'recommendation or does not specify.',
}


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


_CATEGORY_REGIONS: dict[str, str] = {
    "beauty":   "Hongdae or Gangnam",
    "history":  "Jongno or Bukchon",
    "food":     "Gwangjang Market or Myeongdong",
    "shopping": "Myeongdong or Gangnam",
    "activity": "Hongdae or Mapo",
}


def _recommend_region(category: str | None) -> str:
    if not category:
        return "Hongdae or Myeongdong"
    cat = category.lower()
    for key, region in _CATEGORY_REGIONS.items():
        if key in cat:
            return region
    return "Hongdae or Myeongdong"


def _parse_regions(raw: str) -> str:
    parts = re.split(r'\s+and\s+|\s*&\s*|\s*,\s*', raw.strip(), flags=re.IGNORECASE)
    cleaned = [p.strip().title() for p in parts if p.strip()]
    return ", ".join(cleaned) if cleaned else raw.strip()


def build_summary(state: TravelState) -> str:
    lines = "\n".join(
        f"{FIELD_LABELS[f]}: {state.get(f) or '--'}" for f in ALL_FIELDS
    )
    return (
        f"Here's your Seoul trip summary:\n\n{lines}\n\n"
        "Ready to generate your itinerary? Type 'confirm'.\n"
        "Want to change something? Just tell me (e.g. 'change region', 'edit dates')."
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

    if field == "region":
        # "NONE" (asked us to recommend) and "MISSING" (didn't answer) both land
        # on the category-based suggestion — same as the old collecting_region.
        if not value or value.upper() in ("MISSING", "NONE"):
            return {"region": f"{_recommend_region(state.get('category'))} (recommended)"}
        return {"region": _parse_regions(value)}

    if not value or value.upper() == "MISSING":
        return {}

    return {field: value}


def _ask(state: TravelState, updates: dict, field: str | None) -> TravelState:
    """Apply `updates`, then either ask `field` or fall through to the summary."""
    if field is None:
        return {**state, **updates, "pending": None, "current_step": "confirm"}
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
        return {**state, "pending": None, "current_step": "confirm"}

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

    if step == "confirm":
        messages = state.get("messages", [])
        if messages and isinstance(messages[-1], HumanMessage):
            return "handle_confirm"
        return "confirm"

    return "collect"


def _after_collect(state: TravelState) -> str:
    # Collecting only reaches "confirm" once every field has had its question,
    # and the traveller has never seen the summary at that point -- so always
    # show it. Routing straight to handle_confirm here used to hijack a plain
    # answer like "ok" into generating the itinerary.
    return "confirm" if state.get("current_step") == "confirm" else END


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

    builder.add_conditional_edges(
        "collect",
        _after_collect,
        {"confirm": "confirm", END: END},
    )

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
    """Delete one thread's checkpoints from the in-memory store."""
    if _memory is None:
        return
    to_del = [k for k in list(_memory.storage) if isinstance(k, tuple) and k[0] == thread_id]
    for k in to_del:
        del _memory.storage[k]
