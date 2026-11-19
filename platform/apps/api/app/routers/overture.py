from datetime import datetime, timezone
from collections import Counter
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, distinct
from sqlalchemy.orm import Session
from app.database import get_db
from app.config import settings
from app.models import OvertureCandidate, OvertureImportRun, Provider, AuditEvent
from app.pricing_enrichment import (
    queue_approved_overture_candidates_for_pricing,
    queue_overture_candidate_for_pricing,
    dispatch_queued_price_enrichment,
)
from app.overture_tasks import (
    process_overture_candidates, _is_non_first_party_url, _normalised_assessment_row,
    _overture_website_urls,
)
from app.candidate_quality import OVERTURE_IMPORT_SERVICE_TYPES, classify_service
from app.overture_feed import poll_latest_overture_release
from app.identity_review_auth import require_identity_reviewer

router = APIRouter(prefix="/api/v1/overture", tags=["Overture discovery and approval"], dependencies=[Depends(require_identity_reviewer)])
OVERTURE_ENRICHMENT_BATCH_SIZE = 20
OVERTURE_ENRICHMENT_FANOUT = 8

class OvertureImportPayload(BaseModel):
    records: list[dict] = Field(min_length=1, max_length=5000)
    source_release: str | None = Field(default=None, max_length=80)


class EnrichmentApprovalPayload(BaseModel):
    review_notes: str = Field(min_length=3, max_length=1000)


class FailedPriceRetryPayload(BaseModel):
    source_run_id: int = Field(gt=0)
    recheck_no_price_sample: bool = False


def _run_dict(run, db=None):
    metadata = ((run.outcomes or {}).get("_meta", {}) or {})
    public_metadata = {key: value for key, value in metadata.items() if key != "candidate_ids"}
    target_count = int(metadata.get("target_count") or run.records_received or 0)
    candidates_processed = int(run.records_processed or 0)
    candidate_ids = metadata.get("candidate_ids") or []
    if (db is not None and metadata.get("run_type") == "enrichment_retry"
            and candidate_ids and run.status in {"queued", "running", "processing", "price_enrichment"}):
        # Candidate rows commit independently within each worker batch. Count
        # their completion timestamps for live portal progress instead of
        # making users wait for the whole batch to finish.
        candidates_processed = db.query(func.count(OvertureCandidate.id)).filter(
            OvertureCandidate.id.in_([int(value) for value in candidate_ids]),
            OvertureCandidate.last_checked_at.is_not(None),
        ).scalar() or 0
    prices_queued = int(metadata.get("pricing_enrichment_queued") or 0)
    prices_terminal = int(metadata.get("pricing_enrichment_terminal") or 0)
    price_outcomes = metadata.get("pricing_enrichment_outcomes") or {}
    retryable_price_failures = 0
    if db is not None and metadata.get("run_type") in {"enrichment_retry", "price_retry"} and candidate_ids:
        failure_rows = db.query(OvertureCandidate.first_party_evidence).filter(
            OvertureCandidate.id.in_([int(value) for value in candidate_ids]),
        ).all()
        retryable_price_failures = sum(
            1 for (evidence,) in failure_rows
            if ((evidence or {}).get("pricing_enrichment") or {}).get("status") == "failed"
            and int(((evidence or {}).get("pricing_enrichment") or {}).get("overture_run_id") or 0) == int(run.id)
        )
    if (db is not None and metadata.get("run_type") in {"enrichment_retry", "price_retry"}
            and candidate_ids and run.status in {"queued", "running", "processing", "price_enrichment"}):
        # Per-candidate markers are committed independently by the price
        # workers. Read them directly so concurrent status updates cannot make
        # the portal counters lag or lose a terminal result.
        price_rows = db.query(OvertureCandidate.id, OvertureCandidate.first_party_evidence).filter(
            OvertureCandidate.id.in_([int(value) for value in candidate_ids]),
        ).all()
        price_outcomes = {}
        prices_queued = 0
        prices_terminal = 0
        for _, evidence in price_rows:
            marker = (evidence or {}).get("pricing_enrichment") or {}
            if int(marker.get("overture_run_id") or 0) != int(run.id):
                continue
            prices_queued += 1
            terminal_status = marker.get("run_terminal_status")
            if terminal_status:
                prices_terminal += 1
                price_outcomes[terminal_status] = price_outcomes.get(terminal_status, 0) + 1
    return {"id": run.id, "status": run.status, "source_release": run.source_release,
        "records_received": run.records_received, "records_imported": run.records_imported,
        "records_updated": run.records_updated, "records_processed": run.records_processed,
        "progress": {"candidates_total": target_count,
            "candidates_processed": candidates_processed,
            "candidates_percent": round(100 * min(candidates_processed, target_count) / target_count) if target_count else 100,
            "prices_queued": prices_queued, "prices_terminal": prices_terminal,
            "prices_pending": max(0, prices_queued - prices_terminal),
            "retryable_price_failures": retryable_price_failures,
            "price_outcomes": price_outcomes},
        "outcomes": {**{key: value for key, value in (run.outcomes or {}).items() if key != "_meta"}, "_meta": public_metadata},
        "ingestion_method": metadata.get("ingestion_method", "manual_csv"), "error_message": run.error_message,
        "created_at": run.created_at, "started_at": run.started_at, "completed_at": run.completed_at}


@router.get("/status", dependencies=[Depends(require_identity_reviewer)])
def overture_status(db: Session = Depends(get_db)):
    counts = dict(db.query(OvertureCandidate.outcome, func.count(OvertureCandidate.id)).group_by(OvertureCandidate.outcome).all())
    latest = db.query(OvertureImportRun).order_by(OvertureImportRun.id.desc()).first()
    last_check = db.query(AuditEvent).filter(AuditEvent.entity_type == "overture_feed").order_by(AuditEvent.id.desc()).first()
    return {"pipeline_enabled": True, "automatic_processing": settings.overture_auto_process,
        "automatic_enrichment_enabled": settings.overture_auto_process and settings.price_enrichment_enabled,
        "price_enrichment_enabled": settings.price_enrichment_enabled,
        "feed_enabled": settings.overture_feed_enabled,
        "scheduled_tasks_enabled": settings.overture_scheduled_tasks_enabled,
        "feed_schedule_enabled": settings.overture_feed_enabled and settings.overture_scheduled_tasks_enabled,
        "feed_schedule": f"Daily at {settings.overture_feed_daily_hour:02d}:{settings.overture_feed_daily_minute:02d} Europe/London",
        "last_feed_check": {"action": last_check.action, "detail": last_check.detail, "created_at": last_check.created_at} if last_check else None,
        "automatic_publication_enabled": settings.auto_approve_providers,
        "minimum_first_party_confidence": settings.auto_approval_min_confidence,
        "overture_confidence_used_as_approval_proof": False,
        "candidate_count": db.query(OvertureCandidate).count(), "outcomes": counts,
        "published_providers_from_overture": db.query(func.count(distinct(Provider.id))).join(OvertureCandidate, OvertureCandidate.provider_id == Provider.id).filter(OvertureCandidate.outcome == "auto_approved_published").scalar() or 0,
        "latest_import": _run_dict(latest, db) if latest else None}


@router.post("/imports", status_code=410)
def start_overture_import(reviewer: str = Depends(require_identity_reviewer)):
    """Retire caller-supplied candidate payloads; only the official Overture feed may ingest candidates."""
    raise HTTPException(
        status_code=410,
        detail="Manual candidate imports are disabled. Initial candidates are ingested only from the official Overture Places feed.",
    )


@router.post("/feed/check", status_code=202)
def check_overture_feed_now(reviewer: str = Depends(require_identity_reviewer)):
    if not settings.overture_feed_enabled:
        raise HTTPException(409, detail="Automatic Overture feed ingestion is disabled in configuration.")
    task = poll_latest_overture_release.delay()
    return {"status": "queued", "task_id": task.id, "message": "Checking Overture STAC for a new England-wide Places release."}


@router.post("/process", status_code=202)
def queue_overture_processing(reviewer: str = Depends(require_identity_reviewer), db: Session = Depends(get_db)):
    """Start or return the full tracked run for every candidate awaiting enrichment."""
    if not settings.price_enrichment_enabled:
        raise HTTPException(409, "Price enrichment is disabled.")
    recent_runs = db.query(OvertureImportRun).filter(
        OvertureImportRun.status.in_(["queued", "running", "processing", "price_enrichment"]),
    ).order_by(OvertureImportRun.id.desc()).limit(30).all()
    active_run = next((run for run in recent_runs
        if ((run.outcomes or {}).get("_meta", {}) or {}).get("run_type") in {"enrichment_retry", "price_retry"}), None)
    if active_run:
        return {"status": active_run.status, "task_id": active_run.celery_task_id,
                "run_id": active_run.id, "candidates_queued": active_run.records_received,
                "message": "The full Overture enrichment run is already active."}

    candidates = db.query(OvertureCandidate).filter(
        OvertureCandidate.outcome.in_(["awaiting_enrichment", "exception_review"]),
        OvertureCandidate.status.in_(["awaiting_enrichment", "exception_review"]),
    ).order_by(OvertureCandidate.id.asc()).all()
    # Reassess all waiting candidates plus exceptions with at least one URL
    # supplied by Overture. The worker verifies those URLs and retains genuine
    # identity, source or location conflicts in the exception queue.
    terminal_price_states = {"completed", "no_prices_found", "blocked"}
    selected = []
    for candidate in candidates:
        if candidate.outcome == "awaiting_enrichment":
            selected.append(candidate)
            continue
        if not _overture_website_urls(dict(candidate.raw_data or {})):
            continue
        price_state = dict((candidate.first_party_evidence or {}).get("pricing_enrichment") or {}).get("status")
        if price_state in terminal_price_states:
            continue
        selected.append(candidate)
    candidate_ids = [candidate.id for candidate in selected]
    if not candidate_ids:
        return {"status": "empty", "task_id": None, "run_id": None, "candidates_queued": 0,
                "message": "No Overture candidates are waiting for enrichment."}
    for candidate in selected:
        candidate.last_checked_at = None
    initial_batches = min(
        OVERTURE_ENRICHMENT_FANOUT,
        max(1, (len(candidate_ids) + OVERTURE_ENRICHMENT_BATCH_SIZE - 1) // OVERTURE_ENRICHMENT_BATCH_SIZE),
    )
    run = OvertureImportRun(
        status="queued", records_received=len(candidate_ids), records_processed=0,
        outcomes={"_meta": {"ingestion_method": "manual_enrichment_retry",
            "run_type": "enrichment_retry", "candidate_ids": candidate_ids,
            "target_count": len(candidate_ids), "requested_by": reviewer,
            "processing_batches_queued": initial_batches,
            "pricing_enrichment_queued": 0, "pricing_enrichment_terminal": 0,
            "pricing_enrichment_outcomes": {}}},
    )
    db.add(run)
    db.flush()
    db.add(AuditEvent(
        entity_type="overture_import_run",
        entity_id=run.id,
        action="full_overture_enrichment_run_queued",
        actor=reviewer,
        detail={"candidate_count": len(candidate_ids), "url_bearing_exceptions_included": sum(
            1 for candidate in selected if candidate.outcome == "exception_review"
        ), "run_type": "enrichment_retry"},
    ))
    db.commit()
    try:
        tasks = [
            process_overture_candidates.delay(run.id, OVERTURE_ENRICHMENT_BATCH_SIZE)
            for _ in range(initial_batches)
        ]
        run.celery_task_id = tasks[0].id
        db.commit()
    except Exception as exc:
        db.rollback()
        failed_run = db.get(OvertureImportRun, run.id)
        if failed_run:
            failed_run.status = "failed"
            failed_run.error_message = f"Could not enqueue enrichment worker: {str(exc)[:500]}"
            failed_run.completed_at = datetime.now(timezone.utc)
            db.commit()
        raise HTTPException(503, "Could not enqueue the Overture enrichment run.") from exc
    return {"status": "queued", "task_id": run.celery_task_id, "run_id": run.id,
            "candidates_queued": len(candidate_ids),
            "tasks_dispatched": len(tasks),
            "message": f"Queued a full enrichment run for {len(candidate_ids)} Overture candidates."}


@router.get("/imports", dependencies=[Depends(require_identity_reviewer)])
def list_overture_imports(limit: int = 20, db: Session = Depends(get_db)):
    rows = db.query(OvertureImportRun).order_by(OvertureImportRun.id.desc()).limit(min(max(limit, 1), 100)).all()
    return {"items": [_run_dict(row, db) for row in rows]}


@router.post("/pricing-enrichment/queue-approved")
def queue_approved_candidates_for_pricing(
    reviewer: str = Depends(require_identity_reviewer),
    db: Session = Depends(get_db),
):
    """Idempotently mark already-approved, linked Overture candidates for price enrichment.

    This endpoint only writes queue metadata. It does not fetch websites or prices.
    """
    result = queue_approved_overture_candidates_for_pricing(db, requested_by=reviewer)
    db.add(AuditEvent(
        entity_type="pricing_enrichment_queue",
        entity_id=0,
        action="approved_candidate_backfill_completed",
        detail=result,
        actor=reviewer,
    ))
    db.commit()
    dispatched = dispatch_queued_price_enrichment(result.get("queued_candidate_ids") or [])
    return {"status": "completed", **result,
            "tasks_dispatched": dispatched,
            "message": "Verified first-party Overture websites linked to funeral-director records are marked for price enrichment, independent of publication status."}


@router.post("/pricing-enrichment/retry-failed", status_code=202)
def retry_failed_price_enrichment(
    payload: FailedPriceRetryPayload,
    reviewer: str = Depends(require_identity_reviewer),
    db: Session = Depends(get_db),
):
    """Retry failed price tasks from a tracked Overture enrichment run."""
    if not settings.price_enrichment_enabled:
        raise HTTPException(409, "Price enrichment is disabled.")
    source_run = db.get(OvertureImportRun, payload.source_run_id)
    if source_run is None:
        raise HTTPException(404, "Source enrichment run not found.")
    source_meta = dict(((source_run.outcomes or {}).get("_meta") or {}))
    source_ids = [int(value) for value in source_meta.get("candidate_ids") or []]
    if source_meta.get("run_type") not in {"enrichment_retry", "price_retry"} or not source_ids:
        raise HTTPException(409, "Only a tracked Overture enrichment run can be used as the retry source.")

    active_runs = db.query(OvertureImportRun).filter(
        OvertureImportRun.status.in_(["queued", "running", "processing", "price_enrichment"]),
    ).order_by(OvertureImportRun.id.desc()).limit(30).all()
    if any(((row.outcomes or {}).get("_meta") or {}).get("run_type") == "price_retry" for row in active_runs):
        raise HTTPException(409, "A tracked price retry run is already active.")

    failed = []
    no_price_sample = []
    for candidate in db.query(OvertureCandidate).filter(OvertureCandidate.id.in_(source_ids)).order_by(OvertureCandidate.id.asc()).all():
        marker = dict(((candidate.first_party_evidence or {}).get("pricing_enrichment") or {}))
        if (marker.get("status") == "failed"
                and int(marker.get("overture_run_id") or 0) == source_run.id):
            failed.append(candidate)
        elif (payload.recheck_no_price_sample and marker.get("status") == "no_prices_found"
                and int(marker.get("overture_run_id") or 0) == source_run.id
                and not marker.get("fetch_diagnostics")):
            no_price_sample.append(candidate)
    no_price_sample = no_price_sample[:5]
    candidates_to_retry = failed + no_price_sample
    if not candidates_to_retry:
        raise HTTPException(409, "No failed price tasks remain in that run.")

    retry_run = OvertureImportRun(
        status="price_enrichment", records_received=len(candidates_to_retry), records_processed=0,
        started_at=datetime.now(timezone.utc),
        outcomes={"_meta": {
            "ingestion_method": "manual_price_retry", "run_type": "price_retry",
            "candidate_ids": [candidate.id for candidate in candidates_to_retry],
            "target_count": len(candidates_to_retry), "source_run_id": source_run.id,
            "requested_by": reviewer, "pricing_enrichment_queued": len(candidates_to_retry),
            "pricing_enrichment_terminal": 0, "pricing_enrichment_outcomes": {},
        }},
    )
    db.add(retry_run)
    db.flush()
    queued_ids = []
    prior_errors = Counter()
    for candidate in candidates_to_retry:
        old_marker = dict(((candidate.first_party_evidence or {}).get("pricing_enrichment") or {}))
        prior_error = str(old_marker.get("last_error") or "unknown failure")[:500]
        prior_errors[prior_error.split(":", 1)[0]] += 1
        if queue_overture_candidate_for_pricing(
            db, candidate, trigger="retry_failed_price_enrichment",
            requested_by=reviewer, run_id=retry_run.id,
            force_retry=(old_marker.get("status") == "no_prices_found"),
        ):
            evidence = dict(candidate.first_party_evidence or {})
            marker = dict(evidence.get("pricing_enrichment") or {})
            marker.update({"retry_of_run_id": source_run.id, "previous_error": prior_error})
            evidence["pricing_enrichment"] = marker
            candidate.first_party_evidence = evidence
            queued_ids.append(candidate.id)
    if not queued_ids:
        db.rollback()
        raise HTTPException(409, "Failed price tasks changed before they could be queued.")
    retry_run.records_received = len(queued_ids)
    retry_run.outcomes = {"_meta": {
        **dict((retry_run.outcomes or {}).get("_meta") or {}),
        "candidate_ids": queued_ids, "target_count": len(queued_ids),
        "pricing_enrichment_queued": len(queued_ids),
        "previous_failure_classes": dict(prior_errors),
    }}
    db.add(AuditEvent(
        entity_type="overture_import_run", entity_id=retry_run.id,
        action="failed_price_enrichment_retry_queued", actor=reviewer,
        detail={"source_run_id": source_run.id, "candidate_count": len(queued_ids),
                "previous_failure_classes": dict(prior_errors)},
    ))
    db.commit()
    dispatched = 0
    for offset in range(0, len(queued_ids), 100):
        dispatched += dispatch_queued_price_enrichment(queued_ids[offset:offset + 100], max_tasks=100)
    if not dispatched:
        retry_run.status = "failed"
        retry_run.error_message = "No price tasks could be dispatched."
        retry_run.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(503, "Price retry run was created but tasks could not be dispatched.")
    return {"status": retry_run.status, "run_id": retry_run.id,
            "source_run_id": source_run.id, "candidates_queued": len(queued_ids),
            "no_price_sample_rechecked": min(len(no_price_sample), max(0, len(queued_ids) - len(failed))),
            "tasks_dispatched": dispatched, "previous_failure_classes": dict(prior_errors),
            "message": f"Queued {dispatched} price tasks in tracked retry run #{retry_run.id}."}


@router.post("/pricing-enrichment/run-queued", status_code=202)
def run_queued_price_enrichment(
    limit: int = 50,
    reviewer: str = Depends(require_identity_reviewer),
    db: Session = Depends(get_db),
):
    """Start a bounded batch of queued price extractions when the feature is enabled."""
    if not settings.price_enrichment_enabled:
        raise HTTPException(409, "Price enrichment is disabled.")
    candidates = (
        db.query(OvertureCandidate)
        .join(Provider, Provider.id == OvertureCandidate.provider_id)
        .filter(
            Provider.provider_type.in_(set(OVERTURE_IMPORT_SERVICE_TYPES.values())),
        )
        .order_by(OvertureCandidate.id.asc())
        .all()
    )
    page_size = min(max(int(limit), 1), 100)
    queued_ids = [
        row.id for row in candidates
        if (dict(row.first_party_evidence or {}).get("pricing_enrichment") or {}).get("status") == "queued"
    ][:page_size]
    dispatched = dispatch_queued_price_enrichment(queued_ids, max_tasks=page_size)
    return {"status": "queued" if dispatched else "empty",
            "candidate_ids": queued_ids[:page_size], "tasks_dispatched": dispatched,
            "batch_limit": page_size}


@router.get("/pricing-enrichment/queue")
def list_pricing_enrichment_queue(
    status: str = "queued",
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """List candidate price-enrichment state and extracted-price counts."""
    rows = (
        db.query(OvertureCandidate, Provider)
        .join(Provider, Provider.id == OvertureCandidate.provider_id)
        .filter(
            Provider.provider_type.in_(set(OVERTURE_IMPORT_SERVICE_TYPES.values())),
        )
        .order_by(OvertureCandidate.id.asc())
        .all()
    )
    queued = []
    for row, provider in rows:
        metadata = dict(row.first_party_evidence or {}).get("pricing_enrichment") or {}
        if str(metadata.get("status") or "not_requested") != status:
            continue
        queued.append({
            "candidate_id": row.id,
            "gers_id": row.gers_id,
            "candidate_name": row.candidate_name,
            "postcode": row.postcode,
            "provider_id": row.provider_id,
            "provider_status": provider.status,
            "branch_id": row.branch_id,
            "status": metadata.get("status", "not_requested"),
            "trigger": metadata.get("trigger"),
            "requested_at": metadata.get("requested_at"),
            "requested_by": metadata.get("requested_by"),
            "attempt_count": metadata.get("attempt_count", 0),
            "website_url": (row.first_party_evidence or {}).get("website_url"),
            "last_error": metadata.get("last_error"),
            "permission_id": metadata.get("permission_id"),
        })
    start = max(0, offset)
    page_size = min(max(1, limit), 500)
    return {"count": len(queued), "items": queued[start:start + page_size],
            "limit": page_size, "offset": start, "status": status}


@router.get("/candidates", dependencies=[Depends(require_identity_reviewer)])
def list_overture_candidates(outcome: str | None = None, limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    query = db.query(OvertureCandidate)
    if outcome:
        query = query.filter(OvertureCandidate.outcome == outcome)
    total = query.count()
    rows = query.order_by(OvertureCandidate.candidate_name.asc()).offset(max(0, offset)).limit(min(max(1, limit), 500)).all()
    return {"count": total, "items": [{"id": row.id, "gers_id": row.gers_id,
        "candidate_name": row.candidate_name, "postcode": row.postcode,
        "status": row.status, "outcome": row.outcome, "assessment": row.assessment,
        "overture_website_url": _normalised_assessment_row(dict(row.raw_data or {})).get("website"),
        "first_party_evidence": row.first_party_evidence,
        "pricing_enrichment": (row.first_party_evidence or {}).get("pricing_enrichment", {"status": "not_requested"}),
        "provider_id": row.provider_id,
        "branch_id": row.branch_id, "last_checked_at": row.last_checked_at} for row in rows]}


@router.post("/candidates/{candidate_id}/approve-enrichment", status_code=202)
def approve_overture_candidate_for_enrichment(
    candidate_id: int,
    payload: EnrichmentApprovalPayload,
    reviewer: str = Depends(require_identity_reviewer),
    db: Session = Depends(get_db),
):
    """Manually release an Overture exception for enrichment only, never publication."""
    candidate = db.get(OvertureCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(404, "Overture candidate not found.")
    if candidate.outcome != "exception_review":
        raise HTTPException(409, "Only candidates in exception review can use this approval action.")
    raw = dict(candidate.raw_data or {})
    row = _normalised_assessment_row(raw)
    service_class = classify_service(
        name=row.get("name") or candidate.candidate_name,
        basic_category=row.get("basic_category"),
        taxonomy_primary=row.get("taxonomy_primary"),
        website="",
        description=row.get("description", ""),
    )
    if service_class not in OVERTURE_IMPORT_SERVICE_TYPES:
        raise HTTPException(409, "This Overture record is outside the supported funeral-sector service classes.")
    website_url = row.get("website")
    if not website_url or _is_non_first_party_url(website_url):
        raise HTTPException(409, "A provider-owned website URL supplied by Overture is required.")

    evidence = dict(candidate.first_party_evidence or {})
    approved_at = datetime.now(timezone.utc).isoformat()
    evidence["enrichment_approval"] = {
        "status": "approved_by_reviewer",
        "approved_by": reviewer,
        "approved_at": approved_at,
        "review_notes": payload.review_notes.strip(),
        "source": "overture_supplied_website_url",
    }
    candidate.first_party_evidence = evidence
    candidate.outcome = "awaiting_enrichment"
    candidate.status = "awaiting_enrichment"
    candidate.last_checked_at = None
    db.add(AuditEvent(
        entity_type="overture_candidate",
        entity_id=candidate.id,
        action="enrichment_exception_approved",
        actor=reviewer,
        detail={"gers_id": candidate.gers_id, "website_url": website_url,
                "review_notes": payload.review_notes.strip(), "approval_scope": "enrichment_only"},
    ))
    db.commit()
    process_overture_candidates.delay(None, 1, candidate.id)
    return {"status": "queued_for_reassessment", "candidate_id": candidate.id,
            "gers_id": candidate.gers_id, "approval_scope": "enrichment_only"}
