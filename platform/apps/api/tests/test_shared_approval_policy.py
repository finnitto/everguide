from app.approval_policy import evaluate_common_evidence


def passing_evidence(**overrides):
    values = {
        "access_verified": True,
        "robots_allowed": True,
        "complete_branch_address": True,
        "postcode": "YO1 1AA",
        "telephone": "01904 123456",
        "confidence": 0.97,
        "minimum_confidence": 0.94,
        "enabled": True,
    }
    values.update(overrides)
    return values


def test_common_policy_accepts_complete_verified_evidence():
    result = evaluate_common_evidence(**passing_evidence())
    assert result["eligible"] is True
    assert result["reasons"] == []
    assert result["policy_version"] == "shared-provider-approval-v1.0"


def test_common_policy_fails_closed_for_unknown_or_missing_evidence():
    result = evaluate_common_evidence(**passing_evidence(
        access_verified=False,
        robots_allowed=False,
        complete_branch_address=False,
        postcode="not a postcode",
        telephone=None,
        confidence=None,
    ))
    assert result["eligible"] is False
    assert set(result["reasons"]) == {
        "first_party_website_access_not_verified",
        "robots_permission_not_confirmed",
        "complete_branch_address_not_confirmed",
        "valid_uk_postcode_required",
        "telephone_required",
        "confidence_below_threshold",
    }


def test_common_policy_respects_global_approval_switch():
    result = evaluate_common_evidence(**passing_evidence(enabled=False))
    assert result["eligible"] is False
    assert result["reasons"] == ["automatic_approval_disabled"]
