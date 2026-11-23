"""Measure recall@k of select_anchors on 20 personas vs filter-only and random baselines.

Offline, no embedding calls needed (uses pre-computed rankings from persona_ranked.json).
Usage: python evals/retrieval_eval.py
"""
import json
import sys
from math import comb
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import retrieval

here = Path(__file__).parent
GOLD = {int(k): set(v) for k, v in json.loads((here / "personas.json").read_text(encoding="utf-8"))["gold"].items()}
ranked = {r["n"]: r for r in json.loads((here / "persona_ranked.json").read_text(encoding="utf-8"))}

def hit(order, g, k): return any(c in g for c in order[:k])
def first_rank(order, g): return next((i for i, c in enumerate(order, 1) if c in g), None)

K = (1, 3, 5, 10)
rows = []
for n, g in GOLD.items():
    r = ranked[n]
    emb = [c for c, _ in r["ranked"]]
    base = [c["course_id"] for c in retrieval._dedupe_by_base(retrieval.filter_pool(r["region"]))]
    N = len(base)
    rows.append({"n": n, "g": len(g), "emb": {k: hit(emb, g, k) for k in K},
                 "base": {k: hit(base, g, k) for k in K},
                 # k 가 풀보다 크면 무작위 순서도 전부 보여준다 — min(k, N).
                 "rnd": {k: 1 - comb(N - len(g), min(k, N)) / comb(N, min(k, N)) for k in K},
                 "rank": first_rank(emb, g)})

lab = [x for x in rows if x["g"]]
print(f"\nhit@k over {len(lab)} personas with fitting course:")
print(f"{'':22}" + "".join(f"{'@'+str(k):>8}" for k in K))
for name, key in (("embedding", "emb"), ("filter-only", "base"), ("random", "rnd")):
    print(f"{name:22}" + "".join(f"{sum(x[key][k] for x in lab)/len(lab):>8.2f}" for k in K))
print(f"MRR (embedding): {sum(1/x['rank'] for x in lab)/len(lab):.3f}")
