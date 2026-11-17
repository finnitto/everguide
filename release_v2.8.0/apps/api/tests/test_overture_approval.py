import json
from app.overture_approval import assess_overture_candidate


def row(**updates):
    value = {
        "gers_id": "gers-1", "name": "Example Funeral Directors",
        "basic_category": "family_service", "taxonomy_primary": "funeral_service",
        "confidence": "0.99", "address": "1 High Street, Grays",
        "postcode": "RM17 5LS", "phone": "01375555000",
        "website": "https://examplefunerals.co.uk",
        "sources_json": json.dumps([{"dataset": "Microsoft", "license": "CDLA-Permissive-2.0"}]),
        "possible_duplicate": "False",
    }
    value.update(updates)
    return value


def evidence(**updates):
    value = {
        "source_type": "first_party_website", "business_name": "Example Funeral Directors", "reachable": True,
        "robots_allowed": True, "explicit_funeral_director_service": True,
        "website_url": "https://examplefunerals.co.uk", "complete_branch_address": True,
        "postcode": "RM17 5LS", "telephone": "01375 555000", "confidence": 0.97,
    }
    value.update(updates)
    return value


def test_overture_confidence_alone_never_auto_approves():
    result = assess_overture_candidate(row(), point_in_thurrock=True)
    assert result["outcome"] == "awaiting_enrichment"
    assert "independent_first_party_evidence_missing" in result["reasons"]


def test_complete_independent_evidence_and_source_rights_can_pass():
    result = assess_overture_candidate(row(), first_party_evidence=evidence(), point_in_thurrock=True)
    assert result["outcome"] == "auto_approved_eligible"
    assert result["reasons"] == ""
    assert result["shared_policy_version"] == "shared-provider-approval-v1.0"
    assert result["ruleset_version"] == "overture-auto-approval-v1.3"



def test_disabled_auto_approval_never_returns_auto_approved_eligible():
    result = assess_overture_candidate(
        row(), first_party_evidence=evidence(), point_in_thurrock=True,
        auto_approval_enabled=False,
    )
    assert result["outcome"] != "auto_approved_eligible"
    assert result["outcome"] == "awaiting_enrichment"
    assert "automatic_approval_disabled" in result["reasons"]
    assert result["ruleset_version"] == "overture-auto-approval-v1.3"

def test_wrong_service_is_excluded_even_if_overture_taxonomy_says_funeral():
    result = assess_overture_candidate(row(name="A Elfes Memorial Masonry", website="https://memorial.example"), point_in_thurrock=True)
    assert result["outcome"] == "excluded"


def test_postcode_conflict_is_exception():
    result = assess_overture_candidate(row(postcode="G73 2AW"), first_party_evidence=evidence(postcode="G73 2AW"), point_in_thurrock=True)
    assert result["outcome"] == "exception_review"
    assert "postcode_outside_thurrock_area" in result["reasons"]


def test_unknown_contributor_licence_blocks_auto_approval():
    result = assess_overture_candidate(row(sources_json='[{"dataset":"Unknown","license":"UNKNOWN"}]'), first_party_evidence=evidence(), point_in_thurrock=True)
    assert result["outcome"] == "exception_review"
    assert "source_level_licence_missing_or_unrecognised" in result["reasons"]


def test_possible_same_name_postcode_match_is_held_without_claiming_identity_conflict():
    result = assess_overture_candidate(row(possible_duplicate="True"), first_party_evidence=evidence(), point_in_thurrock=True)
    assert result["outcome"] == "exception_review"
    assert "possible_same_name_postcode_match" in result["reasons"]
    assert "conflicting_identity_or_branch_evidence" not in result["reasons"]
    assert result["ruleset_version"] == "overture-auto-approval-v1.3"


def test_boundary_not_confirmed_blocks_auto_approval():
    result = assess_overture_candidate(row(), first_party_evidence=evidence())
    assert result["outcome"] == "awaiting_enrichment"
    assert "official_thurrock_boundary_not_confirmed" in result["reasons"]


def test_point_confirmed_outside_official_boundary_is_exception():
    result = assess_overture_candidate(row(), first_party_evidence=evidence(), point_in_thurrock=False)
    assert result["outcome"] == "exception_review"
    assert "point_outside_official_thurrock_boundary" in result["reasons"]


def test_first_party_business_name_mismatch_is_exception():
    result = assess_overture_candidate(row(), first_party_evidence=evidence(business_name="Different Funeral Company"), point_in_thurrock=True)
    assert result["outcome"] == "exception_review"
    assert "first_party_identity_name_mismatch" in result["reasons"]


def test_business_name_matching_ignores_common_funeral_service_suffixes():
    candidate = row(name="W Howard and Son Funeral Directors")
    evidence_row = evidence(business_name="W Howard & Son")
    result = assess_overture_candidate(candidate, first_party_evidence=evidence_row, point_in_thurrock=True)
    assert result["outcome"] == "auto_approved_eligible"


def test_basildon_scope_uses_authority_boundary_without_thurrock_postcode_filter():
    candidate = row(postcode="SS14 1AB")
    result = assess_overture_candidate(
        candidate, first_party_evidence=evidence(postcode="SS14 1AB"),
        point_in_thurrock=True, geography_scope="basildon",
    )
    assert result["outcome"] == "auto_approved_eligible"
    assert "postcode_outside_thurrock_area" not in result["reasons"]


def test_havering_scope_uses_authority_boundary_and_fails_closed_when_unknown():
    result = assess_overture_candidate(
        row(postcode="RM1 1AA"), first_party_evidence=evidence(postcode="RM1 1AA"),
        geography_scope="havering",
    )
    assert result["outcome"] == "awaiting_enrichment"
    assert "official_havering_boundary_not_confirmed" in result["reasons"]


def test_basildon_point_outside_official_authority_is_exception():
    result = assess_overture_candidate(
        row(postcode="SS14 1AB"), first_party_evidence=evidence(postcode="SS14 1AB"),
        point_in_thurrock=False, geography_scope="basildon",
    )
    assert result["outcome"] == "exception_review"
    assert "point_outside_official_basildon_boundary" in result["reasons"]


def test_unsupported_geographic_scope_is_exception_review():
    result = assess_overture_candidate(
        row(), first_party_evidence=evidence(), point_in_thurrock=True,
        geography_scope="ambiguous_authority_boundary",
    )
    assert result["outcome"] == "exception_review"
    assert "unsupported_geographic_scope" in result["reasons"]
