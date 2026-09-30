from __future__ import annotations

from career.distance import (
    distance_miles,
    find_known_place,
    find_place_outside_uk,
    haversine_miles,
)


def test_haversine_miles_is_zero_for_the_same_point() -> None:
    assert haversine_miles((50.85, -1.18), (50.85, -1.18)) == 0.0


def test_haversine_miles_matches_a_known_approximate_distance() -> None:
    # Fareham to London is roughly 60-70 miles as the crow flies.
    fareham = (50.8523, -1.1780)
    london = (51.5074, -0.1278)

    miles = haversine_miles(fareham, london)

    assert 55 < miles < 75


def test_find_known_place_matches_case_insensitively() -> None:
    assert find_known_place("Remote, working from BRISTOL sometimes") == "bristol"


def test_find_known_place_does_not_match_inside_a_longer_word() -> None:
    assert find_known_place("Yorkshire") is None


def test_find_known_place_does_not_match_york_inside_new_york() -> None:
    assert find_known_place("New York, NY") is None


def test_find_place_outside_uk_recognises_accented_and_unaccented_names() -> None:
    assert find_place_outside_uk("Zürich") == "zurich"
    assert find_place_outside_uk("Zurich, Switzerland") == "zurich"
    assert find_place_outside_uk("Berlin, Berlin, Germany") == "berlin"
    assert find_place_outside_uk("Detmold, Nordrhein-Westfalen, Deutschland") == "deutschland"


def test_find_place_outside_uk_is_none_for_uk_unknown_or_multi_site_listings() -> None:
    assert find_place_outside_uk("London, UK") is None
    assert find_place_outside_uk("Wuppertal") is None
    # A listing that also names a UK office isn't treated as abroad.
    assert find_place_outside_uk("Berlin; London") is None


def test_find_known_place_returns_none_for_an_unknown_place() -> None:
    assert find_known_place("Timbuktu") is None


def test_distance_miles_is_none_when_either_place_is_unknown() -> None:
    assert distance_miles("Fareham", "Somewhere made up") is None
    assert distance_miles("Somewhere made up", "London, UK") is None


def test_distance_miles_resolves_both_ends() -> None:
    miles = distance_miles("Fareham", "London, UK (Hybrid)")

    assert miles is not None
    assert 55 < miles < 75
