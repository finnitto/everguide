from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, distinct
from sqlalchemy.orm import Session
from app.database import get_db
from app.config import settings
from app.models import OvertureCandidate, OvertureImportRun, Provider, AuditEvent
from app.overture_tasks import process_overture_candidates
from app.overture_feed import poll_latest_overture_release
from app.identity_review_auth import require_identity_reviewer

router = APIRouter(prefix="/api/v1/overture", tags=["Overture discovery and approval"])

class OvertureImportPayload(BaseModel):
    records: list[dict] = Field(min_length=1, max_length=5000)
    source_release: str | None = Field(default=None, max_length=80)


def _run_dict(run):
    return {"id": run.id, "status": run.status, "source_release": run.source_release,
        "records_received": run.records_received, "records_imported": run.records_imported,
        "records_updated": run.records_updated, "records_processed": run.records_processed,
        "outcomes": run.outcomes or {}, "ingestion_method": ((run.outcomes or {}).get("_meta", {}) or {}).get("ingestion_method", "manual_csv"), "error_message": run.error_message,
        "created_at": run.created_at, "started_at": run.started_at, "completed_at": run.completed_at}


@router.get("/status", dependencies=[Depends(require_identity_reviewer)])
def overture_status(db: Session = Depends(get_db)):
    counts = dict(db.query(OvertureCandidate.outcome, func.count(OvertureCandidate.id)).group_by(OvertureCandidate.outcome).all())
    latest = db.query(OvertureImportRun).order_by(OvertureImportRun.id.desc()).first()
    last_check = db.query(AuditEvent).filter(AuditEvent.entity_type == "overture_feed").order_by(AuditEvent.id.desc()).first()
    return {"pipeline_enabled": True, "automatic_processing": settings.overture_auto_process,
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
        "latest_import": _run_dict(latest) if latest else None}


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
def queue_overture_processing(limit: int = 20, reviewer: str = Depends(require_identity_reviewer), db: Session = Depends(get_db)):
    task = process_overture_candidates.delay(None, max(1, min(limit, 50)))
    return {"status": "queued", "task_id": task.id, "limit": max(1, min(limit, 50))}


@router.get("/imports", dependencies=[Depends(require_identity_reviewer)])
def list_overture_imports(limit: int = 20, db: Session = Depends(get_db)):
    rows = db.query(OvertureImportRun).order_by(OvertureImportRun.id.desc()).limit(min(max(limit, 1), 100)).all()
    return {"items": [_run_dict(row) for row in rows]}


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
        "first_party_evidence": row.first_party_evidence, "provider_id": row.provider_id,
        "branch_id": row.branch_id, "last_checked_at": row.last_checked_at} for row in rows]}
