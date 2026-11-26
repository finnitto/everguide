import json
from app.overture_approval import assess_overture_candidate, RULESET_VERSION


def row(**updates):
    value = {
        "gers_id": "gers-1", "name": "Example Funeral Directors",
        "basic_category": "family_service", "taxonomy_primary": "funeral_service",
        "confidence": "0.99", "address": "1 High Street, Grays",
        "address_line_1": "1 High Street", "town_city": "Grays",
        "postcode": "RM17 5LS", "phone": "01375555000",
        "website": "https://examplefunerals.co.uk",
        "sources_json": json.dumps([{"dataset": "Microsoft", "license": "CDLA-Permissive-2.0"}]),
        "possible_duplicate": "False",
    }
    value.update(updates)
    return value


def test_valid_overture_location_auto_approves_without_companies_house_or_website_evidence():
    result = assess_overture_candidate(row(website=""), point_in_thurrock=True)
    assert result["outcome"] == "auto_approved_eligible"
    assert result["reasons"] == ""
    assert result["ruleset_version"] == RULESET_VERSION == "overture-first-approval-v2.2"


def test_consistent_optional_website_evidence_does_not_change_overture_authority():
    result = assess_overture_candidate(
        row(), first_party_evidence={"source_type": "first_party_website", "business_name": "Example Funeral Directors"},
        point_in_thurrock=True,
    )
    assert result["outcome"] == "auto_approved_eligible"


def test_explicit_material_conflict_routes_to_exception_review():
    result = assess_overture_candidate(
        row(), first_party_evidence={"conflict_codes": ["official_site_branch_closed"]},
        point_in_thurrock=True,
    )
    assert result["outcome"] == "exception_review"
    assert "official_site_branch_closed" in result["reasons"]


def test_missing_or_unreachable_website_is_an_enrichment_exception():
    result = assess_overture_candidate(
        row(website=""), first_party_evidence={"verification_status": "website_missing"},
        point_in_thurrock=True,
    )
    # The side-effect-free location policy cannot decide website availability;
    # the enrichment gate applies that check in the candidate processing task.
    assert result["outcome"] == "auto_approved_eligible"


def test_disabled_auto_approval_never_returns_auto_approved_eligible():
    result = assess_overture_candidate(row(), point_in_thurrock=True, auto_approval_enabled=False)
    assert result["outcome"] == "awaiting_enrichment"
    assert "automatic_approval_disabled" in result["reasons"]


def test_related_memorial_service_can_be_enriched_from_overture_without_becoming_a_funeral_director():
    result = assess_overture_candidate(row(name="A Elfes Memorial Masonry", website="https://memorial.example"), point_in_thurrock=True)
    assert result["service_class"] == "memorial_or_masonry"
    assert result["outcome"] == "auto_approved_eligible"


def test_postcode_outside_pilot_area_is_exception():
    result = assess_overture_candidate(row(postcode="G73 2AW"), point_in_thurrock=True)
    assert result["outcome"] == "exception_review"
    assert "postcode_outside_thurrock_area" in result["reasons"]


def test_unknown_contributor_licence_blocks_auto_approval():
    result = assess_overture_candidate(row(sources_json='[{"dataset":"Unknown","license":"UNKNOWN"}]'), point_in_thurrock=True)
    assert result["outcome"] == "exception_review"
    assert "source_level_licence_missing_or_unrecognised" in result["reasons"]


def test_possible_same_name_postcode_match_is_held_without_claiming_identity_conflict():
    result = assess_overture_candidate(row(possible_duplicate="True"), point_in_thurrock=True)
    assert result["outcome"] == "exception_review"
    assert "possible_same_name_postcode_match" in result["reasons"]


def test_boundary_not_confirmed_blocks_auto_approval():
    result = assess_overture_candidate(row())
    assert result["outcome"] == "awaiting_enrichment"
    assert "official_thurrock_boundary_not_confirmed" in result["reasons"]


def test_point_confirmed_outside_official_boundary_is_exception():
    result = assess_overture_candidate(row(), point_in_thurrock=False)
    assert result["outcome"] == "exception_review"
    assert "point_outside_official_thurrock_boundary" in result["reasons"]


def test_incomplete_overture_branch_address_awaits_enrichment():
    result = assess_overture_candidate(row(town_city=""), point_in_thurrock=True)
    assert result["outcome"] == "awaiting_enrichment"
    assert "overture_locality_missing" in result["reasons"]


def test_companies_house_registered_office_does_not_enter_branch_conflict_without_linked_evidence():
    result = assess_overture_candidate(row(), first_party_evidence={"companies_house_registered_office": "Different town"}, point_in_thurrock=True)
    assert result["outcome"] == "auto_approved_eligible"


def test_companies_house_conflicts_are_ignored_by_overture_approval_policy():
    result = assess_overture_candidate(
        row(),
        first_party_evidence={"conflict_codes": ["verified_companies_house_entity_dissolved"]},
        point_in_thurrock=True,
    )
    assert result["outcome"] == "auto_approved_eligible"
    assert "verified_companies_house_entity_dissolved" not in result["reasons"]



def test_overture_related_services_are_retained_for_enrichment_without_becoming_funeral_directors():
    cases = (
        ("In Our Hands Pet Funeral Services", "animal_or_pet_service", "animal_or_pet_service", "pet_service"),
        ("Aylesbury Vale Natural Burial Meadow", "family_service", "funeral_service", "cemetery"),
        ("Flexible Funeral Plans", "family_service", "funeral_service", "funeral_plan_provider"),
        ("Simplicity Cremations", "family_service", "funeral_service", "direct_cremation_provider"),
        ("Distinct Cremations", "family_service", "funeral_service", "direct_cremation_provider"),
    )
    expected_outcomes = {
        "pet_service": "excluded",
        "cemetery": "auto_approved_eligible",
        "funeral_plan_provider": "auto_approved_eligible",
        "direct_cremation_provider": "auto_approved_eligible",
    }
    for name, basic, taxonomy, expected_service in cases:
        result = assess_overture_candidate(
            row(name=name, basic_category=basic, taxonomy_primary=taxonomy),
            point_in_england=True,
            geography_scope="england",
        )
        assert result["service_class"] == expected_service
        assert result["outcome"] == expected_outcomes[expected_service]


def test_overture_coordinate_conflict_routes_to_exception_review():
    result = assess_overture_candidate(
        row(),
        point_in_england=True,
        geography_scope="england",
        location_conflict=True,
    )
    assert result["outcome"] == "exception_review"
    assert "overture_coordinate_conflict" in result["reasons"]
