"""Check dataset/course_descriptions.json against the courses it describes.

    python backend/scripts/validate_descriptions.py                    # default file
    python backend/scripts/validate_descriptions.py path/to/other.json
    python backend/scripts/validate_descriptions.py --demo             # self-check

Nobody is going to read 125 descriptions closely enough to catch a wrong
detail, so this checks what a machine can:

  - place names must belong to the course being described (a gazetteer of every
    POI across every course flags one borrowed from a different course)
  - `interests` must not omit a category the data plainly supports, and must
    come from the closed five-label vocabulary the app also uses
  - a course with no meal stop has to say so, and a halal/vegan course with no
    restaurant has to say that too — the failure mode is prose that quietly
    papers over what the itinerary cannot deliver
  - no marketing adjectives: they attach to any course and so tell retrieval
    nothing, which is worse than useless in an embedding

What it cannot check is whether the labels are apt. That still needs eyes.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

COURSE_DATA = _BACKEND / "dataset" / "course_data_v6.json"
DESCRIPTIONS = _BACKEND / "dataset" / "course_descriptions.json"

INTERESTS = [
    "Culture & History",
    "Food & Cafes",
    "Shopping",
    "K-POP & Hallyu",
    "Nature & Relaxation",
]
CONSTRAINTS = {"halal", "vegan", "vegetarian", "budget", "luxury", "wheelchair", "no_alcohol"}

MEAL_TYPES = {"restaurant", "cafe", "market"}
PURPOSE_MIN, PURPOSE_MAX = 60, 400
DESC_MIN, DESC_MAX = 80, 900

# Words that would sit equally well on any of the 125 courses. In an embedding
# they add distance without adding distinction.
MARKETING = [
    "must-see", "must-visit", "must-do", "hidden gem", "perfect for", "perfectly",
    "stunning", "breathtaking", "unforgettable", "vibrant", "charming", "iconic",
    "bustling", "picturesque", "quaint", "nestled", "delightful", "magical",
    "a feast for", "world-class", "unparalleled", "immerse yourself", "soak up",
    "something for everyone", "no trip is complete",
]

# Evidence rules per interest: (theme tags, poi types, name/title keywords).
# One matching POI is enough — thresholds were tried and broke at both ends,
# firing on everything in a one-POI day and never firing in a four-POI one.
RULES = [
    ("Culture & History", {"History", "Traditional", "Culture"}, {"history", "museum"},
     r"palace|gung\b|temple|shrine|fortress|city wall|tomb|prison|independence|memorial|"
     r"hanok|traditional|hansik|makgeolli|sool gallery|gugak|craft|hanbok|museum|gallery|"
     r"art (center|museum|tour)|univ|campus|library|history|heritage"),
    ("Food & Cafes", {"Food"}, {"restaurant", "cafe", "market"},
     r"alley|market|kalguksu|jokbal|tteokbokki|naengmyeon|sikdang|gourmet|culinary|"
     r"foodie|epicurean|cafe|coffee|teahouse|osulloc|dessert|brunch|food"),
    ("Shopping", {"Shopping"}, {"shopping"},
     r"mall|shopping|store|duty free|select shop|department"),
    ("K-POP & Hallyu", {"K-POP"}, {"kpop_landmark"},
     r"k-pop|kpop|hallyu|hybe|bts|blackpink|idol|k-star|hikr|filming|'s pick|demon hunter"),
    ("Nature & Relaxation", {"Nature", "Healing", "Nightlife"}, {"park", "nature"},
     r"mountain|forest|valley|trail|garden|hangang|eco|wetland|stream|"
     r"night|observatory|tower|cruise|seoul sky|rainbow|"
     r"spa|beauty|amore|sulwhasoo|jjimjilbang|therapy|k-medi|healing|wellness"),
]


# ---------------------------------------------------------------------------
# Facts, computed from the course data — never from the description
# ---------------------------------------------------------------------------

def name_variants(poi_name: str) -> list[str]:
    """'Seoul Forest (서울숲)' -> ['Seoul Forest (서울숲)', 'Seoul Forest', '서울숲']"""
    out = [poi_name.strip()]
    m = re.match(r"^(.*?)\s*\((.+)\)\s*$", poi_name.strip())
    if m:
        out += [m.group(1).strip(), m.group(2).strip()]
    return [v for v in out if v]


def evidence_interests(course: dict) -> set[str]:
    """Interests the data plainly supports. One matching POI is enough.

    Judged on POIs, not on `theme_category` or the course title. Both of those
    are course-level and a multi-day course repeats them on every day row, so
    they tag the arrival day that holds only Gwanghwamun Square as Shopping and
    Nature. The one exception is K-POP & Hallyu: a celebrity-pick or filming
    location course is hallyu because of what it is *about*, and its POIs are
    ordinary landmarks that carry no signal of it.
    """
    title = course["course_title"].lower()
    found: set[str] = set()
    for label, _themes, types, kw in RULES:
        pat = re.compile(kw)
        if label == "K-POP & Hallyu" and pat.search(title):
            found.add(label)
            continue
        for p in course["sequence"]:
            text = f"{p['poi_name']} {p.get('address_en') or ''}".lower()
            if p["poi_type"] in types or pat.search(text):
                found.add(label)
                break
    return found


def course_facts(course: dict) -> dict:
    pois = course["sequence"]
    return {
        "has_meal": any(p["poi_type"] in MEAL_TYPES for p in pois),
        "evidence": evidence_interests(course),
        "names": {v for p in pois for v in name_variants(p["poi_name"])},
        "days": 1,
        "pois": len(pois),
    }


def load_courses(path: Path = COURSE_DATA) -> dict[str, dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {c["course_id"]: course_facts(c) for c in raw}


def build_gazetteer(path: Path = COURSE_DATA) -> dict[str, set[str]]:
    """Place name -> the courses that contain it. Short names are skipped:
    they collide with ordinary words and every hit would be a false alarm."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    gaz: dict[str, set[str]] = {}
    for c in raw:
        for p in c["sequence"]:
            for v in name_variants(p["poi_name"]):
                if len(v) < (3 if re.search(r"[가-힣]", v) else 6):
                    continue
                gaz.setdefault(v, set()).add(c["course_id"])
    return gaz


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_one(entry: dict, facts: dict, gaz: dict[str, set[str]], cid: str) -> list[str]:
    errs: list[str] = []
    purpose = (entry.get("purpose") or "").strip()
    desc = (entry.get("description") or "").strip()
    prose = f"{purpose} {desc}"

    if not purpose:
        errs.append("purpose 없음")
    elif not (PURPOSE_MIN <= len(purpose) <= PURPOSE_MAX):
        errs.append(f"purpose {len(purpose)}자 — {PURPOSE_MIN}~{PURPOSE_MAX} 밖")
    if not desc:
        errs.append("description 없음")
    elif not (DESC_MIN <= len(desc) <= DESC_MAX):
        errs.append(f"description {len(desc)}자 — {DESC_MIN}~{DESC_MAX} 밖")
    if not prose.strip():
        return errs

    # 1. A place name that belongs to some other course and not this one.
    own = facts["names"]
    for term, owners in gaz.items():
        if term not in prose:
            continue
        if cid in owners or any(term in o or o in term for o in own):
            continue
        errs.append(f"이 코스에 없는 장소: '{term}' (실제 소유: {', '.join(sorted(owners)[:2])})")

    # 2. Marketing copy.
    low = prose.lower()
    for w in MARKETING:
        if w in low:
            errs.append(f"홍보 문구: '{w}'")

    # 3. Closed vocabularies.
    declared = entry.get("interests") or []
    if bad := [i for i in declared if i not in INTERESTS]:
        errs.append(f"interests 어휘 밖: {bad}")
    if not declared:
        errs.append("interests 비어 있음")
    if bad := sorted(set(entry.get("constraints") or []) - CONSTRAINTS):
        errs.append(f"constraints 어휘 밖: {bad}")

    # 4. Interests must not omit what the data plainly supports. Extra labels are
    #    allowed — the keyword rules miss things a reader catches — but a missing
    #    one means the course will not surface for an interest it actually serves.
    if missing := sorted(facts["evidence"] - set(declared)):
        errs.append(f"interests 누락(근거 있음): {missing}")

    # 5. Honesty. Only the two that change what the traveller can actually do.
    if not facts["has_meal"] and not re.search(r"meal|eat|food|restaurant|dining|lunch|dinner", low):
        errs.append("식사할 곳이 없는데 설명문이 언급하지 않음")
    if set(entry.get("constraints") or []) & {"halal", "vegan", "vegetarian"} and not facts["has_meal"]:
        if not re.search(r"no .{0,20}(restaurant|place to eat)|not listed|chosen on site|"
                         r"on your own|sourced separately", low):
            errs.append("제약을 걸어놓고 그 제약에 맞는 식사처가 없다는 사실을 안 적음")

    return errs


def validate(path: Path) -> int:
    facts_by_id = load_courses()
    gaz = build_gazetteer()
    doc = json.loads(path.read_text(encoding="utf-8"))
    entries = doc.get("courses") if isinstance(doc, dict) else doc
    by_id = {e.get("course_id"): e for e in entries}

    total = failed = 0
    for entry in entries:
        cid = entry.get("course_id", "")
        total += 1
        facts = facts_by_id.get(cid)
        if not facts:
            print(f"✗ {cid}: course_data_v6.json 에 없는 course_id")
            failed += 1
            continue
        errs = check_one(entry, facts, gaz, cid)
        if errs:
            failed += 1
            print(f"✗ {cid}")
            for e in errs:
                print(f"    - {e}")

    missing = sorted(set(facts_by_id) - set(by_id))
    dupes = len(entries) - len(by_id)
    print(f"\n{total - failed}/{total} 통과" + (f" — {failed}개 실패" if failed else ""))
    if dupes:
        print(f"중복 course_id {dupes}건")
    if missing:
        print(f"설명이 없는 코스 {len(missing)}개: {', '.join(missing[:8])}"
              + (" …" if len(missing) > 8 else ""))
    return 1 if (failed or missing or dupes) else 0


# ---------------------------------------------------------------------------

def demo() -> None:
    """Deliberately broken entries, to prove the checks fire."""
    facts = load_courses()
    gaz = build_gazetteer()

    f = facts["VK_THEME_041"]          # 문화비축기지 · 노들섬 · 서울숲, 식당 없음
    assert not f["has_meal"]
    assert f["evidence"] == {"Nature & Relaxation"}, f["evidence"]

    good = {
        "course_id": "VK_THEME_041",
        "interests": ["Nature & Relaxation"],
        "constraints": [],
        "purpose": "For travellers bringing a dog, who need to know which Seoul "
                   "spaces will let one in rather than guessing at the gate.",
        "description": "Oil Tank Culture Park in Mapo, Nodeul Island on the river "
                       "and Seoul Forest in Seongsu, all outdoor. No food stop is "
                       "included, so meals happen elsewhere. Three hours of stops "
                       "across three districts does not fill a day.",
    }
    assert check_one(good, f, gaz, "VK_THEME_041") == [], check_one(good, f, gaz, "VK_THEME_041")

    bad = dict(good, description=good["description"] + " Then on to Gyeongbokgung Palace.")
    assert any("Gyeongbokgung" in e for e in check_one(bad, f, gaz, "VK_THEME_041"))

    bad = dict(good, purpose="A perfectly charming day out with your dog in Seoul, "
                             "with something for everyone in the family.")
    hits = check_one(bad, f, gaz, "VK_THEME_041")
    assert sum("홍보 문구" in e for e in hits) >= 2, hits

    bad = dict(good, interests=["Shopping"])
    assert any("누락" in e for e in check_one(bad, f, gaz, "VK_THEME_041"))

    bad = dict(good, description="Oil Tank Culture Park, Nodeul Island and Seoul "
                                 "Forest, three outdoor spaces in three districts.")
    assert any("식사할 곳이 없는데" in e for e in check_one(bad, f, gaz, "VK_THEME_041"))

    bad = dict(good, interests=["Nature & Relaxation", "Culture"])
    assert any("어휘 밖" in e for e in check_one(bad, f, gaz, "VK_THEME_041"))

    print("demo ok")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--demo"]
    if "--demo" in sys.argv[1:]:
        demo()
    else:
        sys.exit(validate(Path(args[0]) if args else DESCRIPTIONS))
