"""clear_thread must actually delete a thread's checkpoint state.

MemorySaver.storage turned out to be keyed by plain thread-id strings, not
the tuples clear_thread filtered for, so /reset silently deleted nothing.
This seeds a thread through the real graph api.py builds, calls
clear_thread, and checks the state is gone -- not just that the call
returned without raising, which is all the old code needed to "pass".
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import graph  # noqa: E402
from api import _config, _graph  # noqa: E402

THREAD_A = "test-clear-thread-aaaaaaaaaaaa"
THREAD_B = "test-clear-thread-bbbbbbbbbbbb"


def _seed(thread_id: str, purpose: str) -> None:
    _graph.update_state(_config(thread_id), {"purpose": purpose, "current_step": "day_plan"})


def test_clear_thread_deletes_the_seeded_threads_state():
    _seed(THREAD_A, "Shopping")
    assert _graph.get_state(_config(THREAD_A)).values.get("purpose") == "Shopping"

    graph.clear_thread(THREAD_A)

    assert _graph.get_state(_config(THREAD_A)).values == {}


def test_clear_thread_leaves_other_threads_untouched():
    _seed(THREAD_A, "Shopping")
    _seed(THREAD_B, "Food & Cafes")

    graph.clear_thread(THREAD_A)

    assert _graph.get_state(_config(THREAD_A)).values == {}
    assert _graph.get_state(_config(THREAD_B)).values.get("purpose") == "Food & Cafes"
