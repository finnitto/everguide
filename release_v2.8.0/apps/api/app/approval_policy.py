"""Shared, side-effect-free approval gates used by every discovery adapter.

Source adapters remain responsible for provenance, source rights, identity matching,
and geography. This module owns the common first-party evidence quality gates so
that one discovery route cannot silently apply weaker evidence standards.
"""
from __future__ import annotations

import re

POLICY_VERSION = "shared-provider-approval-v1.0"
UK_POSTCODE_RE = re.compile(r"^(?:GIR\s?0AA|[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2})$", re.I)


def evaluate_common_evidence(
    *,
    access_verified: bool,
    robots_allowed: bool,
    complete_branch_address: bool,
    postcode: object,
    telephone: object,
    confidence: object,
    minimum_confidence: float = 0.94,
    enabled: bool = True,
) -> dict:
    """Evaluate common approval requirements and return stable reason codes.

    `access_verified` means the adapter has positively verified a successful,
    usable first-party website response. A missing/unknown value must be False.
    `complete_branch_address` must be affirmative, not inferred from partial data.
    """
    reasons: list[str] = []
    if not enabled:
        reasons.append("automatic_approval_disabled")
    if access_verified is not True:
        reasons.append("first_party_website_access_not_verified")
    if robots_allowed is not True:
        reasons.append("robots_permission_not_confirmed")
    if complete_branch_address is not True:
        reasons.append("complete_branch_address_not_confirmed")

    postcode_text = re.sub(r"\s+", " ", str(postcode or "")).strip().upper()
    if not postcode_text or not UK_POSTCODE_RE.fullmatch(postcode_text):
        reasons.append("valid_uk_postcode_required")

    phone_digits = re.sub(r"\D", "", str(telephone or ""))
    if len(phone_digits) < 9:
        reasons.append("telephone_required")

    try:
        score = float(confidence or 0)
    except (TypeError, ValueError):
        score = 0.0
    try:
        threshold = float(minimum_confidence)
    except (TypeError, ValueError):
        threshold = 0.94
    if score < threshold:
        reasons.append("confidence_below_threshold")

    return {
        "eligible": not reasons,
        "reasons": reasons,
        "policy_version": POLICY_VERSION,
        "confidence": score,
        "minimum_confidence": threshold,
    }
