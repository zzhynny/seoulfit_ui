"""Build RAGChecker inputs for Seoul Lens, plus seoul.json lookup accuracy.

Vision is skipped: each landmark in lens_landmarks.json arrives already
identified, so this scores the seoul.json lookup, the Tavily fallback and the
narration (lens.describe_landmark), not Gemini Vision.

Two conditions on the same landmarks:
  system      describe_landmark() as the endpoint runs it
  no_context  the narrator with no retrieved facts (baseline: what retrieval adds)

Makes real Gemini + Tavily calls; token usage is printed at the end.
Usage: venv/bin/python evals/lens_ragchecker.py
Then score evals/out/lens_*.json with RAGChecker (see evals/README.md).
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import httpx
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv(Path(__file__).parent.parent / ".env")
import lens

SEED = 42  # Gemini seed is best-effort; reruns can still differ slightly
here = Path(__file__).parent
out_dir = here / "out"
fixture = here / "lens_landmarks.json"
spec = json.loads(fixture.read_text(encoding="utf-8"))
items = spec["landmarks"]
rows_by_sn = {r["post_sn"]: r for r in lens._SEOUL_ROWS}

# Count tokens and pin the seed on every Gemini call lens makes.
usage = Counter()
_generate = lens._gemini_client.models.generate_content


def _counted(**kw):
    if kw.get("config") is not None and kw["config"].seed is None:
        kw["config"].seed = SEED
    try:
        r = _generate(**kw)
    except Exception as e:
        # lens swallows Exception and narrates a fallback string; SystemExit gets
        # past that so a failed call stops the run instead of scoring the fallback.
        raise SystemExit(f"Gemini call failed, aborting before writing outputs: {e}") from e
    u = r.usage_metadata
    usage["calls"] += 1
    usage["input"] += u.prompt_token_count or 0
    usage["output"] += (u.candidates_token_count or 0) + (u.thoughts_token_count or 0)
    return r


lens._gemini_client.models.generate_content = _counted


# ── gt_answer: Wikipedia summary + the place's official seoul.json facts ──
def _gt(item: dict) -> str:
    r = httpx.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{item['wiki']}",
                  headers={"User-Agent": "seoulfit-eval"}, follow_redirects=True, timeout=15)
    r.raise_for_status()
    parts = [r.json()["extract"]]
    row = rows_by_sn.get(item["gold_post_sn"])
    if row:
        official = row.get("_en") or row  # visitseoul's own English record when it has one
        parts.append("\n".join(lens._fact_lines(lens._extract_fields(official))))
    return "\n\n".join(parts)


if any("gt_answer" not in it for it in items):
    for it in items:
        it.setdefault("gt_answer", _gt(it))
    fixture.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote gt_answer into {fixture.name} — review it, it is the reference RAGChecker scores against")

# ── Retrieval: did the lookup return the gold row (or correctly miss)? ──
outcome = Counter()
print("\nseoul.json lookup")
for it in items:
    row, _ = lens._lookup_in_seoul_json([it["name_korean"], *it["aliases_korean"]])
    got, gold = (row or {}).get("post_sn"), it["gold_post_sn"]
    if got == gold:
        kind = "hit" if gold else "correct_miss"
    elif gold is None:
        kind = "false_match"  # not in seoul.json, but another row was returned
    elif got is None:
        kind = "miss"
    else:
        kind = "wrong_row"
    outcome[kind] += 1
    if kind not in ("hit", "correct_miss"):
        print(f"  {kind:12} {it['name_korean']} -> {(row or {}).get('post_sj')!r} (gold {gold})")
n = len(items)
print(f"  accuracy {outcome['hit'] + outcome['correct_miss']}/{n}  {dict(outcome)}")
assert sum(outcome.values()) == n

# ── Generation: same landmarks, with and without retrieval ──
results = defaultdict(list)
for i, it in enumerate(items):
    info = {k: it[k] for k in ("name_korean", "name_english", "aliases_korean", "category")}
    info["confidence"] = 95
    base = {"query": f"Audio guide narration for {it['name_english']} ({it['name_korean']})",
            "gt_answer": it["gt_answer"]}

    out = lens.describe_landmark(info)
    facts = lens._fact_lines(out["public_info_en"] or out["public_info"])
    src = "official-" + out["en_source"] if out["data_verified"] else out["en_source"]
    rec = {**base, "query_id": f"{i}:{src}", "response": out["description"],
           # RAGChecker needs at least one chunk; an empty one means "nothing retrieved".
           "retrieved_context": [{"doc_id": f.split(":")[0], "text": f} for f in facts]
                                or [{"doc_id": "none", "text": ""}]}
    results["system"].append(rec)
    results[f"system_{src}"].append(rec)

    narration = lens._generate_english_guide(info, {}, "none")
    results["no_context"].append({**base, "query_id": f"{i}:no_context", "response": narration,
                                  "retrieved_context": [{"doc_id": "none", "text": ""}]})
    print(f"  [{i + 1}/{n}] {it['name_korean']}: {src}, {len(facts)} facts")

out_dir.mkdir(exist_ok=True)
for name, recs in results.items():
    (out_dir / f"lens_{name}.json").write_text(
        json.dumps({"results": recs}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  out/lens_{name}.json  {len(recs)} results")
print(f"\nGemini {lens._GEMINI_MODEL} (seed {SEED}): {usage['calls']} calls, "
      f"{usage['input']:,} input / {usage['output']:,} output tokens (output incl. thinking)")
