"""Deterministic high-confidence provider auto-approval rules.

Only first-party provider website evidence with explicit FuneralHome structured
identity, a complete UK branch address and a telephone can pass. Uncertain
identity, source/domain mismatch, incomplete evidence or duplicate signals are
routed to the exception queue. This module never performs network access.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

RULESET_VERSION = "provider-auto-approval-v1.1"
UK_POSTCODE_RE = re.compile(r"^(?:GIR\s?0AA|[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2})$", re.I)


def _normalise_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _normalise_phone(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _host(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip()
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parsed = urlsplit(raw)
        if parsed.scheme.lower() != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
            return None
        host = (parsed.hostname or "").lower().removeprefix("www.").rstrip(".")
    except ValueError:
        return None
    return host or None


def _domain_for_matching(value: str | None) -> str | None:
    """Read a hostname for collision detection, including legacy HTTP URLs."""
    if not value:
        return None
    raw = value.strip()
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parsed = urlsplit(raw)
        if parsed.username or parsed.password or parsed.port not in (None, 80, 443):
            return None
        return (parsed.hostname or "").lower().removeprefix("www.").rstrip(".") or None
    except ValueError:
        return None


def _same_domain(left: str | None, right: str | None) -> bool:
    a, b = _domain_for_matching(left), _domain_for_matching(right)
    if not a or not b:
        return False
    return a == b or a.endswith("." + b) or b.endswith("." + a)


def _same_site(candidate_url: str | None, extracted_url: str | None) -> bool:
    candidate_host, extracted_host = _host(candidate_url), _host(extracted_url)
    if not candidate_host or not extracted_host:
        return False
    return candidate_host == extracted_host or candidate_host.endswith("." + extracted_host) or extracted_host.endswith("." + candidate_host)


def assess_auto_approval(
    *, candidate_url: str,
    verification: dict,
    candidate_company_name: str | None = None,
    existing_providers: list[dict] | None = None,
    existing_branches: list[dict] | None = None,
    enabled: bool = True,
    minimum_confidence: float = 0.94,
) -> dict:
    """Return a deterministic pass/hold decision and machine-readable reasons."""
    existing_providers = existing_providers or []
    existing_branches = existing_branches or []
    data = verification.get("extracted_data") or {}
    reasons: list[str] = []

    if not enabled:
        reasons.append("automatic_approval_disabled")
    if verification.get("status") != "reachable":
        reasons.append("website_not_reachable")
    if verification.get("robots_allowed") is not True:
        reasons.append("robots_permission_not_confirmed")
    if not (200 <= int(verification.get("http_status") or 0) < 300):
        reasons.append("http_success_not_confirmed")
    if "text/html" not in str(verification.get("content_type") or "").lower():
        reasons.append("html_content_not_confirmed")

    if data.get("source_type") != "schema_org_funeralhome":
        reasons.append("explicit_funeralhome_structured_type_required")
    if not data.get("name") or len(_normalise_name(data.get("name"))) < 4:
        reasons.append("provider_name_missing_or_invalid")
    if not data.get("street") or not data.get("town"):
        reasons.append("complete_branch_address_required")
    postcode = re.sub(r"\s+", " ", str(data.get("postcode") or "")).strip().upper()
    if not postcode or not UK_POSTCODE_RE.fullmatch(postcode):
        reasons.append("valid_uk_postcode_required")
    if not data.get("telephone") or len(_normalise_phone(data.get("telephone"))) < 9:
        reasons.append("telephone_required")
    if not data.get("has_complete_branch_address"):
        reasons.append("complete_branch_address_not_confirmed")
    try:
        confidence = float(data.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0
    if confidence < minimum_confidence:
        reasons.append("confidence_below_threshold")
    if not _same_site(candidate_url, data.get("website") or candidate_url):
        reasons.append("candidate_and_structured_website_domain_mismatch")
    if candidate_company_name:
        ignored = {"limited", "ltd", "plc", "funeral", "director", "directors", "services", "the", "and", "group", "holdings", "company"}
        legal_tokens = {t for t in re.findall(r"[a-z0-9]+", candidate_company_name.lower()) if len(t) > 2 and t not in ignored}
        provider_tokens = {t for t in re.findall(r"[a-z0-9]+", str(data.get("name") or "").lower()) if len(t) > 2 and t not in ignored}
        shared = legal_tokens & provider_tokens
        if not legal_tokens or not provider_tokens or not shared or len(shared) / max(1, min(len(legal_tokens), len(provider_tokens))) < 0.5:
            reasons.append("company_name_relationship_not_confirmed")

    name_key = _normalise_name(data.get("name"))
    phone_key = _normalise_phone(data.get("telephone"))
    domain = _host(candidate_url)
    for provider in existing_providers:
        if name_key and name_key == _normalise_name(provider.get("trading_name")):
            reasons.append("existing_provider_name_collision")
        if domain and _domain_for_matching(provider.get("website")) and _same_domain(candidate_url, provider.get("website")):
            reasons.append("existing_provider_domain_collision")
    for branch in existing_branches:
        existing_postcode = re.sub(r"\s+", "", str(branch.get("postcode") or "")).upper()
        if postcode and existing_postcode == postcode.replace(" ", ""):
            reasons.append("existing_branch_postcode_collision")
        if phone_key and phone_key == _normalise_phone(branch.get("telephone")):
            reasons.append("existing_branch_telephone_collision")

    # Preserve order while removing duplicate reason strings.
    reasons = list(dict.fromkeys(reasons))
    return {
        "eligible": not reasons,
        "decision": "auto_approve" if not reasons else "exception_review",
        "reasons": reasons,
        "ruleset_version": RULESET_VERSION,
        "confidence": confidence,
        "minimum_confidence": minimum_confidence,
    }
