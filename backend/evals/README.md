# Retrieval and Judge Evaluation

Two offline eval scripts for the anchor selection pipeline.

## `retrieval_eval.py`

Measures recall@k of `select_anchors` on 20 personas against filter-only (dataset order) and random baselines.

**No API calls.** Uses pre-computed rankings from `persona_ranked.json`.

```bash
python evals/retrieval_eval.py
```

Output: hit@k (recall) for each method, and mean reciprocal rank (MRR) of the first fitting course.

## `judge_eval.py`

Measures `judge_anchors` accuracy on the same 20 personas, 3 runs each. Makes real Gemini calls.

**Requires:** `GEMINI_API_KEY` and `LANGSMITH_TRACING=false` to suppress tracing output.

```bash
LANGSMITH_TRACING=false python evals/judge_eval.py
```

Output: accuracy on personas with a fitting course vs. those with none, token usage.

## Data

- `personas.json`: 20 test personas (name, purpose, region) and hand-labelled gold courses per region
- `persona_ranked.json`: pre-computed top-125 rankings per persona (from one embedding batch)
