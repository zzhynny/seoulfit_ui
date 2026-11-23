"""Score an ab_run.py run's A (before critic_repair) and B (after) with the SeoulFit
benchmark's 13 sub-metrics, from Google Places facts. Same scorer as SeoulFit vs GPT.

    LANGSMITH_TRACING=false venv/bin/python evals/ab_bench.py evals/out/ab_<ts>
    LANGSMITH_TRACING=false venv/bin/python evals/ab_bench.py evals/out/ab_<ts> B C   # ab_run --revise-ab

Writes <run>/facts.json (cached), <run>/bench_scored.jsonl and <run>/bench_report.md
(suffixed _BC etc. for any pair but A B).
Makes Google Places and Gemini (label) calls for stops not yet in facts.json.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import bench_metrics as m
import bench_run as br

START = "2026-11-03"  # ab_run.py's trip_start_date
ORDER = br.METRIC_ORDER


def main(run, x="A", y="B"):
    br.setup("seoulfit")
    import bench_verify
    from ab_score import sign_test

    import planner
    rows = [json.loads(line) for line in (run / "runs.jsonl").read_text().splitlines()]
    rows = [r for r in rows if not r.get("error")]
    sfx = "" if (x, y) == ("A", "B") else f"_{x}{y}"
    norm = {(r["scenario_id"], arm): br.seoulfit_normalize(r[arm], START) for r in rows for arm in (x, y)}
    stops = [s for it in norm.values() for d in it["days"] for s in d["stops"]]
    facts = bench_verify.verify(planner, stops, run / "facts.json")
    bench_verify.relabel(planner, run / "facts.json")
    facts = json.loads((run / "facts.json").read_text())

    scored = [{"scenario_id": sid, "arm": arm, "scores": m.score(it, facts)} for (sid, arm), it in norm.items()]
    (run / f"bench_scored{sfx}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in scored))

    by = defaultdict(dict)
    for r in scored:
        by[r["scenario_id"]][r["arm"]] = r["scores"]
    lines = [f"| 지표 | {x} | {y} | Δ | 95% CI | {y} 승/패/동 | p |", "|---|---|---|---|---|---|---|"]
    for k in ORDER:
        d = [(v[x][k], v[y][k]) for v in by.values()]
        diffs = [b - a for a, b in d]
        w, l = sum(t > 0.0005 for t in diffs), sum(t < -0.0005 for t in diffs)
        lo, hi = br._ci(diffs)
        bold = "**" if k in ("F", "ECS", "FG", "Score") else ""
        lines.append(f"| {bold}{k}{bold} | {sum(a for a, _ in d) / len(d):.3f} | {sum(b for _, b in d) / len(d):.3f} "
                     f"| {sum(diffs) / len(diffs):+.3f} | [{lo:+.3f}, {hi:+.3f}] | {w}/{l}/{len(diffs) - w - l} | {sign_test(w, l):.3f} |")
    lines += ["", "| 시나리오 | " + f"F | ECS | FG | Score ({x} → {y}) |", "|---|---|---|---|---|"]
    for sid, v in sorted(by.items()):
        lines.append(f"| #{sid} | " + " | ".join(f"{v[x][k]:.3f} → {v[y][k]:.3f}" for k in ("F", "ECS", "FG", "Score")) + " |")
    (run / f"bench_report{sfx}.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve(), *sys.argv[2:4])
