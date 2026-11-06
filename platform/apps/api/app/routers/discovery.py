from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import DiscoveryRun, SourceObservation
from app.tasks import run_provider_discovery

router = APIRouter(prefix="/api/v1/discovery", tags=["automated discovery"])

def run_dict(run):
    return {
        "id": run.id, "task_id": run.task_id, "status": run.status,
        "scope": run.scope, "source": run.source,
        "locations_attempted": run.locations_attempted,
        "places_found": run.places_found,
        "observations_created": run.observations_created,
        "duplicates_flagged": run.duplicates_flagged,
        "error_message": run.error_message,
        "started_at": run.started_at, "completed_at": run.completed_at,
        "created_at": run.created_at,
    }

@router.get("/status")
def discovery_status():
    return {
        "provider": "Google Places API (New)",
        "configured": bool(settings.google_places_api_key),
        "scope": "England",
        "coverage_plan": "40 regional discovery anchors with 30 km location bias",
        "coverage_note": "This is an initial regional discovery pass, not a boundary-validated exhaustive census. Coverage refinement is required before claiming complete England-wide coverage.",
    }

@router.post("/runs", status_code=202)
def start_discovery(db: Session = Depends(get_db)):
    if not settings.google_places_api_key:
        raise HTTPException(
            status_code=400,
            detail="Google Places API key is not configured. Add GOOGLE_PLACES_API_KEY to your local .env file and restart Everguide."
        )
    active = db.query(DiscoveryRun).filter(DiscoveryRun.status.in_(["queued", "running"])).first()
    if active:
        return {"message": "A discovery run is already queued or running.", **run_dict(active)}
    run = DiscoveryRun(status="queued", scope="england", source="google_places",
                       created_at=datetime.now(timezone.utc))
    db.add(run)
    db.commit()
    db.refresh(run)
    task = run_provider_discovery.delay(run.id)
    run.task_id = task.id
    db.commit()
    return run_dict(run)

@router.get("/runs")
def list_runs(limit: int = 20, db: Session = Depends(get_db)):
    rows = db.query(DiscoveryRun).order_by(DiscoveryRun.created_at.desc()).limit(min(max(limit, 1), 100)).all()
    return {"items": [run_dict(row) for row in rows]}

@router.get("/observations")
def discovery_observations(review_status: str | None = "pending", limit: int = 100, db: Session = Depends(get_db)):
    query = db.query(SourceObservation).filter(SourceObservation.source_type == "google_places")
    if review_status:
        query = query.filter(SourceObservation.review_status == review_status)
    rows = query.order_by(SourceObservation.retrieved_at.desc()).limit(min(max(limit, 1), 250)).all()
    return {"items": [{
        "id": row.id, "source_name": row.source_name, "source_url": row.source_url,
        "retrieved_at": row.retrieved_at, "confidence": row.confidence,
        "review_status": row.review_status, "observed_data": row.observed_data,
        "provider_id": row.provider_id, "notes": row.notes
    } for row in rows]}
