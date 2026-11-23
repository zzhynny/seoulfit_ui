"""Capture each itinerary before (A) and after (B) critic_repair, same run.

A is what plan_node returns, B is what critic_repair_node returns, both from one
state, so the only difference between them is critic_repair. Scoring comes later;
this only collects. Makes real Gemini (+ Google Places if keyed) calls.

Usage (from backend/):
    LANGSMITH_TRACING=false venv/bin/python evals/ab_run.py --dry-run --limit 3
    LANGSMITH_TRACING=false venv/bin/python evals/ab_run.py --reps 3
    LANGSMITH_TRACING=false venv/bin/python evals/ab_run.py --out evals/out/ab_<ts>   # resume
    # B (one-shot revise) vs C (ReAct revise), same draft:
    LANGSMITH_TRACING=false venv/bin/python evals/ab_run.py --reps 3 --days 2 --revise-ab --revise-severity medium
"""
import argparse
import copy
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))


# A constraint belongs in the restrictions slot, not the purpose sentence: the
# app's intake puts it there and parse_diet derives `diet` from it. personas.json
# stays untouched (retrieval gold labels were made against its purposes); these
# replace purpose/restrictions/companion for the personas that mix them in.
OVERRIDES = {
    7: {"companion": "family",
        "purpose": "We want places children enjoy: playgrounds, aquarium or theme-park style stops."},
    11: {"restrictions": "Nothing strenuous.",
         "purpose": "I want to unwind: a jjimjilbang, a hot spring or spa, and maybe a skincare treatment."},
    12: {"restrictions": "Halal food only; I need prayer rooms.",
         "purpose": "I'd like to see some of the main sights."},
    14: {"restrictions": "Recovering from a dermatology treatment: short, easy walks only, no long hikes.",
         "purpose": "Quiet cafes and a calm day."},
}


def scenarios(limit=None, pace=None, companion="solo", start="2026-11-03", days=1):
    """personas.json -> one TravelState seed per persona, as the app would hold it
    after the day-plan screen and the user's confirm."""
    out = []
    personas = json.loads((HERE / "personas.json").read_text())["personas"]
    from meal_slots import parse_diet
    for n, name, purpose, region in personas:
        ov = OVERRIDES.get(n, {})
        restrictions = ov.get("restrictions")
        out.append({"scenario_id": n, "name": name, "state": {
            "travel_dates": f"{days} day" if days == 1 else f"{days} days",
            "trip_start_date": start,
            "companion": ov.get("companion", companion),
            "pace": pace,
            "restrictions": restrictions,
            "diet": parse_diet(restrictions) if restrictions else None,
            "purpose": ov.get("purpose", purpose),
            "purpose_keywords": [],
            "day_specs": [{"day": d + 1, "region": region, "note": "", "keywords": []}
                          for d in range(days)],
            "current_step": "retrieving",
            "confirmed": True,
            "messages": [],
        }})
    return out[:limit]


def done_keys(path):
    """(scenario_id, rep) of rows that finished; errored rows are retried."""
    keys = set()
    if path.exists():
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if not row.get("error"):
                keys.add((row["scenario_id"], row["rep"]))
    return keys


def run_one(state, retrieve, critic, revise_ab=False):
    """(A, [B]) or, with revise_ab, (A, [B, C]): C is critic_repair on the same
    draft with REVISE_MODE=react, so B vs C differ only in how flagged days are
    revised."""
    import planner
    s = {**state, **retrieve(state)}
    s = planner.plan_node(s)
    if s.get("current_step") != "critic" or not s.get("itinerary"):
        raise RuntimeError(f"plan_node did not reach critic (step={s.get('current_step')})")
    a = copy.deepcopy(s["itinerary"])
    arms = [critic(copy.deepcopy(s))]  # RepairAgent edits in place; C needs the same draft
    if revise_ab:
        os.environ["REVISE_MODE"] = "react"
        try:
            arms.append(critic(copy.deepcopy(s)))
        finally:
            os.environ.pop("REVISE_MODE", None)
    # critic_repair_node swallows its own failures and returns the unrepaired
    # plan, with no critic_report. That is not an A-vs-B sample.
    for arm in arms:
        if not (arm.get("itinerary") or {}).get("critic_report"):
            raise RuntimeError("critic_repair failed (no critic_report)")
    return a, [arm["itinerary"] for arm in arms]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only", type=int, nargs="+", help="scenario ids to run")
    ap.add_argument("--pace", choices=["relaxed", "packed"])
    ap.add_argument("--companion", default="solo")
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--out", type=Path, help="existing run dir to resume")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--revise-ab", action="store_true",
                    help="also run arm C: critic_repair with the ReAct revise agent (REVISE_MODE=react)")
    ap.add_argument("--revise-severity", choices=["high", "medium"], default="high",
                    help="lowest critic severity that sends a day to revision (eval-only; both arms)")
    args = ap.parse_args()

    out = args.out or HERE / "out" / f"ab_{datetime.now():%Y%m%d-%H%M}"
    runs = out / "runs.jsonl"
    todo = [(sc, rep) for sc in scenarios(args.limit, args.pace, args.companion, days=args.days)
            if not args.only or sc["scenario_id"] in args.only
            for rep in range(args.reps)]
    skip = done_keys(runs)
    todo = [(sc, rep) for sc, rep in todo if (sc["scenario_id"], rep) not in skip]
    print(f"out: {out}\n{len(todo)} to run, {len(skip)} already done")
    if args.dry_run:
        for sc, rep in todo[:5]:
            print(sc["scenario_id"], rep, json.dumps(sc["state"], ensure_ascii=False)[:200])
        return

    # Run from backend/ like the app does; keep the production log out of this.
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))
    from dotenv import load_dotenv
    load_dotenv(".env")
    os.environ.pop("DATABASE_URL", None)
    out.mkdir(parents=True, exist_ok=True)
    import eval_store
    eval_store._DEFAULT_SQLITE = str(out / "evals.db")

    import critic_repair
    import planner
    import revise_agent
    from critic_repair import make_critic_repair_node
    if args.revise_severity == "medium":
        # The revise path never fires at high: RepairAgent clears the only
        # high/critical day issues first. Widening it is eval-only.
        critic_repair._REVISE_SEVERITIES = {"medium", "high", "critical"}
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    retrieve = planner.make_retrieve_node(key)
    critic = make_critic_repair_node()
    # The app's intake extracts these from the purpose (graph._store); without
    # them the run sees a smaller Google supplement than a traveller would.
    import graph
    graph._api_key = key

    # ponytail: counts calls only; token counts need the raw response, which
    # _gemini_text doesn't hand back. Wrap it if cost per arm matters.
    calls = [0]
    raw = planner._gemini_text
    def counted(*a, **kw):
        calls[0] += 1
        return raw(*a, **kw)
    planner._gemini_text = counted

    for sc, rep in todo:
        calls[0], t0 = 0, time.time()
        revise_agent.STATS.clear()
        state = {**sc["state"],
                 "purpose_keywords": graph._extract_purpose_keywords(sc["state"]["purpose"])}
        row = {"scenario_id": sc["scenario_id"], "name": sc["name"], "rep": rep,
               "state": state, "error": None}
        try:
            a, (b, *c) = run_one(state, retrieve, critic, args.revise_ab)
            report = b["critic_report"]
            row.update(A=a, B=b, repair_log=report.get("repair_log"),
                       repair_applied=report.get("repair_applied"),
                       critic_before=report["before"].get("overall_score"),
                       critic_after=report["after"].get("overall_score"),
                       revised=any("Revised day" in line for line in report.get("repair_log") or []))
            if c:
                report_c = c[0]["critic_report"]
                row.update(C=c[0], repair_log_C=report_c.get("repair_log"),
                           critic_after_C=report_c["after"].get("overall_score"),
                           revised_C=any("Revised day" in line for line in report_c.get("repair_log") or []),
                           react=dict(revise_agent.STATS))
        except Exception as e:  # noqa: BLE001 -- one bad run must not stop the batch
            traceback.print_exc()
            row["error"] = f"{type(e).__name__}: {e}"
        row.update(llm_calls=calls[0], latency_s=round(time.time() - t0, 1))
        with open(runs, "a") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        print(f"[{sc['scenario_id']:>2} rep{rep}] {row['error'] or 'ok'} "
              f"({row['llm_calls']} calls, {row['latency_s']}s)")


if __name__ == "__main__":
    main()
