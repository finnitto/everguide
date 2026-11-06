from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.config import settings
from app.models import WebsiteDiscoveryResult
from app.tasks import discover_provider_websites

router = APIRouter(prefix="/api/v1/website-discovery", tags=["automatic website discovery"])

@router.get("/status")
def status(db: Session = Depends(get_db)):
    return {
        "configured": bool(settings.brave_search_api_key) if settings.search_provider == "brave" else False,
        "provider": settings.search_provider,
        "candidates": db.query(WebsiteDiscoveryResult).count(),
        "message": "Search provider configured." if settings.brave_search_api_key else "Configure credentials for the selected search provider."
    }

@router.post("/runs", status_code=202)
def start_run():
    if settings.search_provider == "brave" and not settings.brave_search_api_key:
        raise HTTPException(400, "The selected search provider is not configured. Check its credentials in .env and restart API and worker.")
    task = discover_provider_websites.delay()
    return {"status":"queued","task_id":task.id,"message":"Automatic England regional website search queued."}

@router.get("/candidates")
def candidates(limit:int=100, db:Session=Depends(get_db)):
    rows = db.query(WebsiteDiscoveryResult).order_by(WebsiteDiscoveryResult.created_at.desc()).limit(min(max(limit,1),500)).all()
    return {"items":[{"id":x.id,"region":x.query_region,"title":x.result_title,"url":x.result_url,"domain":x.result_domain,"snippet":x.result_snippet,"status":x.status,"created_at":x.created_at} for x in rows]}
