"""Queue approved Overture locations for a later, rights-aware price enrichment pass.

Queueing only records an idempotent request marker. It does not fetch a website,
extract prices, create PricingEvidence, approve evidence, or publish a provider.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import AuditEvent, OvertureCandidate, Provider


PRICING_ENRICHMENT_KEY = "pricing_enrichment"
PRICING_ENRICHMENT_VERSION = "pricing-enrichment-v1"

# These states must not be reset by repeated approval events or backfills.
# A blocked/permission-required record needs an explicit permission/retry action.
NON_REQUEUEABLE_STATES = {
    "queued",
    "in_progress",
    "completed",
    "no_prices_found",
    "blocked",
    "awaiting_permission",
    "needs_source",
}


def queue_overture_candidate_for_pricing(
    db: Session,
    candidate: OvertureCandidate,
    *,
    trigger: str,
    requested_by: str,
) -> bool:
    """Mark one approved candidate for price enrichment; return True if newly queued."""
    evidence = dict(candidate.first_party_evidence or {})
    current = evidence.get(PRICING_ENRICHMENT_KEY)
    current = dict(current) if isinstance(current, dict) else {}
    if current.get("status") in NON_REQUEUEABLE_STATES:
        return False

    now = datetime.now(timezone.utc)
    current.update({
        "status": "queued",
        "version": PRICING_ENRICHMENT_VERSION,
        "trigger": trigger,
        "requested_by": requested_by or "system",
        "requested_at": now.isoformat(),
        "attempt_count": max(0, int(current.get("attempt_count") or 0)),
        "last_error": None,
    })
    evidence[PRICING_ENRICHMENT_KEY] = current
    candidate.first_party_evidence = evidence

    db.add(AuditEvent(
        entity_type="overture_candidate",
        entity_id=candidate.id,
        action="pricing_enrichment_queued",
        detail={
            "gers_id": candidate.gers_id,
            "provider_id": candidate.provider_id,
            "branch_id": candidate.branch_id,
            "status": "queued",
            "trigger": trigger,
            "queue_version": PRICING_ENRICHMENT_VERSION,
        },
        actor=requested_by or "system",
    ))
    return True


def queue_approved_overture_candidates_for_pricing(
    db: Session,
    *,
    requested_by: str,
) -> dict:
    """Idempotent backfill for Overture candidates linked to approved FD providers."""
    candidates = (
        db.query(OvertureCandidate)
        .join(Provider, Provider.id == OvertureCandidate.provider_id)
        .filter(
            Provider.provider_type == "funeral_director",
            Provider.status.in_(("approved", "published")),
            OvertureCandidate.provider_id.is_not(None),
        )
        .order_by(OvertureCandidate.id.asc())
        .all()
    )

    queued = 0
    already_marked = 0
    for candidate in candidates:
        if queue_overture_candidate_for_pricing(
            db,
            candidate,
            trigger="approved_candidate_backfill",
            requested_by=requested_by,
        ):
            queued += 1
        else:
            already_marked += 1

    return {
        "matched_candidates": len(candidates),
        "queued": queued,
        "already_marked": already_marked,
    }
