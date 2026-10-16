"""SeoulFit vs GPT benchmark: scenarios -> generate -> verify -> score -> report.

    venv/bin/python evals/bench_run.py scenarios                 # writes evals/bench_scenarios.json
    venv/bin/python evals/bench_run.py gen --arm seoulfit --out evals/out/bench_X [--limit N] [--reps 1]
    venv/bin/python evals/bench_run.py gen --arm gpt      --out evals/out/bench_X
    venv/bin/python evals/bench_run.py verify --out evals/out/bench_X   # Google Places + Gemini labels
    venv/bin/python evals/bench_run.py score  --out evals/out/bench_X
    venv/bin/python evals/bench_run.py report --out evals/out/bench_X   # writes report.md

Each arm writes its own runs_<arm>.jsonl and resumes from it (errored rows retry),
so the two arms can run side by side. Run with LANGSMITH_TRACING=false.
"""
import argparse
import itertools
import json
import os
import random
import sys
import time
import traceback
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))

import bench_metrics as m

SCENARIOS = HERE / "bench_scenarios.json"
ARMS = ("seoulfit", "gpt", "gpt_rules")
GPT_MODEL = "gpt-5.6-terra"  # both GPT arms; gpt-4o was the first run

# ---------------------------------------------------------------- scenarios

REGIONS = ["jongno", "gangnam", "itaewon", "myeongdong", "hongdae",
           "yeouido", "seongsu", "dongdaemun", "jamsil"]  # retrieval.DAY_PLAN_REGION_ORDER
# Theme -> personas.json ids whose purpose sentence and home region stand for it.
THEMES = {"heritage": [1, 13, 18], "hallyu": [2, 3], "food": [4, 15],
          "shopping_beauty": [5, 10], "wellness_night": [11, 8]}
AXES = {
    "days": [1, 2, 3, 4, 5],
    "theme": list(THEMES),
    "companion": ["solo", "couple", "family", "friends"],
    "diet": [None, "vegetarian", "vegan", "halal"],
    "pace": [None, "relaxed", "packed"],
    "weekday": ["mon", "sat"],
}
START = {"mon": "2026-11-02", "sat": "2026-11-07"}
DIET_TEXT = {"vegetarian": "I'm vegetarian.", "vegan": "I'm vegan.", "halal": "Halal food only."}

# Hand-picked to provoke a specific failure; 6.3 reads these first.
STRESS = [
    {"name": "Monday heritage", "days": 2, "persona": 1, "regions": ["jongno", "myeongdong"],
     "companion": "solo", "weekday": "mon", "probe": "OH"},
    {"name": "Halal family, 5 days", "days": 5, "persona": 12, "diet": "halal",
     "companion": "family", "weekday": "sat", "probe": "CC"},
    {"name": "Packed nightlife", "days": 2, "persona": 8, "pace": "packed",
     "companion": "friends", "weekday": "sat", "probe": "TF"},
    {"name": "Vegan, 1 day", "days": 1, "persona": 4, "diet": "vegan",
     "companion": "solo", "weekday": "mon", "probe": "CC"},
    {"name": "Recovery, easy walks", "days": 2, "persona": 14, "pace": "relaxed",
     "restrictions": "Recovering from a dermatology treatment: short, easy walks only, no long hikes.",
     "companion": "couple", "weekday": "sat", "probe": "MB"},
    {"name": "Four far-apart regions", "days": 4, "persona": 7,
     "regions": ["jamsil", "hongdae", "gangnam", "jongno"],
     "companion": "family", "weekday": "mon", "probe": "RD"},
]


# The nine traveller types: each fills the seven fields the app asks for and is
# aimed at the failures its type tends to hit. Purposes are the one English
# sentence both arms receive.
PERSONAS = [
    {"name": "First-time culture solo", "days": 3, "regions": ["jongno", "jongno", "dongdaemun"],
     "companion": "solo", "weekday": "mon",
     "purpose": "It's my first time in Korea. I want palaces, hanok streets and traditional culture."},
    {"name": "Vegan foodie couple", "days": 2, "regions": ["seongsu", "hongdae"],
     "companion": "couple", "weekday": "sat", "diet": "vegan",
     "purpose": "We love food: vegan restaurants and local cafes."},
    {"name": "Halal family", "days": 4, "regions": ["itaewon", "myeongdong", "jamsil", "jongno"],
     "companion": "family", "weekday": "sat", "pace": "relaxed", "diet": "halal",
     "purpose": "A Muslim family: halal food and prayer rooms matter."},
    {"name": "Family with young kids", "days": 3, "regions": ["jamsil", "yeouido", "jongno"],
     "companion": "family", "weekday": "sat", "pace": "relaxed",
     "purpose": "Two kids under 8. We need places children enjoy: playgrounds, aquarium or theme-park style stops."},
    {"name": "K-pop fan friends", "days": 2, "regions": ["seongsu", "gangnam"],
     "companion": "friends", "weekday": "mon", "pace": "packed",
     "purpose": "We're K-pop fans: idol-related places, agency buildings and merchandise."},
    {"name": "Shopping and beauty solo", "days": 1, "regions": ["myeongdong"],
     "companion": "solo", "weekday": "sat", "pace": "packed",
     "purpose": "Korean skincare brands, Olive Young, beauty clinics and trendy fashion."},
    {"name": "Nightlife friends", "days": 2, "regions": ["hongdae", "itaewon"],
     "companion": "friends", "weekday": "sat", "pace": "packed",
     "purpose": "Bars, live music and late-night spots. We're happy to start late."},
    {"name": "Five-day mixed couple", "days": 5,
     "regions": ["jongno", "seongsu", "myeongdong", "gangnam", "hongdae"],
     "companion": "couple", "weekday": "mon", "diet": "vegetarian",
     "purpose": "A bit of everything: history, food and shopping."},
    {"name": "Senior couple, little English", "days": 3, "regions": ["jongno", "gangnam", "yeouido"],
     "companion": "couple", "weekday": "mon", "pace": "relaxed",
     "purpose": "We are in our late sixties and speak very little English. We prefer slow days "
                "and places that are easy to walk."},
]


def pairwise_rows(seed=7, tries=200):
    """Greedy 2-way covering array over AXES: every pair of levels from any two
    axes shows up in at least one row. Seeded, so the set is reproducible."""
    rng = random.Random(seed)
    names = list(AXES)
    uncovered = {((a, x), (b, y)) for a, b in itertools.combinations(names, 2)
                 for x in AXES[a] for y in AXES[b]}
    def pairs(row):
        return {((a, row[a]), (b, row[b])) for a, b in itertools.combinations(names, 2)}

    rows = []
    while uncovered:
        # Seed each candidate from one uncovered pair so every row makes progress.
        pool = sorted(uncovered, key=str)
        candidates = []
        for _ in range(tries):
            (a, x), (b, y) = rng.choice(pool)
            candidates.append({k: rng.choice(v) for k, v in AXES.items()} | {a: x, b: y})
        best = max(candidates, key=lambda r: len(pairs(r) & uncovered))
        rows.append(best)
        uncovered -= pairs(best)
    return rows


def build_scenarios():
    personas = {p[0]: p for p in json.loads((HERE / "personas.json").read_text())["personas"]}
    rng = random.Random(11)
    seen = defaultdict(int)
    out = []
    for i, row in enumerate(pairwise_rows(), 1):
        pid = THEMES[row["theme"]][seen[row["theme"]] % len(THEMES[row["theme"]])]
        seen[row["theme"]] += 1
        home = personas[pid][3]
        regions = [home] + rng.sample([r for r in REGIONS if r != home], row["days"] - 1)
        out.append({"id": f"P{i:02d}", "set": "pairwise", "persona": pid, "regions": regions,
                    **{k: row[k] for k in AXES}})
    for i, s in enumerate(STRESS, 1):
        home = personas[s["persona"]][3]
        regions = s.get("regions") or [home] + rng.sample([r for r in REGIONS if r != home], s["days"] - 1)
        out.append({"id": f"X{i}", "set": "stress", "theme": None, "diet": None, "pace": None,
                    **s, "regions": regions})
    for i, s in enumerate(PERSONAS, 1):
        out.append({"id": f"PS{i}", "set": "persona", "theme": None, "diet": None, "pace": None, **s})
    for sc in out:
        if sc["set"] != "persona":
            sc["purpose"] = sc.get("purpose") or personas[sc["persona"]][2]
        sc["start"] = START[sc["weekday"]]
        sc["restrictions"] = " ".join(filter(None, [DIET_TEXT.get(sc.get("diet")), sc.get("restrictions")])) or None
        sc["request"] = render_request(sc)
    return out


def render_request(sc):
    """The one English request both arms answer."""
    who = {"solo": "on my own", "couple": "as a couple", "friends": "with friends",
           "family": "with my family (young children)"}[sc["companion"]]
    start = date.fromisoformat(sc["start"])
    days = "; ".join(f"Day {i + 1} ({(start + timedelta(i)):%a %b %d}): {r.title()}"
                     for i, r in enumerate(sc["regions"]))
    pace = {"relaxed": " I prefer a relaxed pace.", "packed": " I want to fit in as much as I can."}
    parts = [f"I'm visiting Seoul for {sc['days']} day{'s' * (sc['days'] > 1)}, {who}.",
             sc["purpose"], f"Areas by day: {days}.{pace.get(sc.get('pace'), '')}"]
    if sc.get("restrictions"):
        parts.append(sc["restrictions"])
    return " ".join(parts)


def load_scenarios(limit=None, only=None):
    scs = json.loads(SCENARIOS.read_text())
    if only:
        scs = [s for s in scs if s["id"] in only]
    return scs[:limit]


# --------------------------------------------------------------------- arms

def _hhmm(text):
    h, mnt = str(text).split(":")[:2]
    return int(h) * 60 + int(mnt)


def seoulfit_state(sc, graph):
    from meal_slots import parse_diet
    state = {
        "travel_dates": f"{sc['days']} day" if sc["days"] == 1 else f"{sc['days']} days",
        "trip_start_date": sc["start"], "companion": sc["companion"], "pace": sc.get("pace"),
        "restrictions": sc.get("restrictions"),
        "diet": parse_diet(sc["restrictions"]) if sc.get("restrictions") else None,
        "purpose": sc["purpose"],
        "day_specs": [{"day": i + 1, "region": r, "note": "", "keywords": []}
                      for i, r in enumerate(sc["regions"])],
        "current_step": "retrieving", "confirmed": True, "messages": [],
    }
    state["purpose_keywords"] = graph._extract_purpose_keywords(sc["purpose"])
    return state


def seoulfit_normalize(itinerary, start):
    """The app's own clock (planner._day_schedule) gives each stop its start time."""
    import planner
    days = []
    for d in itinerary.get("days") or []:
        t, stops, pois = planner._DAY_START, [], d.get("pois") or []
        for i, p in enumerate(pois):
            if i:
                t += planner._leg_minutes(pois[i - 1], p)
            window = planner.meal_slots.MEAL_SLOTS.get(p.get("meal_slot") or "")
            if window:
                t = max(t, planner._hhmm(window[0]))
            stay = int(float(p.get("stay_minutes") or 60))
            stops.append({"name": p.get("name"), "type": p.get("type"), "lat": p.get("lat"),
                          "lng": p.get("lng"), "start": t, "stay_minutes": stay,
                          "meal_slot": p.get("meal_slot"), "notes": p.get("notes") or ""})
            t += stay
        days.append({"day": d.get("day"), "stops": stops})
    return _dated(days, start)


def _dated(days, start):
    s = date.fromisoformat(start)
    for d in days:
        d["date"] = (s + timedelta(int(d["day"]) - 1)).isoformat()
    return {"days": days}


def run_seoulfit(sc, ctx):
    import planner
    state = seoulfit_state(sc, ctx["graph"])
    s = {**state, **ctx["retrieve"](state)}
    s = planner.plan_node(s)
    if s.get("current_step") != "critic" or not s.get("itinerary"):
        raise RuntimeError(f"plan_node did not reach critic (step={s.get('current_step')})")
    out = ctx["critic"](s).get("itinerary") or {}
    if not out.get("critic_report"):
        raise RuntimeError("critic_repair failed (no critic_report)")
    return out, seoulfit_normalize(out, sc["start"])


TYPES = sorted(m.CATEGORY)
GPT_SYSTEM = "You are a Seoul travel planner."
GPT_FORMAT = f"""Answer with JSON only, in this shape:
{{"days": [{{"day": 1, "stops": [{{
  "name": "the place's real name, in English",
  "type": one of {TYPES},
  "start_time": "HH:MM",
  "stay_minutes": integer,
  "meal_slot": "lunch" | "dinner" | null,
  "lat": number, "lng": number,
  "notes": "one short note about the stop"
}}]}}]}}"""


# The same rules SeoulFit's code enforces, said in plain words and without the
# scoring formulas: what a careful human planner would be told.
GPT_RULES_SYSTEM = """You are a Seoul travel planner. Follow these rules for every day:
- Include a lunch stop starting between 11:00 and 13:30 and a dinner stop starting between 18:00 and 20:00
  (meal_slot "lunch" / "dinner").
- Start the day at 10:00 and end by 22:00 (nightlife trips may run later). Do not overfill the day.
- Leave real time between stops: at least 8 minutes plus 7 minutes per km of distance. start_time of the next
  stop must be after the previous stop's start_time plus its stay_minutes plus that travel time.
- Only schedule a place when it is open for the whole visit on that weekday. Check the weekday of each date;
  museums and palaces often close on Mondays or Tuesdays. Prefer well-known places with stable opening hours.
- Keep each day inside its area; order stops so the route does not zigzag, and keep stops within a few km of each other.
- Give realistic stay_minutes (sights 45-150, museums 60-180, cafes 30-75, meals 45-100).
- Follow the traveller's diet strictly; choose restaurants that really serve it.
- This is a foreign visitor: in each note mention what they need to know: reservations, cash-only, whether
  English is spoken, shoes-off or floor seating, ordering rules. Only state what you actually know.
- Use real, currently operating places with their real English names and correct coordinates."""


def run_gpt(sc, ctx, system=GPT_SYSTEM):
    resp = ctx["openai"].chat.completions.create(
        model=GPT_MODEL, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": f"{sc['request']}\n\n{GPT_FORMAT}"}])
    raw = json.loads(resp.choices[0].message.content)
    days = []
    for d in raw.get("days") or []:
        stops = []
        for p in d.get("stops") or []:
            try:
                start = _hhmm(p.get("start_time"))
            except (ValueError, AttributeError):
                start = None
            stops.append({"name": p.get("name"), "type": (p.get("type") or "").lower(),
                          "lat": p.get("lat"), "lng": p.get("lng"), "start": start,
                          "stay_minutes": p.get("stay_minutes"), "meal_slot": p.get("meal_slot"),
                          "notes": p.get("notes") or ""})
        days.append({"day": d.get("day"), "stops": stops})
    return raw, _dated(days, sc["start"])


def run_gpt_rules(sc, ctx):
    return run_gpt(sc, ctx, system=GPT_RULES_SYSTEM)


def setup(arm):
    os.chdir(BACKEND)
    from dotenv import load_dotenv
    load_dotenv(".env")
    os.environ.pop("DATABASE_URL", None)
    if arm.startswith("gpt"):
        from openai import OpenAI
        return {"openai": OpenAI()}
    import graph
    import planner
    from critic_repair import make_critic_repair_node
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    graph._api_key = key
    return {"graph": graph, "retrieve": planner.make_retrieve_node(key),
            "critic": make_critic_repair_node()}


def read_rows(out, arm):
    path = out / f"runs_{arm}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def cmd_gen(args):
    args.out.mkdir(parents=True, exist_ok=True)
    if args.arm == "seoulfit":  # critic_repair banks a score; keep it out of the prod db
        import eval_store
        eval_store._DEFAULT_SQLITE = str(args.out / "evals.db")
    done = {(r["scenario_id"], r["rep"]) for r in read_rows(args.out, args.arm) if not r.get("error")}
    todo = [(sc, rep) for sc in load_scenarios(args.limit, args.only) for rep in range(args.reps)
            if (sc["id"], rep) not in done]
    print(f"{args.arm}: {len(todo)} to run, {len(done)} done")
    ctx = setup(args.arm)
    run = {"seoulfit": run_seoulfit, "gpt": run_gpt, "gpt_rules": run_gpt_rules}[args.arm]
    for sc, rep in todo:
        t0, row = time.time(), {"scenario_id": sc["id"], "rep": rep, "arm": args.arm, "error": None}
        try:
            row["raw"], row["itinerary"] = run(sc, ctx)
        except Exception as e:  # noqa: BLE001 -- one bad run must not stop the batch
            traceback.print_exc()
            row["error"] = f"{type(e).__name__}: {e}"
        row["latency_s"] = round(time.time() - t0, 1)
        with open(args.out / f"runs_{args.arm}.jsonl", "a") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        print(f"[{args.arm} {sc['id']} rep{rep}] {row['error'] or 'ok'} ({row['latency_s']}s)")


# ------------------------------------------------------- verify / score

def latest_ok(out, only=None):
    """Last successful row per (arm, scenario, rep), limited to `only` ids if given."""
    keep = {}
    for arm in ARMS:
        for r in read_rows(out, arm):
            if not r.get("error") and (not only or r["scenario_id"] in only):
                keep[(arm, r["scenario_id"], r["rep"])] = r
    return list(keep.values())


def cmd_verify(args):
    import bench_verify
    setup("seoulfit")
    import planner
    stops = [s for r in latest_ok(args.out, args.only) for d in r["itinerary"]["days"] for s in d["stops"]]
    bench_verify.verify(planner, stops, args.out / "facts.json")
    bench_verify.relabel(planner, args.out / "facts.json")


def cmd_score(args):
    facts = json.loads((args.out / "facts.json").read_text())
    by_id = {s["id"]: s for s in json.loads(SCENARIOS.read_text())}
    from meal_slots import parse_diet
    rows = []
    for r in latest_ok(args.out, args.only):
        sc = by_id[r["scenario_id"]]
        diet = parse_diet(sc["restrictions"]) if sc.get("restrictions") else None
        rows.append({k: r[k] for k in ("scenario_id", "rep", "arm")}
                    | {"scores": m.score(r["itinerary"], facts, diet)})
    with open(args.out / "scored.jsonl", "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
    print(f"scored {len(rows)} itineraries -> {args.out / 'scored.jsonl'}")


# ------------------------------------------------------------------ report

LABELS = {"gpt": "GPT (no rules)", "gpt_rules": "GPT (with rules)"}
METRIC_ORDER = ["MC", "TF", "OH", "F", "RD", "VD", "SS", "CP", "FS", "ECS",
                "LA", "MB", "CC", "AB", "CF", "FG", "Score"]


def _paired(scored, metric, ids, vs="gpt"):
    """Per scenario (reps averaged): (seoulfit, vs arm) for scenarios both arms finished."""
    acc = defaultdict(lambda: defaultdict(list))
    for r in scored:
        if r["scenario_id"] in ids:
            acc[r["scenario_id"]][r["arm"]].append(r["scores"][metric])
    return [(sum(v["seoulfit"]) / len(v["seoulfit"]), sum(v[vs]) / len(v[vs]))
            for v in acc.values() if v["seoulfit"] and v[vs]]


def _ci(diffs, n=2000):
    """Bootstrap 95% CI of the mean paired difference."""
    if len(diffs) < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(0)
    means = sorted(sum(rng.choices(diffs, k=len(diffs))) / len(diffs) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def _table(scored, ids, metrics=METRIC_ORDER, vs="gpt"):
    from ab_score import sign_test
    lines = [f"| 지표 | SeoulFit | {LABELS[vs]} | Δ | 95% CI | W/L/T | p |", "|---|---|---|---|---|---|---|"]
    for k in metrics:
        pairs = _paired(scored, k, ids, vs)
        if not pairs:
            continue
        diffs = [a - b for a, b in pairs]
        w, l = sum(d > 0 for d in diffs), sum(d < 0 for d in diffs)
        lo, hi = _ci(diffs)
        bold = "**" if k in ("F", "ECS", "FG", "Score") else ""
        lines.append(f"| {bold}{k}{bold} | {sum(a for a, _ in pairs) / len(pairs):.3f} "
                     f"| {sum(b for _, b in pairs) / len(pairs):.3f} | {sum(diffs) / len(diffs):+.3f} "
                     f"| [{lo:+.3f}, {hi:+.3f}] | {w}/{l}/{len(diffs) - w - l} | {sign_test(w, l):.3f} |")
    return "\n".join(lines)


def diagnose(itin, facts):
    """Human-readable reasons behind a low score, for 6.3."""
    out = []
    for d in itin["days"]:
        day = date.fromisoformat(d["date"])
        stops = d["stops"]
        for lo, hi in m.MEAL_WINDOWS.values():
            if not any((s.get("meal_slot") or m._flow(s) == "meal") and s.get("start") is not None
                       and lo <= s["start"] <= hi for s in stops):
                out.append(f"D{d['day']}: no meal starting {lo // 60}:{lo % 60:02d}-{hi // 60}:{hi % 60:02d}")
        for s in stops:
            f = m._fact(s, facts)
            if f is None:
                out.append(f"D{d['day']}: '{s['name']}' not found on Google Places")
            elif f.get("closed_permanently"):
                out.append(f"D{d['day']}: '{s['name']}' is permanently closed")
            elif s.get("start") is not None and m.is_open(
                    f.get("periods"), day, s["start"], s["start"] + (s.get("stay_minutes") or 0)) is False:
                out.append(f"D{d['day']}: '{s['name']}' closed at {s['start'] // 60}:{s['start'] % 60:02d}")
        for a, b in itertools.pairwise(stops):
            ca, cb = m._coords(a, facts), m._coords(b, facts)
            if ca and cb and (km := m.haversine_km(*ca, *cb)) > 8:
                out.append(f"D{d['day']}: {km:.1f}km leg '{a['name']}' -> '{b['name']}'")
            if ca and cb and a.get("start") is not None and b.get("start") is not None:
                gap = b["start"] - a["start"] - (a.get("stay_minutes") or 0)
                if gap <= 0:
                    out.append(f"D{d['day']}: no travel time '{a['name']}' -> '{b['name']}' (gap {gap}min)")
    return out


def cmd_report(args):
    scored = [json.loads(line) for line in (args.out / "scored.jsonl").read_text().splitlines()]
    facts = json.loads((args.out / "facts.json").read_text())
    scs = [s for s in json.loads(SCENARIOS.read_text()) if not args.only or s["id"] in args.only]
    every = {s["id"] for s in scs}
    vs, label = args.vs, LABELS[args.vs]
    scored = [r for r in scored if r["arm"] in ("seoulfit", vs)]
    n_sf = sum(r["arm"] == "seoulfit" for r in scored)
    header = (f"Itineraries scored: {len(scored)} (SeoulFit {n_sf}, {label} {len(scored) - n_sf}; "
              f"GPT model {GPT_MODEL}). "
              f"Δ = SeoulFit − {label}, paired per scenario with reps averaged; p = two-sided sign test.")
    lines = [f"# SeoulFit vs {label} benchmark", "", header,
             "", "## 6.1 지표별 비교 (전체 시나리오)", "", _table(scored, every, vs=vs)]

    lines += ["", "## 6.2 시나리오 유형별 분석", ""]
    for axis, levels in AXES.items():
        lines += [f"### {axis}", "", f"| 수준 | n | SeoulFit | {label} | Δ |", "|---|---|---|---|---|"]
        for level in levels:
            ids = {s["id"] for s in scs if s["set"] == "pairwise" and s.get(axis) == level}
            pairs = _paired(scored, "Score", ids, vs)
            if pairs:
                a, b = (sum(x) / len(pairs) for x in zip(*pairs))
                lines.append(f"| {level} | {len(pairs)} | {a:.3f} | {b:.3f} | {a - b:+.3f} |")
        lines.append("")
    lines += ["### 스트레스 세트", "", f"| ID | 시나리오 | 겨냥 지표 | SeoulFit | {label} | Score SeoulFit | Score {label} |",
              "|---|---|---|---|---|---|---|"]
    for s in scs:
        if s["set"] != "stress":
            continue
        probe = _paired(scored, s["probe"], {s["id"]}, vs)
        score = _paired(scored, "Score", {s["id"]}, vs)
        if probe:
            lines.append(f"| {s['id']} | {s['name']} | {s['probe']} | {probe[0][0]:.3f} | {probe[0][1]:.3f} "
                         f"| {score[0][0]:.3f} | {score[0][1]:.3f} |")
    people = [s for s in scs if s["set"] == "persona"]
    if people:
        lines += ["", "### 페르소나 세트", "", f"| ID | 페르소나 | 일수 | Score SeoulFit | Score {label} | F | ECS | FG (SeoulFit / {label}) |",
                  "|---|---|---|---|---|---|---|---|"]
        for s in people:
            cells = {k: _paired(scored, k, {s["id"]}, vs) for k in ("Score", "F", "ECS", "FG")}
            if cells["Score"]:
                both = {k: f"{v[0][0]:.3f} / {v[0][1]:.3f}" for k, v in cells.items()}
                lines.append(f"| {s['id']} | {s['name']} | {s['days']} | {cells['Score'][0][0]:.3f} "
                             f"| {cells['Score'][0][1]:.3f} | {both['F']} | {both['ECS']} | {both['FG']} |")

    lines += ["", "## 6.3 실패 사례 분석", ""]
    runs = {(r["arm"], r["scenario_id"], r["rep"]): r for r in latest_ok(args.out, args.only)}
    for arm, arm_label in (("seoulfit", "SeoulFit"), (vs, label)):
        lines += [f"### {arm_label}: Score 하위 3건", ""]
        worst = sorted((r for r in scored if r["arm"] == arm), key=lambda r: r["scores"]["Score"])[:3]
        for r in worst:
            sub = {k: v for k, v in r["scores"].items() if k not in ("F", "ECS", "FG", "Score")}
            low = ", ".join(f"{k} {v:.2f}" for k, v in sorted(sub.items(), key=lambda kv: kv[1])[:3])
            lines.append(f"- **{r['scenario_id']} rep{r['rep']}** Score {r['scores']['Score']:.3f} — 최저 지표: {low}")
            for reason in diagnose(runs[(arm, r["scenario_id"], r["rep"])]["itinerary"], facts)[:6]:
                lines.append(f"  - {reason}")
        lines.append("")
    matched = sum(f["found"] for f in facts.values())
    hours = sum(bool(f.get("periods")) for f in facts.values())
    failed = sum("label_error" in f for f in facts.values())
    lines += ["## 부록: 검증 커버리지", "",
              f"Google Places 매칭 {matched}/{len(facts)}곳; 영업시간 있음 {hours}곳; 라벨 실패 {failed}곳."]
    out_path = args.out / ("report.md" if vs == "gpt" else f"report_{vs}.md")
    out_path.write_text("\n".join(lines) + "\n")
    print(f"wrote {out_path}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scenarios")
    g = sub.add_parser("gen")
    g.add_argument("--arm", choices=ARMS, required=True)
    g.add_argument("--reps", type=int, default=1)
    g.add_argument("--limit", type=int)
    g.add_argument("--only", nargs="*", help="scenario ids, e.g. P01 X3")
    for name in ("gen", "verify", "score", "report"):
        p = g if name == "gen" else sub.add_parser(name)
        p.add_argument("--out", type=Path, required=True)
        if name != "gen":
            p.add_argument("--only", nargs="*", help="limit to these scenario ids")
        if name == "report":
            p.add_argument("--vs", choices=("gpt", "gpt_rules"), default="gpt")
    args = ap.parse_args()
    if args.cmd == "scenarios":
        scs = build_scenarios()
        SCENARIOS.write_text(json.dumps(scs, ensure_ascii=False, indent=1))
        print(f"{len(scs)} scenarios ({sum(s['set'] == 'pairwise' for s in scs)} pairwise) -> {SCENARIOS}")
        return
    {"gen": cmd_gen, "verify": cmd_verify, "score": cmd_score, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
