import os

# planner/api load .env, which turns tracing on -- without this every pytest run
# lands in the production LangSmith project as a pile of orphan root traces.
# load_dotenv never overrides a set variable, so pinning it here wins.
# test_langsmith_tracing's spy fixture flips it back on against a stubbed client.
os.environ["LANGSMITH_TRACING"] = "false"
