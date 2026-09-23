"""네트워크 없이 도는 self-check. Run: python test_meal_slots.py"""

import geo
import meal_slots
from meal_slots import MEAL_AREA_CENTERS, fill_meal_slot, is_open, load_restaurants, matches_area_within_radius


def demo() -> None:
    closed_day = {"opening_hours": {"Monday": ["closed"]}}
    assert is_open(closed_day, "Monday", "11:00", "13:30") is False

    break_time = {"opening_hours": {"Tuesday": ["12:00-15:00", "18:00-22:00"]}}
    assert is_open(break_time, "Tuesday", "15:00", "18:00") is False
    assert is_open(break_time, "Tuesday", "11:00", "13:30") is True
    assert is_open(break_time, "Tuesday", "18:00", "20:00") is True

    no_hours = {"opening_hours": None}
    assert is_open(no_hours, "Tuesday", "11:00", "13:30") is False
    no_hours_missing_key = {}
    assert is_open(no_hours_missing_key, "Tuesday", "11:00", "13:30") is False

    overnight = {"opening_hours": {"Friday": ["18:00-02:00"]}}
    assert is_open(overnight, "Friday", "18:00", "20:00") is True
    assert is_open(overnight, "Friday", "11:00", "13:30") is False

    restaurants = load_restaurants()
    samgyetang = next(r for r in restaurants if r["cuisine"] == "Samgyetang")
    assert samgyetang["cuisine_family"] == "korean", samgyetang["cuisine_family"]

    contemporary = next(r for r in restaurants if r["cuisine"] == "Contemporary")
    assert contemporary["needs_review"] is False
    assert contemporary["cuisine_family"] == "contemporary"

    noodles = next(r for r in restaurants if r["cuisine"] == "Noodles")
    assert noodles["needs_review"] is False
    assert noodles["cuisine_family"] == "korean"

    # MEAL_AREA_CENTERS must cover every geo.py area — no silent KeyError later.
    assert set(MEAL_AREA_CENTERS) == set(geo.SEOUL_AREA_CENTERS)

    # the meal-specific gangnam center (moved to the restaurant centroid) must
    # be within a tiny radius of itself, and far from dmc.
    gangnam_center_lat, gangnam_center_lon = MEAL_AREA_CENTERS["gangnam"]
    at_center = {"lat": gangnam_center_lat, "lon": gangnam_center_lon}
    assert matches_area_within_radius(at_center, "gangnam", 0.1) is True
    assert matches_area_within_radius(at_center, "dmc", 0.1) is False  # dmc is ~13km away

    # seongsu's centroid override should recover ~49 restaurants within 1.5km
    # (area_center_check.py measured 49; assert a tolerant range so tiny
    # coordinate rounding doesn't make this test flaky).
    n_seongsu = sum(
        1 for r in restaurants if matches_area_within_radius(r, "seongsu", 1.5)
    )
    assert 45 <= n_seongsu <= 53, n_seongsu

    print("all meal_slots self-checks passed")


def _michelin_fixture(name: str, grade: str, cuisine_family: str = "korean") -> dict:
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


def test_fill_meal_slot() -> None:
    calls: list[str] = []

    def stub_with_result(area: str) -> list[dict]:
        calls.append(area)
        return [{"poi_name": "Stub BBQ", "lat": 1.0, "lng": 2.0, "address_en": "stub addr", "rating": 4.5}]

    original_fetch = meal_slots._fetch_google_restaurants_raw
    meal_slots._GOOGLE_PLACES_CACHE.clear()
    meal_slots._fetch_google_restaurants_raw = stub_with_result
    try:
        # 1층에 후보가 있으면 2층(google)을 호출하지 않는다. 등급 순서도 뒤섞어서
        # 3스타가 순위 상관없이 뽑히는지 같이 검증.
        restaurants = [
            _michelin_fixture("SelectedPlace", "Selected"),
            _michelin_fixture("OneStar", "1스타"),
            _michelin_fixture("ThreeStar", "3스타"),
            _michelin_fixture("BibGourmand", "빕구르망"),
        ]
        r1 = fill_meal_slot(
            area="hongdae", weekday="Tuesday", slot_start="11:00", slot_end="13:30",
            restaurants=restaurants,
        )
        assert r1["status"] == "filled"
        assert r1["source_tier"] == "michelin"
        assert r1["name"] == "ThreeStar", r1["name"]
        assert calls == [], "google must not be called when tier-1 has a candidate"

        # 1층이 비면 2층을 호출한다. verified는 opening_hours/cuisine 둘 다 False여야 한다.
        r2 = fill_meal_slot(
            area="hongdae", weekday="Tuesday", slot_start="11:00", slot_end="13:30",
            restaurants=[],
        )
        assert r2["status"] == "filled"
        assert r2["source_tier"] == "google"
        assert r2["name"] == "Stub BBQ"
        assert r2["verified"] == {"opening_hours": False, "cuisine": False}
        assert calls == ["hongdae"]

        # 같은 area를 다시 조회하면 캐시로 인해 fetch가 다시 불리지 않는다.
        r3 = fill_meal_slot(
            area="hongdae", weekday="Tuesday", slot_start="11:00", slot_end="13:30",
            restaurants=[],
        )
        assert r3["source_tier"] == "google"
        assert calls == ["hongdae"], "second call for the same area must hit the cache"

        # 1층/2층 둘 다 비면 unfilled + reason.
        meal_slots._GOOGLE_PLACES_CACHE.clear()

        def stub_empty(area: str) -> list[dict]:
            calls.append(area)
            return []

        meal_slots._fetch_google_restaurants_raw = stub_empty
        r4 = fill_meal_slot(
            area="itaewon", weekday="Tuesday", slot_start="11:00", slot_end="13:30",
            restaurants=[],
        )
        assert r4["status"] == "unfilled"
        assert r4["source_tier"] is None
        assert r4.get("reason"), "unfilled result must carry a reason"

        # exclude_families가 걸려도 2층 후보는 배제하지 않고 반환한다(검증 못 할
        # 뿐 후보 자체는 준다) — 단 아직 구현 안 한 exclude_reason은 명시적으로 막는다.
        meal_slots._GOOGLE_PLACES_CACHE.clear()
        meal_slots._fetch_google_restaurants_raw = stub_with_result
        r5 = fill_meal_slot(
            area="hongdae", weekday="Tuesday", slot_start="11:00", slot_end="13:30",
            restaurants=[], exclude_families=("korean",),
        )
        assert r5["status"] == "filled" and r5["source_tier"] == "google"
        assert r5["verified"] == {"opening_hours": False, "cuisine": False}

        try:
            fill_meal_slot(
                area="hongdae", weekday="Tuesday", slot_start="11:00", slot_end="13:30",
                restaurants=[], exclude_families=("korean",), exclude_reason="allergy",
            )
            raise AssertionError("expected NotImplementedError for an unimplemented exclude_reason")
        except NotImplementedError:
            pass
    finally:
        meal_slots._fetch_google_restaurants_raw = original_fetch
        meal_slots._GOOGLE_PLACES_CACHE.clear()

    print("all fill_meal_slot self-checks passed")


if __name__ == "__main__":
    demo()
    test_fill_meal_slot()


# --- diet -------------------------------------------------------------------

def _michelin(name, cuisine, area_latlng=(37.5729, 126.9794)):
    return {"name": name, "cuisine": cuisine, "cuisine_family": None, "needs_review": False,
            "grade": "Selected", "lat": area_latlng[0], "lon": area_latlng[1], "street": "",
            "opening_hours": {"Tuesday": ["11:00-22:00"]}}


def test_parse_diet() -> None:
    cases = {
        "vegetarian": "vegetarian", "I'm veggie": "vegetarian", "no meat please": "vegetarian",
        "채식해요": "vegetarian", "vegan please": "vegan", "plant-based only": "vegan",
        "halal": "halal", "we're muslim": "halal",
        "no pork please": None, "nut allergy": None, "none": None, "": None, None: None,
    }
    for text, want in cases.items():
        assert meal_slots.parse_diet(text) == want, (text, meal_slots.parse_diet(text))


def _diet_fill(monkeypatch, restaurants, found, diet="vegetarian"):
    queries = []
    monkeypatch.setattr(meal_slots, "_fetch_diet_restaurants_raw",
                        lambda area, search: queries.append((area, search)) or found)
    meal_slots._GOOGLE_PLACES_CACHE.clear()
    out = fill_meal_slot(area="jongno", weekday="Tuesday", slot_start="11:00", slot_end="13:30",
                         restaurants=restaurants, diet=diet)
    return out, queries


def test_a_vegetarian_never_gets_a_meat_michelin_pick(monkeypatch) -> None:
    google = [{"poi_name": "Veg Place", "rating": 4.6, "lat": 37.57, "lng": 126.98, "address_en": ""}]
    out, queries = _diet_fill(monkeypatch, [_michelin("Gomtang House", "Gomtang")], google)
    assert out["name"] == "Veg Place" and out["source_tier"] == "google"
    assert queries == [("jongno", "vegetarian restaurant")]
    assert "vegetarian" in out["warnings"][0]


def test_a_vegan_michelin_in_the_zone_is_picked_for_a_vegetarian(monkeypatch) -> None:
    out, queries = _diet_fill(monkeypatch, [_michelin("Gomtang House", "Gomtang"),
                                            _michelin("Leaf", "Vegan")], [])
    assert out["name"] == "Leaf" and out["source_tier"] == "michelin" and queries == []


def test_no_diet_match_leaves_the_meal_open(monkeypatch) -> None:
    out, _ = _diet_fill(monkeypatch, [_michelin("Gomtang House", "Gomtang")], [])
    assert out["status"] == "unfilled" and "vegetarian" in out["reason"]


def test_halal_never_uses_michelin(monkeypatch) -> None:
    out, queries = _diet_fill(monkeypatch, [_michelin("Leaf", "Vegan")], [], diet="halal")
    assert out["status"] == "unfilled" and queries == [("jongno", "halal restaurant")]


def test_nearest_michelin_can_be_limited_to_diet_cuisines() -> None:
    rs = [_michelin("Gomtang House", "Gomtang"), _michelin("Leaf", "Vegan")]
    hits = meal_slots.nearest_michelin(lat=37.5729, lng=126.9794, restaurants=rs,
                                       cuisines=("Vegan", "Vegetarian"))
    assert [h["name"] for h in hits] == ["Leaf"]
