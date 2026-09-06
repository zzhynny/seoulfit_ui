"""Self-check for _gemini_json's one-shot JSON self-heal retry (12-Factor #9).

No framework, no network: monkeypatches the module-global _gemini_raw seam with
scripted replies and asserts the retry contract. Run: `python test_gemini_retry.py`.
"""
import graph


def _fake(replies):
    """Scripted _gemini_raw: pops one reply per call, raising if it's an
    Exception instance. Tracks call count; failing loudly (not IndexError) if
    called more times than scripted so a runaway retry is a clean assert fail."""
    state = {"calls": 0}

    def fake(prompt: str) -> str:
        i = state["calls"]
        state["calls"] += 1
        assert i < len(replies), f"_gemini_raw called {i + 1}x, only {len(replies)} scripted"
        reply = replies[i]
        if isinstance(reply, Exception):
            raise reply
        return reply

    return fake, state


def main():
    # Seam must exist — without it the retry has nowhere to hook.
    assert hasattr(graph, "_gemini_raw"), "graph._gemini_raw seam is missing"

    # 1. Valid JSON on the first reply -> parsed, exactly one call (no needless retry).
    graph._gemini_raw, s = _fake(['{"a": 1}'])
    assert graph._gemini_json("x") == {"a": 1}
    assert s["calls"] == 1, s["calls"]

    # 2. Bad first reply, valid on retry -> parsed, exactly two calls.
    graph._gemini_raw, s = _fake(["not json", '{"a": 2}'])
    assert graph._gemini_json("x") == {"a": 2}
    assert s["calls"] == 2, s["calls"]

    # 3. Both replies bad -> {} floor, no raise, exactly two calls.
    graph._gemini_raw, s = _fake(["not json", "still not json"])
    assert graph._gemini_json("x") == {}
    assert s["calls"] == 2, s["calls"]

    # 4. Retry call itself raises (transient 429/5xx/network) -> {} floor, no propagation.
    graph._gemini_raw, s = _fake(["not json", RuntimeError("429 rate limited")])
    assert graph._gemini_json("x") == {}
    assert s["calls"] == 2, s["calls"]

    print("OK — _gemini_json retry self-check passed (4 cases)")


if __name__ == "__main__":
    main()
