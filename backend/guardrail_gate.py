"""Input gatekeeper — NeMo `self check input` rail in front of /chat.

Loads the LLMRails config in backend/guardrails/ once (module singleton) and
exposes ``is_blocked(text)``. Only the INPUT rail runs (rail_types=["input"]),
so no reply is generated here — LangGraph still produces every response.

The rail costs one extra Gemini call per message; see step 3 (cost/latency)
before turning it on for every turn in production.
"""
from __future__ import annotations

import asyncio
import os
import threading

# The self-check LLM runs through langchain-google-genai (engine: google_genai in
# guardrails/config.yml). This env var must be set before nemoguardrails is
# imported so its framework registry picks it up.
os.environ.setdefault("NEMOGUARDRAILS_LLM_FRAMEWORK", "langchain")
# ChatGoogleGenerativeAI reads GOOGLE_API_KEY; mirror GEMINI_API_KEY like api.py.
if os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]

from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree, tracing_context
from nemoguardrails import LLMRails, RailsConfig
from nemoguardrails.rails.llm.options import RailStatus, RailType

_here = os.path.dirname(os.path.abspath(__file__))
_rails: LLMRails | None = None

# NeMo's Gemini client binds to the first event loop it runs on. The sync
# rails.check() makes a fresh loop on whichever thread calls it, so under
# uvicorn's threadpool only a process's first check worked -- every later one
# raised "attached to a different loop" and failed open. So every check runs
# on this one loop, on its own thread, and so does building the rails.
_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()
_CHECK_TIMEOUT_S = 20


def _rails_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _loop_lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, name="guardrail-loop", daemon=True).start()
    return _loop


def _get_rails() -> LLMRails:
    global _rails
    if _rails is None:
        config = RailsConfig.from_path(os.path.join(_here, "guardrails"))
        _rails = LLMRails(config)
    return _rails


@traceable(run_type="chain", name="input_rail")
def is_blocked(text: str | None, question: str | None = None) -> bool:
    """True if the user message should be blocked by the input rail.

    [question] is the question the buddy just asked, when there is one. Without
    it the rail judges each message in isolation, which is hopeless for the
    one-word replies the intake flow is built out of: a bare "none" answering
    "Any dietary or physical restrictions?" got blocked as off-topic chit-chat,
    while "I have no restrictions" sailed through. The question is app text
    (FIELD_QUESTIONS), never user input, so it is safe to hand to the judge.

    Empty/whitespace input is never blocked (the greeting turn sends no message).
    Any guardrail error, or a check slower than _CHECK_TIMEOUT_S, falls open
    (returns False) — a flaky safety check must not take down the chat endpoint. ponytail: fail-open here; flip to fail-closed
    only if abuse via induced errors ever shows up.
    """
    if not text or not text.strip():
        return False
    content = text
    if question:
        # Labelled rather than glued together, so the judge can tell our question
        # from their reply — and so an injection can't fake the prefix and claim
        # the app sanctioned it.
        content = f'[SeoulFit Buddy asked: "{question}"]\n{text}'
    # langsmith: the check runs on _loop's thread, which contextvars don't reach,
    # so the rail's Gemini call would orphan into its own root trace. Hand it
    # this span as parent explicitly.
    parent = get_current_run_tree()
    try:
        async def check():
            with tracing_context(parent=parent):
                return await _get_rails().check_async(
                    [{"role": "user", "content": content}],
                    rail_types=[RailType.INPUT],
                )

        result = asyncio.run_coroutine_threadsafe(check(), _rails_loop()).result(
            timeout=_CHECK_TIMEOUT_S
        )
        return result.status == RailStatus.BLOCKED
    except Exception:
        import traceback
        traceback.print_exc()
        return False
