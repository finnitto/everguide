from types import SimpleNamespace

from app.candidate_quality import (
    candidate_location_flags,
    classify_service,
    exact_branch_fingerprint,
    normalise_phone,
    provider_identity_key,
)
from app.identity_assessment import _non_provider_signal, branch_eligible
from app.identity_rules import _classify, _provider_quality_assessment


def test_adjacent_service_precedence_overrides_overture_funeral_taxonomy():
    assert classify_service(
        name="A Elfes",
        basic_category="family_service",
        taxonomy_primary="funeral_service",
        website="http://www.memorialgroup.co.uk",
    ) == "memorial_or_masonry"


def test_celebrant_and_cemetery_typo_are_not_funeral_directors():
    assert classify_service(
        name="Claire Townsend Independent Celebrant",
        taxonomy_primary="funeral_service",
    ) == "celebrant"
    assert classify_service(
        name="Chadwell Cemetary",
        taxonomy_primary="funeral_service",
    ) == "cemetery"


def test_brand_name_can_be_classified_from_funeral_taxonomy():
    assert classify_service(
        name="S. Stibbards & Sons",
        taxonomy_primary="funeral_service",
    ) == "funeral_director_candidate"


def test_existing_search_classifier_maps_adjacent_services_correctly():
    assert _classify("Chadwell Cemetary", "Cemetery", "example.co.uk") == "related_service_not_funeral_director"
    assert _classify("Claire Townsend Independent Celebrant", "", "ct-ic.co.uk") == "related_service_not_funeral_director"
    assert _classify("A Elfes", "Memorial and headstone services", "memorialgroup.co.uk") == "related_service_not_funeral_director"


def test_phone_normalisation_handles_local_and_international_formats():
    assert normalise_phone("441708225146") == "01708225146"
    assert normalise_phone("+44 1708 225146") == "01708225146"
    assert normalise_phone("0044 1708 225146") == "01708225146"


def test_todd_duplicate_fingerprint_matches_phone_format_variants():
    a = exact_branch_fingerprint(name="Todd Funeral Services", postcode="RM15 5QZ", phone="441708225146")
    b = exact_branch_fingerprint(name="Todd Funeral Services", postcode="RM15 5QZ", phone="+441708225146")
    assert a == b


def test_west_and_coe_different_postcodes_remain_distinct_branches():
    aveley = exact_branch_fingerprint(name="West & Coe Funeral Directors", postcode="RM15 4AD", phone="01708865804")
    grays = exact_branch_fingerprint(name="West & Coe Funeral Directors", postcode="RM16 2YJ", phone="01375375615")
    assert aveley != grays


def test_provider_identity_group_is_a_suggestion_not_a_branch_deduplication_key():
    west_aveley = provider_identity_key(name="West & Coe Funeral Directors", website="https://www.westandcoe.com/")
    west_grays = provider_identity_key(name="West & Coe Funeral Directors", website="https://www.westandcoe.com/")
    assert west_aveley == west_grays
    assert exact_branch_fingerprint(name="West & Coe Funeral Directors", postcode="RM15 4AD", phone="01708865804") != exact_branch_fingerprint(name="West & Coe Funeral Directors", postcode="RM16 2YJ", phone="01375375615")


def test_thurrock_postcode_coordinate_conflict_is_flagged():
    flags = candidate_location_flags(
        postcode="G73 2AW",
        latitude=51.4801651,
        longitude=0.3741444,
        point_in_boundary=True,
    )
    assert "POSTCODE_OUTSIDE_EXPECTED_AREA" in flags
    assert "POSTCODE_COORDINATE_CONFLICT" in flags


def test_invalid_postcode_is_held_without_guessing_a_replacement():
    flags = candidate_location_flags(postcode="Grays", latitude=51.48507, longitude=0.36592)
    assert flags == ["POSTCODE_MISSING_OR_INVALID"]


def test_identity_assessment_blocks_a_celebrant_candidate():
    lead = SimpleNamespace(
        final_url="https://www.ct-ic.co.uk/",
        result_url="https://www.ct-ic.co.uk/",
        page_title="Claire Townsend Independent Celebrant",
        result_title="Claire Townsend Independent Celebrant",
    )
    data = {"name": "Claire Townsend Independent Celebrant", "type": "funeral_service"}
    assert _non_provider_signal(lead, data) is True


def test_funeral_director_is_not_blocked_for_memorial_word_in_body_description():
    lead = SimpleNamespace(
        final_url="https://examplefunerals.co.uk/",
        result_url="https://examplefunerals.co.uk/",
        page_title="Example Funeral Directors",
        result_title="Example Funeral Directors",
        match_score=0.9,
        verification_status="identity_signals_found",
        http_status=200,
        robots_allowed=True,
    )
    data = {
        "name": "Example Funeral Directors",
        "type": "funeral_director",
        "description": "We can also help families arrange memorial services.",
        "source_type": "schema_org_funeral_home",
        "website": "https://examplefunerals.co.uk/",
        "has_complete_branch_address": True,
        "street": "1 High Street",
        "town": "Thurrock",
        "postcode": "RM17 1AA",
        "country": "England",
    }
    assert _non_provider_signal(lead, data) is False
    assert branch_eligible(lead, data)[0] is True


def test_provider_quality_holds_obvious_adjacent_services():
    for name, website in (
        ("A Elfes", "https://www.memorialgroup.co.uk"),
        ("Claire Townsend Independent Celebrant", "https://www.ct-ic.co.uk"),
    ):
        status, _ = _provider_quality_assessment(
            SimpleNamespace(trading_name=name, website=website), []
        )
        assert status == "needs_review"




def test_overture_classifies_pet_funeral_and_pet_cremation_services_separately():
    assert classify_service(
        name="In Our Hands Pet Funeral Services",
        basic_category="animal_or_pet_service",
        taxonomy_primary="animal_or_pet_service",
    ) == "pet_service"
    assert classify_service(
        name="Roxy's Rainbow Pet Cremation",
        basic_category="family_service",
        taxonomy_primary="funeral_service",
    ) == "pet_service"


def test_natural_and_woodland_burial_locations_are_cemeteries():
    assert classify_service(
        name="Aylesbury Vale Natural Burial Meadow",
        basic_category="family_service",
        taxonomy_primary="funeral_service",
    ) == "cemetery"
    assert classify_service(
        name="Brocklands Woodlands Burial",
        basic_category="family_service",
        taxonomy_primary="funeral_service",
    ) == "cemetery"


def test_direct_cremation_providers_have_a_separate_service_class():
    for name in ("Simplicity Cremations", "Distinct Cremations", "Direct2Grave Cremations & Burials"):
        assert classify_service(
            name=name,
            basic_category="family_service",
            taxonomy_primary="funeral_service",
        ) == "direct_cremation_provider"


def test_funeral_plan_only_businesses_have_a_separate_service_class():
    assert classify_service(
        name="Flexible Funeral Plans",
        basic_category="family_service",
        taxonomy_primary="funeral_service",
    ) == "funeral_plan_provider"


def test_funeral_directors_that_offer_cremation_or_funeral_plans_remain_in_scope():
    assert classify_service(
        name="Example Funeral Directors and Cremations",
        basic_category="family_service",
        taxonomy_primary="funeral_service",
    ) == "funeral_director_candidate"
    assert classify_service(
        name="Example Funeral Directors and Funeral Plans",
        basic_category="family_service",
        taxonomy_primary="funeral_service",
    ) == "funeral_director_candidate"
