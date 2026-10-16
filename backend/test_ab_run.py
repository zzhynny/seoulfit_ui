import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "evals"))
import ab_run


def test_scenarios_shape():
    sc = ab_run.scenarios(limit=3)
    assert len(sc) == 3
    s = sc[0]["state"]
    assert s["current_step"] == "retrieving" and s["day_specs"][0]["region"]


def test_done_keys_skips_finished_retries_errors(tmp_path):
    p = tmp_path / "runs.jsonl"
    rows = [{"scenario_id": 1, "rep": 0, "error": None},
            {"scenario_id": 1, "rep": 1, "error": "boom"}]
    p.write_text("\n".join(json.dumps(r) for r in rows))
    assert ab_run.done_keys(p) == {(1, 0)}
