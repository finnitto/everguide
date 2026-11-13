"""Evidence-led Overture candidate assessment for automated Everguide publication.

Overture is a discovery source. Its place-existence confidence is never treated
as proof of service type, branch identity, address accuracy or trading status.
This module is deterministic and side-effect free; publication is permitted
only when independent first-party verification and source-rights checks pass.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from app.candidate_quality import (
    THURROCK_OUTWARD_CODES,
    classify_service,
    is_valid_uk_postcode,
    normalise_phone,
    normalise_postcode,
    website_domain,
)

RULESET_VERSION = "overture-auto-approval-v1.0"
# Source licences are recorded, not inferred from the Overture umbrella licence.
KNOWN_LICENCES = {
    "CDLA-Permissive-2.0", "Apache-2.0", "CC0-1.0", "CC0",
}


def _https_url(value: object) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    try:
        parsed = urlsplit(raw if "://" in raw else "https://" + raw)
        return parsed.scheme.lower() == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False


def _source_licences(sources: object) -> tuple[bool, list[str]]:
    """Return whether every contributor licence is known and the licences found."""
    if isinstance(sources, str):
        import json
        try:
            sources = json.loads(sources or "[]")
        except (TypeError, ValueError):
            return False, []
    if not isinstance(sources, list) or not sources:
        return False, []
    licences = sorted({str(item.get("license") or "").strip() for item in sources if isinstance(item, dict)})
    valid = bool(licences) and all(item in KNOWN_LICENCES for item in licences)
    return valid, licences


def assess_overture_candidate(
    row: dict,
    *,
    first_party_evidence: dict | None = None,
    point_in_thurrock: bool | None = None,
    duplicate_conflict: bool = False,
    existing_provider_conflict: bool = False,
    auto_approval_enabled: bool = True,
    minimum_confidence: float = 0.94,
) -> dict:
    """Assess one Overture row; no DB writes or external requests are performed."""
    evidence = first_party_evidence or {}
    reasons: list[str] = []
    service_class = classify_service(
        name=row.get("name", ""),
        basic_category=row.get("basic_category", ""),
        taxonomy_primary=row.get("taxonomy_primary", ""),
        website=row.get("website", ""),
        description=row.get("description", ""),
    )
    if service_class != "funeral_director_candidate":
        return _result(row, "excluded", [f"not_funeral_director:{service_class}"], service_class, [], None)

    postcode = str(row.get("postcode") or "").strip().upper()
    outward = re.match(r"^([A-Z]{1,2}\d{1,2}[A-Z]?)", normalise_postcode(postcode))
    if not is_valid_uk_postcode(postcode):
        reasons.append("invalid_or_missing_uk_postcode")
    elif not outward or outward.group(1) not in THURROCK_OUTWARD_CODES:
        reasons.append("postcode_outside_thurrock_area")
    if point_in_thurrock is not True:
        reasons.append("official_thurrock_boundary_not_confirmed")
    if duplicate_conflict or str(row.get("possible_duplicate", "")).lower() in {"true", "1", "yes"}:
        reasons.append("possible_duplicate_or_branch_identity_conflict")
    if existing_provider_conflict:
        reasons.append("existing_provider_or_branch_conflict")

    source_ok, licences = _source_licences(row.get("sources_json", []))
    if not source_ok:
        reasons.append("source_level_licence_missing_or_unrecognised")

    # Overture score is provenance only. It is intentionally not a pass criterion.
    if not row.get("name") or len(str(row.get("name")).strip()) < 3:
        reasons.append("provider_name_missing")
    if not row.get("address"):
        reasons.append("overture_address_missing")
    if not normalise_phone(row.get("phone")):
        reasons.append("overture_phone_missing")
    if not _https_url(row.get("website")):
        reasons.append("official_https_website_not_available")

    # Independent evidence required for automatic publication.
    if evidence.get("source_type") != "first_party_website":
        reasons.append("independent_first_party_evidence_missing")
    if evidence.get("reachable") is not True or evidence.get("robots_allowed") is not True:
        reasons.append("first_party_website_access_not_verified")
    if evidence.get("explicit_funeral_director_service") is not True:
        reasons.append("first_party_funeral_director_service_not_confirmed")
    candidate_domain = website_domain(row.get("website"))
    evidence_url = evidence.get("website_url") or evidence.get("final_url")
    evidence_domain = website_domain(evidence_url)
    if evidence_url and (not candidate_domain or not evidence_domain or not (
        candidate_domain == evidence_domain
        or candidate_domain.endswith("." + evidence_domain)
        or evidence_domain.endswith("." + candidate_domain)
    )):
        reasons.append("first_party_website_domain_mismatch")
    if evidence.get("complete_branch_address") is not True:
        reasons.append("first_party_complete_branch_address_not_confirmed")
    if evidence.get("postcode") and normalise_postcode(evidence.get("postcode")) != normalise_postcode(postcode):
        reasons.append("first_party_postcode_does_not_match_overture")
    overture_phone = normalise_phone(row.get("phone"))
    evidence_phone = normalise_phone(evidence.get("telephone"))
    if evidence.get("telephone") and (not overture_phone or not evidence_phone or overture_phone != evidence_phone):
        reasons.append("independent_telephone_match_not_confirmed")
    elif not evidence.get("telephone"):
        reasons.append("independent_telephone_match_not_confirmed")
    try:
        confidence = float(evidence.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < minimum_confidence:
        reasons.append("first_party_evidence_confidence_below_threshold")
    if evidence.get("conflicting_identity_or_branch_evidence") is True:
        reasons.append("conflicting_identity_or_branch_evidence")
    if not auto_approval_enabled:
        reasons.append("automatic_approval_disabled")

    reasons = list(dict.fromkeys(reasons))
    if not reasons:
        outcome = "auto_approved_eligible"
    elif any(reason in reasons for reason in (
        "postcode_outside_thurrock_area", "possible_duplicate_or_branch_identity_conflict",
        "existing_provider_or_branch_conflict", "first_party_website_domain_mismatch",
        "first_party_postcode_does_not_match_overture", "conflicting_identity_or_branch_evidence",
    )):
        outcome = "exception_review"
    else:
        outcome = "awaiting_enrichment"
    return _result(row, outcome, reasons, service_class, licences, confidence)


def _result(row, outcome, reasons, service_class, licences, confidence):
    return {
        "source": "Overture Places",
        "gers_id": row.get("gers_id", ""),
        "candidate_name": row.get("name", ""),
        "postcode": row.get("postcode", ""),
        "source_confidence": row.get("confidence", ""),
        "first_party_confidence": confidence,
        "service_class": service_class,
        "outcome": outcome,
        "reasons": ";".join(reasons),
        "source_licences": ";".join(licences),
        "ruleset_version": RULESET_VERSION,
    }
