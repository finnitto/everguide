from app.provider_approval import assess_auto_approval


def verification(**overrides):
    result = {
        "status": "reachable", "robots_allowed": True, "http_status": 200,
        "content_type": "text/html; charset=utf-8",
        "extracted_data": {
            "name": "Example Funeral Directors", "street": "1 High Street",
            "town": "York", "postcode": "YO1 1AA", "telephone": "01904 123456",
            "website": "https://example.test/", "source_type": "schema_org_funeralhome",
            "confidence": 0.94, "has_complete_branch_address": True,
        },
    }
    result.update(overrides)
    return result


def test_high_confidence_first_party_funeral_home_is_auto_approved():
    decision = assess_auto_approval(candidate_url="https://www.example.test/contact",
                                   verification=verification(), candidate_company_name="Example Funeral Services Ltd", point_in_england=True)
    assert decision["eligible"] is True
    assert decision["decision"] == "auto_approve"
    assert decision["ruleset_version"] == "provider-auto-approval-v1.2"
    assert decision["shared_policy_version"] == "shared-provider-approval-v1.0"


def test_localbusiness_is_exception_not_auto_approved():
    data = verification()["extracted_data"] | {"source_type": "schema_org_localbusiness"}
    decision = assess_auto_approval(candidate_url="https://example.test",
                                   verification=verification(extracted_data=data))
    assert decision["eligible"] is False
    assert "explicit_funeralhome_structured_type_required" in decision["reasons"]


def test_incomplete_address_is_exception():
    data = verification()["extracted_data"] | {"postcode": None, "has_complete_branch_address": False}
    decision = assess_auto_approval(candidate_url="https://example.test",
                                   verification=verification(extracted_data=data))
    assert decision["eligible"] is False
    assert "valid_uk_postcode_required" in decision["reasons"]


def test_duplicate_provider_or_branch_is_exception():
    decision = assess_auto_approval(
        candidate_url="https://example.test", verification=verification(),
        existing_providers=[{"trading_name": "Example Funeral Directors", "website": None}],
    )
    assert decision["eligible"] is False
    assert "existing_provider_name_collision" in decision["reasons"]

    decision = assess_auto_approval(
        candidate_url="https://example.test", verification=verification(),
        existing_branches=[{"postcode": "YO1 1AA", "telephone": None}],
    )
    assert decision["eligible"] is False
    assert "existing_branch_postcode_collision" in decision["reasons"]


def test_candidate_website_domain_mismatch_is_exception():
    data = verification()["extracted_data"] | {"website": "https://different.test"}
    decision = assess_auto_approval(candidate_url="https://example.test",
                                   verification=verification(extracted_data=data))
    assert decision["eligible"] is False
    assert "candidate_and_structured_website_domain_mismatch" in decision["reasons"]


def test_global_switch_and_confidence_threshold_are_respected():
    decision = assess_auto_approval(candidate_url="https://example.test",
                                   verification=verification(), enabled=False)
    assert decision["eligible"] is False
    assert "automatic_approval_disabled" in decision["reasons"]

    decision = assess_auto_approval(candidate_url="https://example.test",
                                   verification=verification(), minimum_confidence=0.97)
    assert decision["eligible"] is False
    assert "confidence_below_threshold" in decision["reasons"]


def test_companies_house_name_mismatch_is_exception():
    decision = assess_auto_approval(candidate_url="https://example.test",
                                   verification=verification(),
                                   candidate_company_name="Unrelated Holdings Limited")
    assert decision["eligible"] is False
    assert "company_name_relationship_not_confirmed" in decision["reasons"]


def test_non_https_declared_website_is_exception():
    data = verification()["extracted_data"] | {"website": "http://example.test"}
    decision = assess_auto_approval(candidate_url="https://example.test",
                                   verification=verification(extracted_data=data),
                                   candidate_company_name="Example Funeral Services Ltd")
    assert decision["eligible"] is False
    assert "candidate_and_structured_website_domain_mismatch" in decision["reasons"]


def test_legacy_http_provider_website_domain_collision_is_detected():
    decision = assess_auto_approval(
        candidate_url="https://www.example.test", verification=verification(),
        candidate_company_name="Example Funeral Services Ltd",
        existing_providers=[{"trading_name": "Example Funeral Group", "website": "http://example.test"}],
    )
    assert decision["eligible"] is False
    assert "existing_provider_domain_collision" in decision["reasons"]


def test_provider_route_fails_closed_without_official_england_boundary():
    decision = assess_auto_approval(
        candidate_url="https://example.test", verification=verification(),
        candidate_company_name="Example Funeral Services Ltd",
    )
    assert decision["eligible"] is False
    assert "official_england_boundary_not_confirmed" in decision["reasons"]


def test_provider_route_rejects_point_outside_england():
    decision = assess_auto_approval(
        candidate_url="https://example.test", verification=verification(),
        candidate_company_name="Example Funeral Services Ltd", point_in_england=False,
    )
    assert decision["eligible"] is False
    assert "point_outside_official_england_boundary" in decision["reasons"]
