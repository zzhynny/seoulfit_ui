"""LangSmith span plumbing — the three things that fail silently.

Not a test of langsmith itself. These guard the three decisions in our
decorators that produce no error when they break:

1. select_anchors' process_inputs drops `vectors` (the 125x3072 matrix, 8.7MB
   as JSON) and `purpose_vec` (69KB). Forget it and every trace carries them.
2. _google_get's process_inputs drops params["key"] — the Google Places API
   key rides in the query params of all four call sites.
3. The two ThreadPoolExecutor fan-outs re-enter the parent run tree. Without
   that, contextvars don't cross the thread boundary and every span inside
   orphans into its own root trace — which looks fine until you open one.
"""
import json

import pytest


@pytest.fixture
def spy(monkeypatch):
    """Capture what would be sent, without a LangSmith account.

    langsmith.utils.get_env_var is lru_cached, so whichever test touches
    langsmith first freezes the LANGSMITH_TRACING answer for the whole
    session -- these pass alone and record nothing in a full run without the
    cache_clear on both sides.
    """
    from langsmith import client as ls_client, utils as ls_utils

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "fake-key-for-test")
    ls_utils.get_env_var.cache_clear()

    runs = []
    monkeypatch.setattr(
        ls_client.Client, "create_run",
        lambda self, name, inputs, run_type, **kw: runs.append(
            {"name": name, "inputs": inputs, "id": kw.get("id"),
             "parent": kw.get("parent_run_id")}),
    )
    monkeypatch.setattr(ls_client.Client, "update_run", lambda self, *a, **k: None)

    yield runs

    # monkeypatch restores the env vars, but the cache would hand the next
    # test "true" and start tracing into a patched-away client.
    ls_utils.get_env_var.cache_clear()


def test_select_anchors_span_omits_the_vector_matrix(spy):
    from retrieval import load_vectors, select_anchors

    vectors = load_vectors()
    assert vectors is not None, "course_vectors.npz missing — rebuild to run this"
    select_anchors(
        {"day": 1, "region": "jongno",
         "purpose_vec": vectors[1][0]},
        vectors=vectors,
    )

    (run,) = [r for r in spy if r["name"] == "select_anchors"]
    assert set(run["inputs"]) == {"day", "region", "has_query_vec", "exclude"}
    assert run["inputs"]["has_query_vec"] is True
    # 8.7MB untrimmed. The bound is generous; the point is orders of magnitude.
    assert len(json.dumps(run["inputs"], default=str)) < 1000


def test_google_places_span_never_carries_the_api_key(spy, monkeypatch):
    import planner

    class _Resp:
        def json(self):
            return {"status": "OK", "results": [{"name": "Test Cafe"}]}

    monkeypatch.setattr(planner.requests, "get", lambda *a, **k: _Resp())
    planner.build_google_supplement_by_areas(
        requested_areas=["jongno"], location="Seoul", keywords=[{"phrase": "cafes", "poi_type": "cafe"}],
        api_key="SECRET-KEY-123", day_segments=None,
    )

    places = [r for r in spy if r["name"] == "google_places"]
    assert places, "no google_places spans recorded"
    for run in places:
        assert "key" not in (run["inputs"].get("params") or {})
    assert "SECRET-KEY-123" not in json.dumps(places, default=str)


def test_thread_fanout_spans_stay_attached_to_the_parent_run(spy, monkeypatch):
    """The fan-out runs in worker threads; contextvars don't follow."""
    import planner
    from langsmith.run_helpers import traceable

    class _Resp:
        def json(self):
            return {"status": "OK", "results": [{"name": "Test Cafe"}]}

    monkeypatch.setattr(planner.requests, "get", lambda *a, **k: _Resp())

    @traceable(run_type="chain", name="root")
    def root():
        planner.build_google_supplement_by_areas(
            requested_areas=["jongno", "hongdae"], location="Seoul",
            keywords=[{"phrase": "cafes", "poi_type": "cafe"}], api_key="k", day_segments=None,
        )

    root()

    known = {r["id"] for r in spy}
    places = [r for r in spy if r["name"] == "google_places"]
    assert places, "no google_places spans recorded"
    for run in places:
        assert run["parent"] is not None, f"{run['name']} orphaned out of its trace"
        assert run["parent"] in known, f"{run['name']} parented to an unknown run"


def test_input_rail_llm_call_stays_under_the_rail_span(spy, monkeypatch):
    """The rail's LLM call runs on guardrail_gate's own loop thread; contextvars
    don't follow, so without an explicit parent it becomes its own root trace."""
    import guardrail_gate
    from langsmith.run_helpers import traceable
    from nemoguardrails.rails.llm.options import RailStatus

    @traceable(run_type="llm", name="rail_llm")
    async def rail_llm():
        return "ok"

    class FakeRails:
        async def check_async(self, messages, rail_types=None):
            await rail_llm()
            return type("R", (), {"status": RailStatus.PASSED})()

    monkeypatch.setattr(guardrail_gate, "_get_rails", lambda: FakeRails())
    guardrail_gate.is_blocked("no pork please",
                              langsmith_extra={"metadata": {"thread_id": "t-1"}})

    (rail,) = [r for r in spy if r["name"] == "input_rail"]
    (llm,) = [r for r in spy if r["name"] == "rail_llm"]
    assert llm["parent"] == rail["id"], "rail LLM call orphaned out of input_rail"


def test_thinking_tokens_are_billed_as_output(monkeypatch):
    """google-genai 1.2 reports thinking only inside total_token_count. Left out
    of output_tokens, LangSmith priced a day at a fraction of the real bill."""
    from types import SimpleNamespace
    import planner

    rt = SimpleNamespace(metadata={}, usage=None)
    rt.set = lambda usage_metadata: setattr(rt, "usage", usage_metadata)
    monkeypatch.setattr(planner, "get_current_run_tree", lambda: rt)

    usage = SimpleNamespace(prompt_token_count=2354, candidates_token_count=949,
                            total_token_count=12102)
    planner._record_usage(SimpleNamespace(usage_metadata=usage), "gemini-3.8-flash")

    assert rt.usage["output_tokens"] == 949 + 8799
    assert rt.usage["output_token_details"] == {"reasoning": 8799}
    assert rt.usage["total_tokens"] == 12102
