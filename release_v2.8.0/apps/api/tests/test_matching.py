from types import SimpleNamespace
from app.matching import (
    find_provider_matches, normalise_domain, normalise_name,
    normalise_phone, normalise_postcode, observation_duplicate_key,
)


def test_normalisers_handle_common_uk_formats():
    assert normalise_name("A.B.C. Funeral Care Limited") == "a b c funeral care"
    assert normalise_postcode("sw1a 1aa") == "SW1A1AA"
    assert normalise_phone("+44 20 7946 0958") == "02079460958"
    assert normalise_domain("https://www.example.co.uk/contact") == "example.co.uk"


def test_matching_uses_multiple_independent_signals():
    branch = SimpleNamespace(id=7, branch_name="Northfield Funeral Services", postcode="YO1 1AA",
        telephone="01904 123456", website="https://northfield.example", town_city="York")
    provider = SimpleNamespace(id=3, trading_name="Northfield Funeral Services Ltd", website=None,
        status="draft", branches=[branch])
    observation = SimpleNamespace(id=10, observed_data={"name":"Northfield Funeral Services",
        "postcode":"YO1 1AA", "phone":"01904 123456", "website":"https://northfield.example"})
    result = find_provider_matches(observation, [provider])
    assert result["match_state"] == "strong_candidate"
    assert result["candidates"][0]["provider_id"] == 3
    assert "Exact postcode" in result["candidates"][0]["reasons"]


def test_place_id_only_observation_is_not_guessed_as_a_match():
    observation = SimpleNamespace(id=11, observed_data={"google_place_id":"ChIJexample"})
    result = find_provider_matches(observation, [])
    assert result["match_state"] == "needs_enrichment"
    assert result["matchable"] is False
    assert result["candidates"] == []


def test_duplicate_key_uses_permitted_place_id_or_business_fingerprint():
    place_a = SimpleNamespace(observed_data={"google_place_id":"ChIJ123"})
    place_b = SimpleNamespace(observed_data={"google_place_id":"ChIJ123"})
    assert observation_duplicate_key(place_a) == observation_duplicate_key(place_b)
    business = SimpleNamespace(observed_data={"name":"Example Funeral Care", "postcode":"YO1 1AA"})
    assert observation_duplicate_key(business).startswith("business:")
