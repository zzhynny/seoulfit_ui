"""Self-check for the one-question-per-turn intake loop in collect_node.

No framework, no network, no graph compile: drives collect_node /
handle_confirm_node directly with a scripted _gemini_raw seam.
Run: `python test_one_at_a_time_intake.py`.
"""
import json

from langchain_core.messages import AIMessage, HumanMessage

import graph
import rag


PICKED = "June 15, 2027 to June 17, 2027"   # exactly what the date picker sends


def _boom(prompt: str) -> str:
    raise AssertionError("Gemini must not be called for the dates question")


def _answer_with(value):
    """_gemini_raw stub that echoes `value` back under whichever field the
    prompt is asking for — so one stub serves every question.

    travel_dates never reaches Gemini (collect_node parses the picker's output
    itself), so this only ever fires for the other five.
    """
    def fake(prompt: str) -> str:
        field = next(f for f in graph.FIELD_ORDER if f"- {f}:" in prompt)
        return json.dumps({field: value})
    return fake


def _turn(state, text):
    """One user turn through collect_node, mimicking the add_messages reducer."""
    state = {**state, "messages": [*state.get("messages", []), HumanMessage(content=text)]}
    out = graph.collect_node(state)
    # collect_node returns only NEW messages under "messages"; the real reducer
    # appends them, so do the same here.
    new = out.get("messages", [])
    return {**state, **out, "messages": [*state["messages"], *new]}


def _last_ai(state):
    return next(m.content for m in reversed(state["messages"]) if isinstance(m, AIMessage))


def main():
    assert graph.FIELD_ORDER[0] == "travel_dates", "dates must be asked first"
    assert set(graph.FIELD_ORDER) == set(graph.ALL_FIELDS)
    assert set(graph.FIELD_EXTRACT) == set(graph.FIELD_ORDER)

    # 1. Greeting asks for dates only — not the whole questionnaire at once.
    s = graph.collect_node({"current_step": "start", "messages": []})
    assert s["current_step"] == "collecting", s["current_step"]
    assert s["pending"] == "travel_dates", s["pending"]
    assert s["asked"] == ["travel_dates"]
    greeting = s["messages"][0].content
    assert graph.FIELD_QUESTIONS["travel_dates"] in greeting
    for other in graph.FIELD_ORDER[1:]:
        assert graph.FIELD_QUESTIONS[other] not in greeting, f"{other} asked too early"

    # 2. Each answer banks one slot and asks exactly the next field, in order.
    graph._gemini_raw = _answer_with("Hongdae")
    for i, field in enumerate(graph.FIELD_ORDER):
        assert s["pending"] == field, (i, s["pending"])
        s = _turn(s, PICKED if field == "travel_dates" else "Hongdae")
        nxt = graph.FIELD_ORDER[i + 1] if i + 1 < len(graph.FIELD_ORDER) else None
        assert s["pending"] == nxt, (field, s["pending"], nxt)
        if nxt:
            assert _last_ai(s) == graph.FIELD_QUESTIONS[nxt]

    # 3. Every field asked -> hand off to the summary, once.
    assert s["current_step"] == "confirm", s["current_step"]
    assert s["asked"] == graph.FIELD_ORDER
    assert graph._after_collect(s) == "confirm"

    # 4. "ok" as an ANSWER must not hijack the flow into generating.
    #    (The old shortcut treated it as a confirm and skipped the rest.)
    s2 = graph.collect_node({"current_step": "start", "messages": []})
    graph._gemini_raw = _answer_with("MISSING")
    s2 = _turn(s2, PICKED)
    s2 = _turn(s2, "ok")
    assert s2["current_step"] == "collecting", s2["current_step"]
    assert s2["pending"] == "companion", s2["pending"]

    # 5. A field answered unintelligibly is never re-asked — it just stays empty.
    #    Without this the loop spins on the same question forever.
    assert not s2.get("category")
    assert "category" in s2["asked"]
    for _ in graph.FIELD_ORDER[2:]:
        s2 = _turn(s2, "???")
    assert s2["current_step"] == "confirm", s2["current_step"]
    assert s2["asked"] == graph.FIELD_ORDER
    # region is the one field with a fallback: MISSING/NONE -> recommendation.
    assert s2["region"].endswith("(recommended)"), s2["region"]

    # 6. Editing one field from the summary re-asks THAT field only, then goes
    #    straight back to the summary instead of restarting the questionnaire.
    graph._gemini_raw = lambda prompt: json.dumps({"intent": "pace"})
    s3 = graph.handle_confirm_node({**s, "messages": [*s["messages"], HumanMessage(content="change pace")]})
    assert s3["current_step"] == "collecting" and s3["pending"] == "pace", s3
    assert s3["pace"] is None
    s3 = {**s3, "messages": [*s["messages"], AIMessage(content=s3["messages"][0].content)]}
    graph._gemini_raw = _answer_with("relaxed")
    s3 = _turn(s3, "relaxed")
    assert s3["pace"] == "relaxed", s3["pace"]
    assert s3["current_step"] == "confirm", s3["current_step"]
    assert s3["pending"] is None

    # 7. Confirming from the summary still reaches generation. _after_collect no
    #    longer routes to handle_confirm, so route_entry is now the ONLY way in.
    s4 = {**s, "messages": [*s["messages"], HumanMessage(content="confirm")]}
    assert graph.route_entry(s4) == "handle_confirm", graph.route_entry(s4)
    graph._gemini_raw = lambda prompt: json.dumps({"intent": "CONFIRM"})
    s4 = graph.handle_confirm_node(s4)
    assert s4["confirmed"] is True and s4["current_step"] == "retrieving", s4["current_step"]

    # 8. Typed dates are bounced back to the calendar: question stays put, slot
    #    stays empty, and Gemini is never consulted (_boom proves it).
    s5 = graph.collect_node({"current_step": "start", "messages": []})
    graph._gemini_raw = _boom
    for typed in ("3 days", "next week", "June 15-17", "February 30, 2026", "ok"):
        out = _turn(s5, typed)
        assert out["pending"] == "travel_dates", (typed, out["pending"])
        assert not out.get("travel_dates"), typed
        assert "calendar" in _last_ai(out), typed

    # 9. Inclusive day count, surviving month / year / leap-day boundaries.
    for text, days, start_iso in [
        ("September 6, 2026 to September 8, 2026", 3, "2026-09-06"),
        ("September 30, 2026 to October 2, 2026", 3, "2026-09-30"),   # month
        ("December 30, 2026 to January 2, 2027", 4, "2026-12-30"),    # year
        ("February 27, 2028 to March 1, 2028", 4, "2028-02-27"),      # leap day
        ("June 15, 2027", 1, "2027-06-15"),                           # single day
    ]:
        picked = graph._parse_picked_dates(text)
        assert picked is not None, text
        got, label = graph._describe_trip(*picked)
        assert got == days, (text, got, days)
        assert picked[0].isoformat() == start_iso, (text, picked[0])
        # The planner re-derives the span from this label, so it has to agree.
        assert rag._parse_num_days(label) == days, (label, days)

    # 10. Over the cap -> re-ask, nothing stored. Exactly at the cap -> accepted.
    over = _turn(s5, "September 6, 2026 to September 13, 2026")    # 8 days
    assert over["pending"] == "travel_dates", over["pending"]
    assert not over.get("travel_dates")
    assert f"up to {graph.MAX_TRIP_DAYS}" in _last_ai(over)

    at_cap = _turn(s5, "September 6, 2026 to September 12, 2026")  # 7 days
    assert at_cap["pending"] == "category", at_cap["pending"]
    assert at_cap["trip_start_date"] == "2026-09-06", at_cap["trip_start_date"]
    assert rag._parse_num_days(at_cap["travel_dates"]) == graph.MAX_TRIP_DAYS

    # 11. A backwards range is normalised, not counted as a negative trip.
    rev = _turn(s5, "September 8, 2026 to September 6, 2026")
    assert rev["trip_start_date"] == "2026-09-06", rev["trip_start_date"]
    assert rag._parse_num_days(rev["travel_dates"]) == 3

    print("one-at-a-time intake: all checks passed")


if __name__ == "__main__":
    main()
