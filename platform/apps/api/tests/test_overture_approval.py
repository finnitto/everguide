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
        "source_type": "first_party_website", "reachable": True,
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


def test_wrong_service_is_excluded_even_if_overture_taxonomy_says_funeral():
    result = assess_overture_candidate(row(name="A Elfes Memorial Masonry", website="https://memorial.example"), point_in_thurrock=True)
    assert result["outcome"] == "excluded"


def test_postcode_conflict_is_exception():
    result = assess_overture_candidate(row(postcode="G73 2AW"), first_party_evidence=evidence(postcode="G73 2AW"), point_in_thurrock=True)
    assert result["outcome"] == "exception_review"
    assert "postcode_outside_thurrock_area" in result["reasons"]


def test_unknown_contributor_licence_blocks_auto_approval():
    result = assess_overture_candidate(row(sources_json='[{"dataset":"Unknown","license":"UNKNOWN"}]'), first_party_evidence=evidence(), point_in_thurrock=True)
    assert result["outcome"] == "awaiting_enrichment"
    assert "source_level_licence_missing_or_unrecognised" in result["reasons"]


def test_duplicate_and_branch_conflicts_are_exceptions():
    result = assess_overture_candidate(row(possible_duplicate="True"), first_party_evidence=evidence(), point_in_thurrock=True)
    assert result["outcome"] == "exception_review"


def test_boundary_not_confirmed_blocks_auto_approval():
    result = assess_overture_candidate(row(), first_party_evidence=evidence())
    assert result["outcome"] == "awaiting_enrichment"
    assert "official_thurrock_boundary_not_confirmed" in result["reasons"]
