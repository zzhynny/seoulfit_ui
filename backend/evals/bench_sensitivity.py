"""Chapter 7 robustness: re-score the saved persona runs under changed scoring
parameters. No generation, no API calls: itineraries and facts.json are reused.

    venv/bin/python evals/bench_sensitivity.py [--out evals/out/bench_persona]

Writes <out>/sensitivity.md. The baseline variant must reproduce scored.jsonl.
"""
import argparse
import json
from contextlib import contextmanager
from pathlib import Path

import bench_metrics as m
import bench_run
from ab_score import sign_test

SUBS = {
    "MC": lambda d, f, diet: m.mc(d), "TF": lambda d, f, diet: m.tf(d, f),
    "OH": lambda d, f, diet: m.oh(d, f), "RD": lambda d, f, diet: m.rd(d, f),
    "VD": lambda d, f, diet: m.vd(d), "SS": lambda d, f, diet: m.ss(d, f),
    "CP": lambda d, f, diet: m.cp(d, f), "FS": lambda d, f, diet: m.fs(d),
    "LA": lambda d, f, diet: m.la(d, f), "MB": lambda d, f, diet: m.mb(d, f),
    "CC": lambda d, f, diet: m.cc(d, f, diet), "AB": lambda d, f, diet: m.ab(d, f),
    "CF": lambda d, f, diet: m.cf(d, f),
}
AXES = {"F": ["MC", "TF", "OH"], "ECS": ["RD", "VD", "SS", "CP", "FS"],
        "FG": ["LA", "MB", "CC", "AB", "CF"]}
_LINEAR, _MB_LEG = m._linear, m.mb_leg


def unknown(oh_la, vd_cc):
    return {"OH": oh_la, "LA": oh_la, "VD": vd_cc, "CC": vd_cc}


def meals(lunch, dinner):
    h = lambda t: int(t[:2]) * 60 + int(t[3:])
    return {"lunch": (h(lunch[0]), h(lunch[1])), "dinner": (h(dinner[0]), h(dinner[1]))}


# (section, label, module patches, compose options)
VARIANTS = [
    ("기준", "본문 설정", {}, {}),
    ("7.2", "식사 시간대 ±30분 확대", {"MEAL_WINDOWS": meals(("10:30", "14:00"), ("17:30", "20:30"))}, {}),
    ("7.2", "식사 시간대 ±60분 확대", {"MEAL_WINDOWS": meals(("10:00", "14:30"), ("17:00", "21:00"))}, {}),
    ("7.2", "식사 시간대 30분 축소", {"MEAL_WINDOWS": meals(("11:30", "13:00"), ("18:30", "19:30"))}, {}),
    ("7.2", "이동시간 기준 완화 max(5, 4+4km)", {"TF_NEED": (5.0, 4, 4)}, {}),
    ("7.2", "이동시간 기준 강화 max(15, 12+10km)", {"TF_NEED": (15.0, 12, 10)}, {}),
    ("7.2", "식사 ±60분 + 이동시간 완화", {"MEAL_WINDOWS": meals(("10:00", "14:30"), ("17:00", "21:00")),
                                     "TF_NEED": (5.0, 4, 4)}, {}),
    ("7.2", "MC·TF 제외", {}, {"drop": {"MC", "TF"}}),
    ("7.3", "미확인 = 0 (결측을 실패로)", {"UNKNOWN": unknown(0.0, 0.0)}, {}),
    ("7.3", "미확인 −0.2", {"UNKNOWN": unknown(0.3, 0.5)}, {}),
    ("7.3", "미확인 +0.2", {"UNKNOWN": unknown(0.7, 0.9)}, {}),
    ("7.3", "미확인 = 1 (결측을 충족으로)", {"UNKNOWN": unknown(1.0, 1.0)}, {}),
    ("7.3", "거리 임계값 ×0.5", {"DIST": 0.5}, {}),
    ("7.3", "거리 임계값 ×1.5", {"DIST": 1.5}, {}),
    ("7.4", "FG 균등 가중치", {"FG_WEIGHTS": dict.fromkeys(AXES["FG"], 0.2)}, {}),
    ("7.4", "축 가중치 F 0.5", {}, {"axis_w": {"F": 0.5, "ECS": 0.25, "FG": 0.25}}),
    ("7.4", "축 가중치 ECS 0.5", {}, {"axis_w": {"F": 0.25, "ECS": 0.5, "FG": 0.25}}),
    ("7.4", "축 가중치 FG 0.5", {}, {"axis_w": {"F": 0.25, "ECS": 0.25, "FG": 0.5}}),
    ("7.4", "FG 축 제외", {}, {"axis_w": {"F": 0.5, "ECS": 0.5, "FG": 0.0}}),
    ("7.4", "13개 지표 단순 평균", {}, {"flat": True}),
] + [("7.5", f"{k} 제외", {}, {"drop": {k}}) for k in SUBS]


@contextmanager
def patched(patches):
    saved = {}
    for k, v in patches.items():
        if k == "DIST":
            saved["_linear"], saved["mb_leg"] = m._linear, m.mb_leg
            m._linear = lambda x, good, bad, s=v: _LINEAR(x, good * s, bad * s)
            m.mb_leg = lambda km, s=v: _MB_LEG(km / s)
        else:
            saved[k] = getattr(m, k)
            setattr(m, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(m, k, v)


def compose(subs, axis_w=None, drop=(), flat=False):
    """Axes and Score from unrounded sub-metrics; dropped metrics leave their
    axis, FG weights renormalise over what is left."""
    keep = {k: v for k, v in subs.items() if k not in drop}
    if flat:
        return {"Score": sum(keep.values()) / len(keep)}
    out = {}
    for axis, ks in AXES.items():
        ks = [k for k in ks if k in keep]
        if axis == "FG":
            w = {k: m.FG_WEIGHTS[k] for k in ks}
            out[axis] = sum(w[k] * keep[k] for k in ks) / sum(w.values())
        else:
            out[axis] = sum(keep[k] for k in ks) / len(ks)
    axis_w = axis_w or dict.fromkeys(AXES, 1.0)
    out["Score"] = sum(axis_w[a] * out[a] for a in AXES) / sum(axis_w.values())
    return out


def stats(pairs):
    diffs = [a - b for a, b in pairs]
    w, l = sum(d > 0.0005 for d in diffs), sum(d < -0.0005 for d in diffs)
    lo, hi = bench_run._ci(diffs)
    return {"sf": sum(a for a, _ in pairs) / len(pairs), "vs": sum(b for _, b in pairs) / len(pairs),
            "d": sum(diffs) / len(diffs), "lo": lo, "hi": hi, "w": w, "l": l,
            "t": len(diffs) - w - l, "p": sign_test(w, l)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=bench_run.HERE / "out" / "bench_persona")
    args = ap.parse_args()
    # backend/ is on sys.path once bench_run is imported
    from meal_slots import parse_diet
    facts = json.loads((args.out / "facts.json").read_text())
    scs = {s["id"]: s for s in json.loads(bench_run.SCENARIOS.read_text())}
    runs = bench_run.latest_ok(args.out, None)
    diet = {sid: parse_diet(s["restrictions"]) if s.get("restrictions") else None for sid, s in scs.items()}

    results = []
    for section, label, patches, opts in VARIANTS:
        with patched(patches):
            score = {(r["arm"], r["scenario_id"]): compose(
                {k: f(r["itinerary"]["days"], facts, diet[r["scenario_id"]]) for k, f in SUBS.items()}, **opts)
                for r in runs}
        if section == "기준":  # self-check: baseline reproduces the paper's scored.jsonl
            for line in (args.out / "scored.jsonl").read_text().splitlines():
                old = json.loads(line)
                got = score[(old["arm"], old["scenario_id"])]["Score"]
                assert abs(got - old["scores"]["Score"]) <= 0.0006, (old["arm"], old["scenario_id"], got)
        ids = sorted({sid for _, sid in score})
        res = {"section": section, "label": label}
        for vs in ("gpt", "gpt_rules"):
            for metric in ("Score", "F"):
                if metric in score[("seoulfit", ids[0])]:
                    res[(vs, metric)] = stats([(score[("seoulfit", i)][metric], score[(vs, i)][metric]) for i in ids])
        results.append(res)

    def row(r, vs):
        s = r[(vs, "Score")]
        f = r.get((vs, "F"))
        keep = "유지" if s["lo"] > 0 and s["p"] < 0.05 else ("방향 유지" if s["d"] > 0 else "역전")
        fcell = f"{f['d']:+.3f} ({f['w']}/{f['l']}/{f['t']})" if f else "–"
        return (f"| {r['section']} | {r['label']} | {s['vs']:.3f} | {s['sf']:.3f} | {s['d']:+.3f} "
                f"| [{s['lo']:+.3f}, {s['hi']:+.3f}] | {s['w']}/{s['l']}/{s['t']} | {s['p']:.3f} | {fcell} | {keep} |")

    lines = ["# 7장 민감도 분석", "",
             (f"저장된 일정 {len(runs)}개를 재채점. Δ = SeoulFit − 비교군, 페르소나별 짝비교 n = {len(ids)}, "
              "95% CI = 부트스트랩 2,000회, p = 양측 부호검정. 판정: 유지 = CI가 0 초과이고 p < 0.05."), ""]
    for vs, title in (("gpt", "GPT (규칙 없음)"), ("gpt_rules", "GPT (규칙 제공)")):
        lines += [f"## SeoulFit vs {title}", "",
                  "| 절 | 조건 | 비교군 | SeoulFit | Δ 종합 | 95% CI | 승/패/무 | p | Δ F (승/패/무) | 판정 |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        lines += [row(r, vs) for r in results] + [""]
    path = args.out / "sensitivity.md"
    path.write_text("\n".join(lines))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
