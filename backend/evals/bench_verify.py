"""Facts for every stop the benchmark itineraries actually contain, from Google
Places (legacy API -- the New API is disabled on this key) plus a Gemini label
pass over Google's own reviews.

Both arms go through this one path, so a stop's facts never depend on which
system proposed it. The labeler sees only the place's name, Google types,
summary and reviews -- never the itinerary or which arm it came from.

Cached per normalized name in <run>/facts.json; a rerun only looks up names it
hasn't seen, and the cache is what makes the labels reproducible.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor

import bench_metrics as m

DETAILS_FIELDS = ("name,geometry,types,business_status,opening_hours,"
                  "serves_vegetarian_food,reservable,editorial_summary,reviews")
# Greater Seoul; a match outside this is a same-named place elsewhere, i.e. no match.
SEOUL_LAT, SEOUL_LNG = (37.3, 37.8), (126.6, 127.3)
LABEL_KEYS = ("english_support", "cash_only", "reservation_required", "cultural_friction",
              "vegetarian", "vegan", "halal")

LABEL_PROMPT = """You label one place in Seoul for foreign visitors. Use ONLY the
evidence below (Google data and reviews). If the evidence does not say, answer null --
do not guess from the kind of place.

- english_support: 1 if staff, menus or signage work in English; 0 if reviewers report
  they don't (Korean-only menu, no English spoken); null otherwise.
- cash_only: 1 if cash is the only payment; 0 if cards are accepted; null otherwise.
- reservation_required: 1 if you can't get in without booking ahead; 0 if walk-ins work;
  null otherwise.
- cultural_friction: 1 if a first-time foreign visitor would hit a local custom here
  (floor seating / shoes off, one-menu-per-person or minimum order, ordering at a
  Korean-only kiosk, strict etiquette); 0 if reviews describe a standard visit; null
  otherwise.
- vegetarian / vegan / halal: 1 if a traveller with that diet can get a proper meal
  here; 0 if the menu is built around what they can't eat (e.g. a chicken-soup or
  barbecue house for vegetarians); null if it's not a place to eat or the evidence
  doesn't say.

Return JSON: {"english_support": 1|0|null, "cash_only": 1|0|null,
"reservation_required": 1|0|null, "cultural_friction": 1|0|null,
"vegetarian": 1|0|null, "vegan": 1|0|null, "halal": 1|0|null, "evidence": "<one sentence>"}

Evidence:
"""


def _find_place(planner, stop):
    """place_id of the best Google match, biased to the stop's own point when it
    has one (2km), else to all of Seoul."""
    try:
        bias = f"circle:2000@{float(stop['lat'])},{float(stop['lng'])}"
    except (KeyError, TypeError, ValueError):
        bias = planner._SEOUL_BIAS
    data = planner._google_get(
        "https://maps.googleapis.com/maps/api/place/findplacefromtext/json",
        {"input": stop["name"], "inputtype": "textquery", "fields": "place_id",
         "locationbias": bias, "language": "en", "key": planner.GOOGLE_PLACES_API_KEY})
    cands = data.get("candidates") or []
    return cands[0].get("place_id") if cands else None


def _details(planner, place_id):
    data = planner._google_get(
        "https://maps.googleapis.com/maps/api/place/details/json",
        {"place_id": place_id, "fields": DETAILS_FIELDS, "language": "en",
         "key": planner.GOOGLE_PLACES_API_KEY})
    return data.get("result") or {}


def _label(planner, d):
    evidence = {
        "name": d.get("name"), "types": d.get("types"),
        "summary": (d.get("editorial_summary") or {}).get("overview"),
        "reservable": d.get("reservable"),
        "reviews": [r.get("text", "")[:600] for r in d.get("reviews") or []],
    }
    raw = planner._gemini_text(LABEL_PROMPT + json.dumps(evidence, ensure_ascii=False))
    out = json.loads(re.sub(r"```(?:json)?", "", raw).strip())
    labels = {k: out.get(k) if out.get(k) in (0, 1) else None for k in LABEL_KEYS}
    labels["evidence"] = out.get("evidence")
    return labels


def fact_for(planner, stop):
    """One stop -> its facts row. found=False is the rubric's "DB 미매칭".
    A stop that already carries a place_id (the course data's verified match)
    skips Find Place; benchmark stops never do."""
    place_id = stop.get("place_id") or _find_place(planner, stop)
    if not place_id:
        return {"found": False, "query": stop["name"]}
    d = _details(planner, place_id)
    if not d:
        return {"found": False, "query": stop["name"], "place_id": place_id}
    loc = (d.get("geometry") or {}).get("location") or {}
    # locationbias is a hint, not a filter: "Bourbon Street" came back as New Orleans.
    if not (SEOUL_LAT[0] <= (loc.get("lat") or 0) <= SEOUL_LAT[1]
            and SEOUL_LNG[0] <= (loc.get("lng") or 0) <= SEOUL_LNG[1]):
        return {"found": False, "query": stop["name"], "place_id": place_id,
                "outside_seoul": d.get("name")}
    row = {
        "found": True, "query": stop["name"], "place_id": place_id,
        "google_name": d.get("name"), "lat": loc.get("lat"), "lng": loc.get("lng"),
        "types": d.get("types"),
        "closed_permanently": d.get("business_status") == "CLOSED_PERMANENTLY",
        "periods": (d.get("opening_hours") or {}).get("periods"),
        "serves_vegetarian": d.get("serves_vegetarian_food"),
        "reservable": d.get("reservable"),
    }
    try:
        row.update(_label(planner, d))
    except Exception as e:  # noqa: BLE001 -- an unlabeled stop scores as unknown, not a crash
        row.update(dict.fromkeys(LABEL_KEYS), label_error=f"{type(e).__name__}: {e}")
    return row


def verify(planner, stops, cache_path, workers=6):
    """Look up every stop name not yet in the cache; returns the full cache.

    ponytail: keyed by name, so two different "Starbucks" in one run share the
    first one's facts. Key by (name, rounded coords) if chains start to matter."""
    facts = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    todo = {}
    for s in stops:
        key = m.normalize(s.get("name"))
        if key and key not in facts:
            todo.setdefault(key, s)
    print(f"verify: {len(todo)} new places, {len(facts)} cached")
    with ThreadPoolExecutor(workers) as pool:
        for i, (key, row) in enumerate(zip(todo, pool.map(lambda s: fact_for(planner, s), todo.values()))):
            facts[key] = row
            if i % 25 == 24:  # checkpoint so a crash doesn't throw away paid lookups
                cache_path.write_text(json.dumps(facts, ensure_ascii=False, indent=1))
    cache_path.write_text(json.dumps(facts, ensure_ascii=False, indent=1))
    return facts


def relabel(planner, cache_path, workers=6):
    """Redo only the entries whose label call failed (e.g. quota ran out). The
    cache keeps no review text, so Place Details is fetched again; found
    entries that labeled fine are not touched."""
    facts = json.loads(cache_path.read_text())
    todo = [k for k, v in facts.items() if v.get("found") and "label_error" in v]
    print(f"relabel: {len(todo)} to redo of {len(facts)}")

    def one(key):
        try:
            labels = _label(planner, _details(planner, facts[key]["place_id"]))
        except Exception as e:  # noqa: BLE001 -- stay unlabeled, keep the reason
            return {"label_error": f"{type(e).__name__}: {e}"}
        return labels

    with ThreadPoolExecutor(workers) as pool:
        for i, (key, res) in enumerate(zip(todo, pool.map(one, todo))):
            if "label_error" in res:
                facts[key]["label_error"] = res["label_error"]
            else:
                facts[key].pop("label_error", None)
                facts[key].update(res)
            if i % 25 == 24:
                cache_path.write_text(json.dumps(facts, ensure_ascii=False, indent=1))
    cache_path.write_text(json.dumps(facts, ensure_ascii=False, indent=1))
    left = sum("label_error" in facts[k] for k in todo)
    print(f"relabel: {len(todo) - left} fixed, {left} still failing")
    return facts
