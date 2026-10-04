"""Measure recall@k of select_anchors on 20 personas vs filter-only and random baselines.

Offline, no embedding calls needed (uses pre-computed rankings from persona_ranked.json).
Usage: python evals/retrieval_eval.py
"""
import json
from math import comb
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import retrieval

here = Path(__file__).parent
GOLD = {int(k): set(v) for k, v in json.load(open(here / "personas.json"))["gold"].items()}
ranked = {r["n"]: r for r in json.load(open(here / "persona_ranked.json"))}

def hit(order, g, k): return any(c in g for c in order[:k])
def first_rank(order, g): return next((i for i, c in enumerate(order, 1) if c in g), None)

K = (1, 3, 5, 10)
rows = []
for n, g in GOLD.items():
    r = ranked[n]
    emb = [c for c, _ in r["ranked"]]
    base = [c["course_id"] for c in retrieval._dedupe_by_base(retrieval.filter_pool(r["region"]))]
    N = len(base)
    rows.append(dict(n=n, g=len(g), emb={k: hit(emb, g, k) for k in K},
                     base={k: hit(base, g, k) for k in K},
                     rnd={k: 1 - comb(N - len(g), k) / comb(N, k) for k in K},
                     rank=first_rank(emb, g)))

lab = [x for x in rows if x["g"]]
print(f"\nhit@k over {len(lab)} personas with fitting course:")
print(f"{'':22}" + "".join(f"{'@'+str(k):>8}" for k in K))
for name, key in (("embedding", "emb"), ("filter-only", "base"), ("random", "rnd")):
    print(f"{name:22}" + "".join(f"{sum(x[key][k] for x in lab)/len(lab):>8.2f}" for k in K))
print(f"MRR (embedding): {sum(1/x['rank'] for x in lab)/len(lab):.3f}")
