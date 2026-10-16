"""SeoulFit benchmark metrics: F(p), ECS(p), FG(p) and their 13 sub-metrics.

Pure functions, no API calls. Both arms (SeoulFit and GPT-4o) are scored from
the same normalized itinerary and the same Google-Places-derived facts, so
neither system's own database decides its score.

Normalized itinerary:
    {"days": [{"day": 1, "date": "2026-11-02", "stops": [
        {"name", "type", "lat", "lng", "start": minutes from 00:00,
         "stay_minutes", "meal_slot": "lunch"|"dinner"|None, "notes"}]}]}

facts: {normalize(name): {"found": bool, "lat", "lng", "periods": [...]|None,
        "serves_vegetarian": bool|None, "english_support": 1|0|None,
        "cash_only": 1|0|None, "reservation_required": 1|0|None,
        "cultural_friction": 1|0|None}}
A stop with no entry, or found=False, is "DB 미매칭".

Definitions the slides left open are this study's own and are marked "defined
here"; see backend/evals/README.md.
"""
import itertools
import math
import re
from datetime import date

# MEAL_SLOTS in meal_slots.py (lunch 11:00-13:30, dinner 18:00-20:00).
MEAL_WINDOWS = {"lunch": (11 * 60, 13 * 60 + 30), "dinner": (18 * 60, 20 * 60)}

# Activity category per POI type. The GPT prompt is given the same type enum.
CATEGORY = {
    "tourist_spot": "sight", "park": "sight", "street": "sight", "history": "sight",
    "culture": "sight", "nature": "sight", "kpop_landmark": "sight", "palace": "sight",
    "museum": "museum",
    "restaurant": "meal", "food": "meal",
    "market": "market",
    "cafe": "cafe",
    "shopping": "shopping", "shopping_mall": "shopping",
    "nightlife": "nightlife", "bar": "nightlife",
}

# VD: acceptable stay range in minutes per category (defined here).
STAY_RANGE = {
    "sight": (45, 150), "museum": (60, 180), "cafe": (30, 75), "meal": (45, 100),
    "shopping": (45, 150), "market": (45, 120), "nightlife": (60, 240),
}

# FS: transition pairs over flow categories (defined here). museum counts as
# sight, market as meal.
GOOD = {
    ("sight", "meal"), ("meal", "sight"), ("meal", "cafe"), ("cafe", "sight"),
    ("sight", "cafe"), ("shopping", "meal"), ("meal", "shopping"), ("sight", "shopping"),
}
BAD = {("cafe", "meal"), ("nightlife", "sight")}

FG_WEIGHTS = {"LA": 0.40, "MB": 0.20, "CC": 0.15, "AB": 0.15, "CF": 0.10}

# Itinerary notes that address a barrier ("guided"). Keyword lists defined here.
# Word-bounded: "discover" must not read as "cover", nor "bookstore" as "book".
_BARRIER_RE = re.compile(
    r"\b(reserv\w*|book(ing|ed)?|cash|cards?|sells? out|queues?|wait(ing)?)\b", re.IGNORECASE)
_FRICTION_RE = re.compile(
    r"\b(shoes?|floor|sit(ting)?|seat(ing|s)?|order(ing)?|per person|minimum|kiosks?|"
    r"ticket machines?|self[- ]service|etiquette|bow(ing)?|dress code|share|banchan|tips?)\b",
    re.IGNORECASE)


def normalize(name):
    return re.sub(r"[^0-9a-z가-힣]", "", (name or "").lower())


def haversine_km(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def _fact(stop, facts):
    f = facts.get(normalize(stop.get("name"))) or {}
    return f if f.get("found") else None


def _coords(stop, facts):
    """Places geometry when matched, else what the system itself gave."""
    f = _fact(stop, facts)
    for src in (f or {}, stop):
        try:
            return float(src["lat"]), float(src["lng"])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _legs(stops, facts):
    """Straight-line km of each consecutive pair that has coordinates on both ends."""
    pts = [_coords(s, facts) for s in stops]
    return [haversine_km(*a, *b) for a, b in itertools.pairwise(pts) if a and b]


def _category(stop):
    return CATEGORY.get((stop.get("type") or "").lower(), "sight")


def _flow(stop):
    c = _category(stop)
    return {"museum": "sight", "market": "meal"}.get(c, c)


def _mean(xs, empty=1.0):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else empty


def _linear(x, good, bad):
    """1 at or below `good`, 0 at or above `bad`, linear between."""
    if x <= good:
        return 1.0
    if x >= bad:
        return 0.0
    return 1 - (x - good) / (bad - good)


# --------------------------------------------------------------------- F(p)

def mc(days):
    """Share of (day, lunch|dinner) slots with a meal stop starting in its window."""
    hits = 0
    for d in days:
        for lo, hi in MEAL_WINDOWS.values():
            hits += any((s.get("meal_slot") or _flow(s) == "meal") and s.get("start") is not None
                        and lo <= s["start"] <= hi for s in d["stops"])
    return hits / (2 * len(days)) if days else 0.0


def tf_leg(gap, km):
    need = max(10.0, 8 + 7 * km)
    if gap <= 0:
        return 0.0
    r = gap / need
    if r < 1.0:
        return min(0.78, 0.78 * r)
    if r < 1.25:
        return 0.82 + (r - 1.0) / 0.25 * 0.08
    if r < 1.75:
        return 0.90 + (r - 1.25) / 0.50 * 0.06
    return 0.98


def tf(days, facts):
    """Per leg: gap = next start - (this start + stay), against need(km)."""
    scores = []
    for d in days:
        for a, b in itertools.pairwise(d["stops"]):
            ca, cb = _coords(a, facts), _coords(b, facts)
            if ca is None or cb is None or a.get("start") is None or b.get("start") is None:
                continue
            gap = b["start"] - (a["start"] + (a.get("stay_minutes") or 0))
            scores.append(tf_leg(gap, haversine_km(*ca, *cb)))
    return _mean(scores)


def is_open(periods, day, start, end):
    """True/False whether [start, end] minutes on `day` sits inside one opening
    period (Google legacy `periods`, day 0 = Sunday); None with no periods."""
    if not periods:
        return None
    week = 7 * 1440
    g = (day.weekday() + 1) % 7
    lo, hi = g * 1440 + start, g * 1440 + end
    for p in periods:
        o = p.get("open") or {}
        if "close" not in p and o.get("time") == "0000":
            return True  # open 24 hours
        c = p.get("close") or {}
        try:
            po = o["day"] * 1440 + int(o["time"][:2]) * 60 + int(o["time"][2:])
            pc = c["day"] * 1440 + int(c["time"][:2]) * 60 + int(c["time"][2:])
        except (KeyError, TypeError, ValueError):
            continue
        if pc <= po:
            pc += week
        if any(po <= lo + k and hi + k <= pc for k in (0, week)):
            return True
    return False


def oh(days, facts):
    ok = conflict = unknown = 0
    for d in days:
        day = date.fromisoformat(d["date"])
        for s in d["stops"]:
            f = _fact(s, facts)
            res = None
            if f and f.get("closed_permanently"):
                res = False
            elif f and s.get("start") is not None:
                res = is_open(f.get("periods"), day, s["start"], s["start"] + (s.get("stay_minutes") or 0))
            if res is None:
                unknown += 1
            elif res:
                ok += 1
            else:
                conflict += 1
    n = ok + conflict + unknown
    return (ok + 0.5 * unknown) / n if n else 1.0


# ------------------------------------------------------------------- ECS(p)

def rd(days, facts):
    legs = [km for d in days for km in _legs(d["stops"], facts)]
    return _linear(_mean(legs, 0.0), 1, 8)


def vd(days):
    ok = fail = unknown = 0
    for d in days:
        for s in d["stops"]:
            stay = s.get("stay_minutes")
            if not stay:
                unknown += 1
                continue
            lo, hi = STAY_RANGE[_category(s)]
            if lo <= stay <= hi:
                ok += 1
            else:
                fail += 1
    n = ok + fail + unknown
    return (ok + 0.7 * unknown) / n if n else 1.0


def _path_km(pts):
    return sum(haversine_km(*a, *b) for a, b in itertools.pairwise(pts))


def ss_day(pts):
    """Nearest-neighbour route from the same first stop vs the actual route, capped at 1.

    ponytail: NN is a heuristic, so the actual order can beat it; the cap keeps
    that at 1.0. Swap in exact TSP if days ever exceed ~10 stops and it matters."""
    actual = _path_km(pts)
    if actual == 0:
        return 1.0
    rest, route = list(pts[1:]), [pts[0]]
    while rest:
        nxt = min(rest, key=lambda p: haversine_km(*route[-1], *p))
        rest.remove(nxt)
        route.append(nxt)
    return min(1.0, _path_km(route) / actual)


def ss(days, facts):
    return _mean(ss_day([c for s in d["stops"] if (c := _coords(s, facts))]) for d in days)


def cp_day(pts):
    """0.65 * f_avg(mean leg km) + 0.35 * f_max(max pairwise km).
    f_avg = RD's curve (1-8km); f_max is 1 up to 3km, 0 from 12km (defined here)."""
    if len(pts) < 2:
        return 1.0
    legs = [haversine_km(*a, *b) for a, b in itertools.pairwise(pts)]
    spread = max(haversine_km(*a, *b) for a, b in itertools.combinations(pts, 2))
    return 0.65 * _linear(_mean(legs), 1, 8) + 0.35 * _linear(spread, 3, 12)


def cp(days, facts):
    return _mean(cp_day([c for s in d["stops"] if (c := _coords(s, facts))]) for d in days)


def fs_day(stops):
    """Mean transition score x p; p = 0.8 when one category is over 60% of the
    day's stops, else 1.0 (defined here)."""
    cats = [_flow(s) for s in stops]
    if len(cats) < 2:
        return 1.0
    pair_scores = []
    for a, b in itertools.pairwise(cats):
        if (a, b) in GOOD:
            pair_scores.append(1.0)
        elif (a, b) in BAD or a == b:
            pair_scores.append(0.35)
        else:
            pair_scores.append(0.75)
    top = max(cats.count(c) for c in set(cats))
    p = 0.8 if top / len(cats) > 0.6 else 1.0
    return _mean(pair_scores) * p


def fs(days):
    return _mean(fs_day(d["stops"]) for d in days)


# -------------------------------------------------------------------- FG(p)

def _all_stops(days):
    return [s for d in days for s in d["stops"]]


def la(days, facts):
    su = ns = unk = 0
    for s in _all_stops(days):
        v = (_fact(s, facts) or {}).get("english_support")
        if v == 1:
            su += 1
        elif v == 0:
            ns += 1
        else:
            unk += 1
    total = su + ns + unk
    return (su + 0.5 * unk) / total if total else 1.0


def mb_leg(km):
    for limit, score in ((1, 1.0), (3, 0.85), (5, 0.65), (8, 0.40)):
        if km <= limit:
            return score
    return 0.20


def mb(days, facts):
    return _mean(mb_leg(km) for d in days for km in _legs(d["stops"], facts))


def diet_verdict(fact, diet):
    """True/False/None for one meal stop. Evidence is Google's
    serves_vegetarian_food (vegetarian only; it says nothing about vegan) and
    the review-based label; Google wins when they disagree. The itinerary's own
    note is NOT evidence (defined here): both arms write their notes, and in the
    smoke run GPT-4o called a samgyetang (chicken soup) house "vegan-friendly"."""
    if fact is None:
        return None
    google = fact.get("serves_vegetarian") if diet == "vegetarian" else None
    if google is not None:
        return google
    label = fact.get(diet)
    return None if label is None else bool(label)


def cc(days, facts, diet):
    """Meal stops vs the traveller's diet: ok 1, unknown 0.7, fail 0."""
    if not diet:
        return 1.0
    ok = sk = total = 0
    for s in _all_stops(days):
        if not (s.get("meal_slot") or _flow(s) == "meal" or _category(s) == "cafe"):
            continue
        total += 1
        v = diet_verdict(_fact(s, facts), diet)
        if v is True:
            ok += 1
        elif v is None:
            sk += 1
    return (ok + 0.7 * sk) / total if total else 1.0


def ab_stop(stop, fact):
    guided = bool(_BARRIER_RE.search(stop.get("notes") or ""))
    if fact is None:
        return 0.65 if guided else 0.30
    res, cash = fact.get("reservation_required"), fact.get("cash_only")
    if res is None and cash is None:
        return 0.75 if guided else 0.60
    if res == 1 or cash == 1:
        return 0.95 if guided else 0.55
    return 1.0


def ab(days, facts):
    return _mean(ab_stop(s, _fact(s, facts)) for s in _all_stops(days))


def cf_stop(stop, fact):
    """has_tip: the note names the specific friction (shoes, floor seating, order
    rules...). guided: a note of 80+ characters. Both defined here."""
    notes = stop.get("notes") or ""
    has_tip = bool(_FRICTION_RE.search(notes))
    guided = has_tip or len(notes) >= 80
    if fact is None:
        return 0.70 if guided else 0.45
    friction = fact.get("cultural_friction")
    if friction is None:
        return 0.75 if guided else 0.55
    if friction == 0:
        return 1.0
    if has_tip:
        return 1.0
    return 0.90 if guided else 0.35


def cf(days, facts):
    return _mean(cf_stop(s, _fact(s, facts)) for s in _all_stops(days))


# -------------------------------------------------------------------- total

def score(itinerary, facts, diet=None):
    """All 13 sub-metrics, the three axes and Score(p), rounded to 3 places."""
    days = itinerary.get("days") or []
    out = {
        "MC": mc(days), "TF": tf(days, facts), "OH": oh(days, facts),
        "RD": rd(days, facts), "VD": vd(days), "SS": ss(days, facts),
        "CP": cp(days, facts), "FS": fs(days),
        "LA": la(days, facts), "MB": mb(days, facts), "CC": cc(days, facts, diet),
        "AB": ab(days, facts), "CF": cf(days, facts),
    }
    out["F"] = (out["MC"] + out["TF"] + out["OH"]) / 3
    out["ECS"] = (out["RD"] + out["VD"] + out["SS"] + out["CP"] + out["FS"]) / 5
    out["FG"] = sum(FG_WEIGHTS[k] * out[k] for k in FG_WEIGHTS)
    out["Score"] = (out["F"] + out["ECS"] + out["FG"]) / 3
    return {k: round(v, 3) for k, v in out.items()}
