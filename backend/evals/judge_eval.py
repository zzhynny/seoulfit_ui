"""Measure judge accuracy on 20 personas, 3 runs each. Makes real Gemini calls.

Usage: LANGSMITH_TRACING=false python evals/judge_eval.py
"""
import json
import os
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(Path(__file__).parent.parent)
from dotenv import load_dotenv
load_dotenv(".env")

import planner, retrieval

here = Path(__file__).parent
data = json.load(open(here / "personas.json"))
GOLD = {int(k): set(v) for k, v in data["gold"].items()}
ranked = {r["n"]: r for r in json.load(open(here / "persona_ranked.json"))}
C = {c["course_id"]: c for c in retrieval.load_courses()}
planner.set_planner_api_key(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))

from google import genai
client = genai.Client(api_key=planner._PLANNER_GEMINI_KEY)
usage, lock = Counter(), threading.Lock()

def text(prompt):
    r = client.models.generate_content(model="gemini-3.8-flash", contents=prompt,
                                       config={"response_mime_type": "application/json"})
    u = r.usage_metadata
    with lock:
        usage["calls"] += 1
        usage["in"] += u.prompt_token_count or 0
        usage["out_total"] += (u.total_token_count or 0) - (u.prompt_token_count or 0)
    return r.text

planner._gemini_text = text

def run(job):
    (n, name, purpose, region), rep = job
    seg = {"day_numbers": [1], "area": region,
           "anchor_courses": [C[cid] for cid, _ in ranked[n]["ranked"][:3]]}
    picks, _ = planner.judge_anchors([seg], [purpose])
    return n, rep, picks.get(1, "KEEP_ALL")

jobs = [(p, rep) for p in data["personas"] for rep in range(3)]
with ThreadPoolExecutor(6) as ex:
    res = list(ex.map(run, jobs))

by = {}
for n, rep, pick in res:
    by.setdefault(n, []).append(pick)

names = {p[0]: (p[1], p[3]) for p in data["personas"]}
print(f"{'#':>3} {'persona':22} picks (3 runs)   correct")
for n in sorted(by):
    g = GOLD[n]
    picks = by[n]
    correct = [(p is None) if not g else (p in g) for p in picks]
    top3 = ",".join(c for c, _ in ranked[n]["ranked"][:3])
    print(f"{n:>3} {names[n][0]:22} {picks}  {sum(correct)}/3")

lab = [n for n in by if GOLD[n]]
none = [n for n in by if not GOLD[n]]
acc = lambda ns: sum(((p is None) if not GOLD[n] else (p in GOLD[n])) for n in ns for p in by[n]) / (3 * len(ns))
print(f"\naccuracy, with course ({len(lab)}): {acc(lab):.2f}  without ({len(none)}): {acc(none):.2f}")
print(f"overall: {sum(((p is None) if not GOLD[n] else (p in GOLD[n])) for n in by for p in by[n])}/{len(res)}")
print(f"stable: {sum(len(set(map(str, v))) == 1 for v in by.values())}/{len(by)}")
print(f"tokens: {usage['calls']} calls, input {usage['in']}, output {usage['out_total']}")
