import os

# planner/api load .env, which turns tracing on -- without this every pytest run
# lands in the production LangSmith project as a pile of orphan root traces.
# load_dotenv never overrides a set variable, so pinning it here wins.
# test_langsmith_tracing's spy fixture flips it back on against a stubbed client.
os.environ["LANGSMITH_TRACING"] = "false"


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_place_facts(monkeypatch):
    """dataset/place_facts.json is real Google data that a rerun of the
    enrichment script changes; no test may depend on it. Tests that need
    facts patch place_facts._all themselves. Nor may a test call Google for
    hours; test_place_facts stubs _google_get to test _learn_hours itself."""
    import critic_repair
    import place_facts
    monkeypatch.setattr(place_facts, "_all", dict)
    monkeypatch.setattr(place_facts, "_live", {})
    monkeypatch.setattr(critic_repair, "_learn_hours", lambda pois, state: None)


@pytest.fixture(autouse=True)
def _no_live_react(monkeypatch):
    """plan_node hands a null day to revise_agent's ReAct agent, and .env may
    hold a real Gemini key. No test may reach it: the model fails to build, so
    react_day falls back to the one-shot call each test already fakes. Tests of
    the agent patch _model themselves."""
    import revise_agent

    def no_model():
        raise RuntimeError("no live model in tests")
    monkeypatch.setattr(revise_agent, "_model", no_model)
