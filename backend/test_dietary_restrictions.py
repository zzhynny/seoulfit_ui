"""Self-check for the P0 fix: state["restrictions"] (e.g. "vegetarian") must
actually reach every restaurant-picking path -- locked meal slots
(meal_slots.fill_meal_slot) and the Google Places supplement -- instead of
only ever showing up as prose in the LLM prompt.

Network-free: GOOGLE_PLACES_API_KEY is left unset / fetch functions are
monkeypatched, so nothing here makes a real HTTP call.

Run:  python test_dietary_restrictions.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import meal_slots  # noqa: E402
import planner  # noqa: E402
from meal_slots import MEAL_AREA_CENTERS, fill_meal_slot, restrictions_to_excluded_families  # noqa: E402


def test_restrictions_to_excluded_families_mapping():
    # Vegetarian/vegan (English + Korean) -> exclude every family except "other"
    # (the only bucket cuisine_family.json ever assigns to a "Vegan"/"Vegetarian"
    # cuisine -- see dataset/cuisine_family.json).
    for text in ("vegetarian", "Vegan", "I'm vegan, no meat please", "채식주의자", "비건"):
        excluded = restrictions_to_excluded_families(text)
        assert "other" not in excluded, (text, excluded)
        assert set(excluded) == {"korean", "japanese", "chinese", "western", "contemporary", "asian"}, (text, excluded)

    # Unrelated / empty / "none" -> no exclusion (unchanged behavior).
    for text in (None, "", "none", "No restrictions", "wheelchair access needed", "peanut allergy"):
        assert restrictions_to_excluded_families(text) == (), text

    print("OK  restrictions_to_excluded_families maps vegetarian/vegan and leaves everything else alone")


def _michelin_fixture(name: str, grade: str, cuisine_family: str) -> dict:
    hongdae_lat, hongdae_lon = MEAL_AREA_CENTERS["hongdae"]
    return {
        "name": name,
        "lat": hongdae_lat,
        "lon": hongdae_lon,
        "street": "test street, Test-gu",
        "grade": grade,
        "cuisine_family": cuisine_family,
        "needs_review": False,
        "opening_hours": {"Tuesday": ["11:00-14:00", "18:00-21:00"]},
    }


def test_fill_meal_slot_respects_excluded_families():
    """Direct check that fill_meal_slot(exclude_families=...) -- the mechanism
    this fix wires up to -- actually keeps a Korean BBQ place out and picks
    the "other"-family (vegetarian) place instead."""
    restaurants = [
        _michelin_fixture("Meaty BBQ", "3스타", cuisine_family="korean"),
        _michelin_fixture("Green Table", "Selected", cuisine_family="other"),
    ]
    veg_families = restrictions_to_excluded_families("vegetarian")

    result = fill_meal_slot(
        area="hongdae", weekday="Tuesday", slot_start="11:00", slot_end="13:30",
        exclude_families=veg_families,
        restaurants=restaurants,
    )
    assert result["status"] == "filled"
    assert result["name"] == "Green Table", result

    # Without the restriction, the higher-grade (3스타) BBQ place wins as before.
    result_unrestricted = fill_meal_slot(
        area="hongdae", weekday="Tuesday", slot_start="11:00", slot_end="13:30",
        restaurants=restaurants,
    )
    assert result_unrestricted["name"] == "Meaty BBQ", result_unrestricted

    print("OK  fill_meal_slot(exclude_families=...) keeps the non-vegetarian pick out")


def test_resolve_locked_meals_passes_exclude_families_through():
    """Regression guard for the actual bug: plan_node computes exclude_families
    but _resolve_locked_meals used to never forward it to fill_meal_slot."""
    captured: list[tuple] = []
    original = meal_slots.fill_meal_slot

    def _capture(**kwargs):
        captured.append(kwargs.get("exclude_families"))
        return meal_slots._unfilled(kwargs["slot_start"], kwargs["slot_end"], "stub")

    meal_slots.fill_meal_slot = _capture
    try:
        planner._resolve_locked_meals(
            "2027-02-01", ["hongdae"], 1, meal_type="dinner",
            exclude_families=("korean", "japanese"),
        )
    finally:
        meal_slots.fill_meal_slot = original

    assert captured == [("korean", "japanese")], captured
    print("OK  planner._resolve_locked_meals forwards exclude_families to fill_meal_slot")


def test_google_supplement_biases_queries_for_vegetarian():
    """Regression guard for the Google Places leg: build_google_supplement_for_area
    must bias the restaurant/cafe fetch calls toward "vegetarian" when
    exclude_families says so, and must NOT change anything when it's empty
    (no behavior change for travellers without a dietary restriction)."""
    nearby_calls: list[dict] = []
    text_calls: list[dict] = []

    def _stub_nearby(**kwargs):
        nearby_calls.append(kwargs)
        return []

    def _stub_text(**kwargs):
        text_calls.append(kwargs)
        return []

    original_nearby = planner.fetch_nearby_places
    original_text = planner.fetch_text_places
    planner.fetch_nearby_places = _stub_nearby
    planner.fetch_text_places = _stub_text
    try:
        # Vegetarian restriction: the restaurant Nearby Search call must carry
        # keyword="vegetarian" (only lever Places' Nearby Search offers).
        planner.build_google_supplement_for_area(
            area="hongdae", purpose="food", api_key="fake-key",
            exclude_families=restrictions_to_excluded_families("vegetarian"),
        )
        restaurant_calls = [c for c in nearby_calls if c.get("place_type") == "restaurant"]
        assert restaurant_calls and restaurant_calls[-1].get("keyword") == "vegetarian", restaurant_calls

        nearby_calls.clear()
        text_calls.clear()

        # No restriction: unchanged -- keyword stays None, exactly as before this fix.
        planner.build_google_supplement_for_area(
            area="hongdae", purpose="food", api_key="fake-key",
        )
        restaurant_calls = [c for c in nearby_calls if c.get("place_type") == "restaurant"]
        assert restaurant_calls and restaurant_calls[-1].get("keyword") is None, restaurant_calls
    finally:
        planner.fetch_nearby_places = original_nearby
        planner.fetch_text_places = original_text

    print("OK  build_google_supplement_for_area biases restaurant search only when a "
          "vegetarian/vegan restriction is present, unchanged otherwise")


if __name__ == "__main__":
    test_restrictions_to_excluded_families_mapping()
    test_fill_meal_slot_respects_excluded_families()
    test_resolve_locked_meals_passes_exclude_families_through()
    test_google_supplement_biases_queries_for_vegetarian()
    print("all test_dietary_restrictions self-checks passed")
