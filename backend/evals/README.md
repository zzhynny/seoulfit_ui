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

## `lens_ragchecker.py`

Scores Seoul Lens (seoul.json lookup → Tavily fallback → narration) on the 23 landmarks in `lens_landmarks.json`. Vision is skipped: each landmark arrives already identified.

1. **Lookup accuracy** (no API calls): did `_lookup_in_seoul_json` return the gold row, or correctly miss a place that isn't in seoul.json?
2. **RAGChecker inputs**: narrations for two conditions on the same landmarks — `system` (as the endpoint runs) and `no_context` (narrator with no facts, the baseline). `system` is also split by where the facts came from (`official-visitseoul-en`, `official-gemini`, `web`, `none`). Makes real Gemini + Tavily calls; aborts on the first failed Gemini call.

```bash
LANGSMITH_TRACING=false venv/bin/python evals/lens_ragchecker.py   # writes evals/out/lens_*.json
```

Then score each file with RAGChecker, kept out of the backend venv (it pulls torch):

```bash
cd evals/out
SPACY=https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
for f in lens_*.json; do
  [[ $f == *.scored.json ]] && continue
  OPENAI_API_KEY=... uv run --no-project --python 3.11 --with ragchecker==0.1.9 --with "$SPACY" \
    ragchecker-cli --input_path=$f --output_path=${f%.json}.scored.json \
    --extractor_name=openai/gpt-4.1-mini-2025-04-14 --checker_name=openai/gpt-4.1-mini-2025-04-14 \
    --batch_size_extractor=8 --batch_size_checker=8 --metrics all_metrics
done
```

Read `hallucination` (claims in neither the retrieved facts nor the reference) and `faithfulness` (claims backed by the retrieved facts); with `self_knowledge` they sum to 100. Claim recall is low by design — the narration is a 150-word story, the reference a Wikipedia summary.

## `ab_run.py`

Captures each itinerary before (A, `plan_node` output) and after (B, `critic_repair_node` output) critic_repair from one run per persona. Collects only; scoring is a later step. Makes real Gemini calls.

```bash
LANGSMITH_TRACING=false venv/bin/python evals/ab_run.py --dry-run --limit 3   # no API calls
LANGSMITH_TRACING=false venv/bin/python evals/ab_run.py --reps 3              # writes evals/out/ab_<ts>/runs.jsonl
LANGSMITH_TRACING=false venv/bin/python evals/ab_run.py --out evals/out/ab_<ts> # resume; errored rows retry
```

One JSONL row per (persona, rep): `A`, `B`, `repair_log`, `critic_before/after` (reference only: the repairer optimizes what the critic scores), `llm_calls`, `latency_s`, `error`. The production `evals.db` is not touched; the run writes its own in the run dir.

## `ab_score.py`

Scores A and B from an `ab_run.py` run with checks the critic doesn't compute (no API calls): stops, gold-course stops (within 150m of a POI in the persona's gold courses), stops outside the day's area (re-inferred from address/coords), validator filler stops, straight-line route km / longest leg / legs over 3km, missing and unverified meals. Prints a paired table per metric: mean A, mean B, B win/loss/tie per scenario (reps averaged first) and a two-sided sign-test p, for all runs and for `repair_applied` runs only.

```bash
venv/bin/python evals/ab_score.py evals/out/ab_<ts>   # writes <run>/scored.jsonl
```

## `bench_run.py`: SeoulFit vs GPT-4o

Scores both systems on the 13 sub-metrics of F(p) / ECS(p) / FG(p) (`bench_metrics.py`, pure functions; `test_bench_metrics.py`). Makes real Gemini, OpenAI and Google Places calls.

```bash
export LANGSMITH_TRACING=false OUT=evals/out/bench_<ts>
venv/bin/python evals/bench_run.py scenarios                    # rewrite bench_scenarios.json (seeded, reproducible)
venv/bin/python evals/bench_run.py gen --arm seoulfit --out $OUT # resumable; --only P01 X3, --limit, --reps (1)
venv/bin/python evals/bench_run.py gen --arm gpt --out $OUT     # can run alongside the line above
venv/bin/python evals/bench_run.py verify --out $OUT             # facts.json: Google Places + Gemini labels
venv/bin/python evals/bench_run.py score --out $OUT && venv/bin/python evals/bench_run.py report --out $OUT
```

**Fair benchmark.** Both arms answer one English request per scenario. SeoulFit gets it as the state the app's intake would build. GPT-4o gets the request text plus an output JSON shape, with no quality instructions. Every stop from either arm goes through the same lookup: Find Place, then legacy Place Details (`opening_hours`, `business_status`, `serves_vegetarian_food`, `reservable`, reviews). Gemini then labels English support, cash-only, reservation-required, cultural friction and diet fit from those reviews only. It never sees the itinerary or which arm the stop came from. The system's own databases play no part in scoring. A stop Google can't find is "DB 미매칭" for both arms.

**Times.** GPT-4o's `start_time` is used as written. SeoulFit has no per-stop time in its output, so it gets the app's own clock: `planner._day_schedule` (10:00 start, `_leg_minutes` between stops, locked meals wait for their window). TF therefore compares SeoulFit's own travel estimate against the 8 + 7·km buffer.

**Scenarios** (`bench_scenarios.json`). 29 rows form a greedy 2-way covering array over days (1–5, one region per day) × theme (5) × companion (4) × diet (none, vegetarian, vegan, halal) × pace (3) × start day (Mon, Sat). On top of these sit 6 stress cases, each aimed at one metric. The PDF's "5 days / 6 regions" is 5 / 5 here because the app plans one region per day.

**Definitions the slides leave open (this study's own):**

| Item | Definition |
|---|---|
| Meal windows (MC) | `meal_slots.MEAL_SLOTS`: lunch 11:00–13:30, dinner 18:00–20:00. A meal stop is one with `meal_slot` or type restaurant/food/market |
| TF | Slide piecewise as written, including its jumps at ratio 1.0 and 1.75. No legs gives 1.0 |
| OH | Visit [start, start+stay] inside a Google `periods` window on that date. Permanently closed counts as a conflict; no hours or no match counts as unknown |
| VD ranges (min) | sight 45–150, museum 60–180, cafe 30–75, meal 45–100, shopping 45–150, market 45–120, nightlife 60–240 |
| SS | Nearest-neighbour path from the day's first stop ÷ actual path, capped at 1 |
| CP | 0.65·f_avg + 0.35·f_max. f_avg is RD's curve (1 → 8 km); f_max is linear on the day's largest pairwise distance (3 → 12 km) |
| FS | GOOD (1.0): sight→meal, meal→sight, meal→cafe, cafe→sight, sight→cafe, shopping→meal, meal→shopping, sight→shopping. BAD (0.35): cafe→meal, nightlife→sight, same category twice. Otherwise 0.75. p = 0.8 when one category is over 60% of the day's stops, else 1.0 |
| CC | Evidence is Google `serves_vegetarian_food` (vegetarian only), else the review label. The itinerary's own note is not evidence, because GPT-4o labelled a samgyetang house "vegan-friendly" in the smoke run |
| AB "guided" | The stop's note mentions reservation/booking/cash/card/queue (word-bounded) |
| CF | has_tip: the note names the friction (shoes, floor seating, ordering, kiosk, etiquette…). Guided: has_tip or a note of 80+ characters |

## Data

- `bench_scenarios.json`: the benchmark's 35 scenarios, generated by `bench_run.py scenarios`
- `personas.json`: 20 test personas (name, purpose, region) and hand-labelled gold courses per region
- `persona_ranked.json`: pre-computed top-125 rankings per persona (from one embedding batch)
