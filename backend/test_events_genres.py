"""Genre map self-checks for POST /events.

Offline by default. `python test_events_genres.py --live` additionally fetches
every genre page and parses it, which is how the slugs were established in the
first place: NOL's labels and its slugs disagree ("Play" is DRAMA,
"Exhibitions" is EXHIBIT, "Family" is KIDS), so a typo here does not raise —
it silently serves Musical under someone else's tab.
"""

from __future__ import annotations

import sys

from api import _NOL_GENRE, _NOL_UA, _parse_nol

# Mirrors kEventCategories in lib/models/event.dart, in the same order.
# Kept by hand because the two live in different languages; the point of the
# test is that they cannot drift apart unnoticed.
APP_CATEGORIES = [
    "Play&Stay", "Concert", "Musical", "Play", "Exhibitions",
    "Sports", "Dance", "Classic", "Family",
]

# Read off the nav's own hrefs on world.nol.com/en/ticket.
EXPECTED_SLUGS = {
    "Play&Stay": "play-stay",
    "Concert": "CONCERT",
    "Musical": "MUSICAL",
    "Play": "DRAMA",
    "Exhibitions": "EXHIBIT",
    "Sports": "SPORTS",
    "Dance": "DANCE",
    "Classic": "CLASSIC",
    "Family": "KIDS",
}


def _slug(category: str) -> str | None:
    """The lookup get_events does, minus its Musical fallback — the fallback is
    what hides a missing entry, so the test must not inherit it."""
    return _NOL_GENRE.get(category.strip().lower())


def test_every_app_category_resolves():
    for category in APP_CATEGORIES:
        assert _slug(category) == EXPECTED_SLUGS[category], (
            f"{category!r} -> {_slug(category)!r}, expected "
            f"{EXPECTED_SLUGS[category]!r}"
        )
    print("OK - every app category maps to its own genre page")


def test_no_two_categories_share_a_slug():
    # Two tabs serving the same page is the symptom a fallback produces.
    seen = {}
    for category in APP_CATEGORIES:
        slug = _slug(category)
        assert slug not in seen, f"{category!r} and {seen[slug]!r} both -> {slug!r}"
        seen[slug] = category
    print(f"OK - {len(seen)} distinct genres reachable from the app")


def test_legacy_labels_still_resolve():
    # An app build that predates the nine-genre list keeps working.
    assert _slug("Theater") == "DRAMA"
    assert _slug("Exhibition") == "EXHIBIT"
    assert _slug("Classical") == "CLASSIC"
    print("OK - labels from older builds still resolve")


def test_live_pages_parse():
    import httpx

    for category in APP_CATEGORIES:
        slug = _slug(category)
        resp = httpx.get(
            f"https://world.nol.com/en/ticket/genre/{slug}/products",
            headers={"User-Agent": _NOL_UA},
            timeout=20,
            follow_redirects=True,
        )
        assert resp.status_code == 200, f"{category}: HTTP {resp.status_code}"
        events = _parse_nol(resp.text)
        assert events, f"{category} ({slug}): fetched but parsed 0 events"
        print(f"OK - {category:<11} {slug:<10} {len(events):>2} events")


if __name__ == "__main__":
    test_every_app_category_resolves()
    test_no_two_categories_share_a_slug()
    test_legacy_labels_still_resolve()
    if "--live" in sys.argv:
        test_live_pages_parse()
    print("\nAll genre self-checks passed.")
