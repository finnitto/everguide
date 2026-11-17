"""Overture-first approval policy for Everguide funeral-director locations.

Overture is the authoritative discovery and branch-location source. Companies
House and provider websites are corroborating sources: missing corroboration
does not block an otherwise valid Overture record. Only explicit, material
conflicts are routed to exception review. This module is deterministic and
side-effect free; publication remains guarded by the worker write gate.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from app.candidate_quality import (
    THURROCK_OUTWARD_CODES,
    classify_service,
    is_valid_uk_postcode,
    normalise_postcode,
)

RULESET_VERSION = "overture-first-approval-v2.0"
KNOWN_LICENCES = {"CDLA-Permissive-2.0", "Apache-2.0", "CC0-1.0", "CC0"}


def _source_licences(sources: object) -> tuple[bool, list[str]]:
    if isinstance(sources, str):
        import json
        try:
            sources = json.loads(sources or "[]")
        except (TypeError, ValueError):
            return False, []
    if not isinstance(sources, list) or not sources:
        return False, []
    if any(not isinstance(item, dict) or not str(item.get("license") or "").strip() for item in sources):
        return False, sorted({str(item.get("license") or "").strip() for item in sources if isinstance(item, dict) and item.get("license")})
    licences = sorted({str(item.get("license") or "").strip() for item in sources})
    return bool(licences) and all(item in KNOWN_LICENCES for item in licences), licences


def assess_overture_candidate(
    row: dict,
    *,
    first_party_evidence: dict | None = None,
    point_in_thurrock: bool | None = None,
    point_in_england: bool | None = None,
    geography_scope: str = "thurrock",
    duplicate_conflict: bool = False,
    existing_provider_conflict: bool = False,
    auto_approval_enabled: bool = True,
    minimum_confidence: float = 0.94,
) -> dict:
    """Assess Overture integrity and explicit conflicts without requiring enrichment."""
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
    scope = str(geography_scope or "thurrock").lower()
    outward = re.match(r"^([A-Z]{1,2}\d{1,2}[A-Z]?)", normalise_postcode(postcode))
    if not is_valid_uk_postcode(postcode):
        reasons.append("invalid_or_missing_uk_postcode")
    if not row.get("address_line_1") and not row.get("address"):
        reasons.append("overture_street_address_missing")
    if not row.get("town_city") and not row.get("town") and not row.get("locality"):
        reasons.append("overture_locality_missing")

    if scope == "england":
        if point_in_england is False:
            reasons.append("point_outside_official_england_boundary")
        elif point_in_england is not True:
            reasons.append("official_england_boundary_not_confirmed")
    else:
        if not outward or outward.group(1) not in THURROCK_OUTWARD_CODES:
            reasons.append("postcode_outside_thurrock_area")
        if point_in_thurrock is False:
            reasons.append("point_outside_official_thurrock_boundary")
        elif point_in_thurrock is not True:
            reasons.append("official_thurrock_boundary_not_confirmed")

    if duplicate_conflict or str(row.get("possible_duplicate", "")).lower() in {"true", "1", "yes"}:
        reasons.append("possible_same_name_postcode_match")
    if existing_provider_conflict:
        reasons.append("existing_provider_or_branch_conflict")

    source_ok, licences = _source_licences(row.get("sources_json", []))
    if not source_ok:
        reasons.append("source_level_licence_missing_or_unrecognised")
    if not str(row.get("name") or "").strip() or len(str(row.get("name")).strip()) < 3:
        reasons.append("provider_name_missing")

    # Supporting evidence only blocks when an upstream assessor has positively
    # identified a material contradiction. Missing, unreachable or absent
    # websites and absent Companies House links are not conflicts.
    conflict_codes = evidence.get("conflict_codes") or []
    if evidence.get("conflicting_identity_or_branch_evidence") is True:
        reasons.append("conflicting_identity_or_branch_evidence")
    for code in conflict_codes:
        if code in {
            "official_site_branch_closed",
            "official_site_different_operator_at_same_address",
            "verified_companies_house_entity_dissolved",
            "verified_companies_house_identity_conflict",
        }:
            reasons.append(str(code))

    reasons = list(dict.fromkeys(reasons))
    if not reasons:
        outcome = "auto_approved_eligible" if auto_approval_enabled else "awaiting_enrichment"
        if not auto_approval_enabled:
            reasons.append("automatic_approval_disabled")
    elif any(reason in reasons for reason in (
        "postcode_outside_thurrock_area",
        "possible_same_name_postcode_match",
        "existing_provider_or_branch_conflict",
        "point_outside_official_thurrock_boundary",
        "point_outside_official_england_boundary",
        "source_level_licence_missing_or_unrecognised",
        "conflicting_identity_or_branch_evidence",
        "official_site_branch_closed",
        "official_site_different_operator_at_same_address",
        "verified_companies_house_entity_dissolved",
        "verified_companies_house_identity_conflict",
    )):
        outcome = "exception_review"
    else:
        outcome = "awaiting_enrichment"

    confidence = None
    try:
        confidence = float(row.get("confidence")) if row.get("confidence") not in (None, "") else None
    except (TypeError, ValueError):
        pass
    return _result(row, outcome, reasons, service_class, licences, confidence)


def _result(row, outcome, reasons, service_class, licences, confidence):
    return {
        "source": "Overture Places",
        "gers_id": row.get("gers_id", ""),
        "candidate_name": row.get("name", ""),
        "postcode": row.get("postcode", ""),
        "source_confidence": row.get("confidence", ""),
        "first_party_confidence": None,
        "confidence": confidence,
        "service_class": service_class,
        "outcome": outcome,
        "reasons": ";".join(reasons),
        "source_licences": ";".join(licences),
        "ruleset_version": RULESET_VERSION,
        "supporting_evidence_policy": "optional_conflict_detection_only",
    }
