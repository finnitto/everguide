from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app.config import settings
from app.models import (CompaniesHouseCandidate, CompanyWebsiteCandidate, CompanyWebsiteDiscoveryRun)
from app.tasks import discover_company_websites

router = APIRouter(prefix="/api/v1/company-websites", tags=["company website discovery"])

def _run_dict(run):
    if not run: return None
    return {"id":run.id,"status":run.status,"include_uncertain":run.include_uncertain,"batch_size":run.batch_size,
        "total_candidates":run.total_candidates,"processed_candidates":run.processed_candidates,"results_found":run.results_found,
        "websites_checked":run.websites_checked,"identity_signals":run.identity_signals,"no_results":run.no_results,
        "error_message":run.error_message,"created_at":run.created_at.isoformat() if run.created_at else None,
        "started_at":run.started_at.isoformat() if run.started_at else None,"completed_at":run.completed_at.isoformat() if run.completed_at else None}

@router.get("/status")
def status(db: Session = Depends(get_db)):
    eligible = db.query(func.count(CompaniesHouseCandidate.id)).filter(CompaniesHouseCandidate.company_status == "active",
        CompaniesHouseCandidate.profile_status == "completed", CompaniesHouseCandidate.classification.in_(["likely_funeral_director", "uncertain"])).scalar() or 0
    unsearched = db.query(func.count(CompaniesHouseCandidate.id)).filter(CompaniesHouseCandidate.company_status == "active",
        CompaniesHouseCandidate.profile_status == "completed", CompaniesHouseCandidate.classification.in_(["likely_funeral_director", "uncertain"]),
        CompaniesHouseCandidate.website_discovery_status.in_(["not_requested", "search_failed"])).scalar() or 0
    found = db.query(func.count(CompanyWebsiteCandidate.id)).scalar() or 0
    verified = db.query(func.count(CompanyWebsiteCandidate.id)).filter(CompanyWebsiteCandidate.verification_status == "identity_signals_found").scalar() or 0
    latest = db.query(CompanyWebsiteDiscoveryRun).order_by(CompanyWebsiteDiscoveryRun.id.desc()).first()
    return {"configured": settings.search_provider == "brave" and bool(settings.brave_search_api_key),
        "provider": settings.search_provider, "eligible_companies": eligible,"unsearched_companies":unsearched,
        "website_candidates":found,"identity_signal_candidates":verified,"latest_run":_run_dict(latest),
        "note":"Search results are leads only. Website checks obey robots.txt, use HTTPS/public-host safeguards, discard page bodies and never create or publish providers or branches."}

@router.get("/runs")
def runs(limit: int = 10, db: Session = Depends(get_db)):
    rows = db.query(CompanyWebsiteDiscoveryRun).order_by(CompanyWebsiteDiscoveryRun.id.desc()).limit(min(max(limit,1),50)).all()
    return {"items":[_run_dict(x) for x in rows]}

@router.post("/runs", status_code=202)
def start_run(db: Session = Depends(get_db)):
    if settings.search_provider != "brave" or not settings.brave_search_api_key:
        raise HTTPException(400, "Website discovery requires SEARCH_PROVIDER=brave and BRAVE_SEARCH_API_KEY in .env. The key is used server-side only.")
    active = db.query(CompanyWebsiteDiscoveryRun).filter(CompanyWebsiteDiscoveryRun.status.in_(["queued","running"])).order_by(CompanyWebsiteDiscoveryRun.id.desc()).first()
    if active:
        return {"message":"A company website discovery run is already active.","run":_run_dict(active)}
    eligible = db.query(func.count(CompaniesHouseCandidate.id)).filter(CompaniesHouseCandidate.company_status=="active",
        CompaniesHouseCandidate.profile_status=="completed", CompaniesHouseCandidate.classification.in_(["likely_funeral_director","uncertain"])).scalar() or 0
    remaining = db.query(func.count(CompaniesHouseCandidate.id)).filter(CompaniesHouseCandidate.company_status=="active",
        CompaniesHouseCandidate.profile_status=="completed", CompaniesHouseCandidate.classification.in_(["likely_funeral_director","uncertain"]),
        CompaniesHouseCandidate.website_discovery_status.in_(["not_requested","search_failed"])).scalar() or 0
    if not remaining:
        raise HTTPException(409, "There are no eligible unsearched Companies House candidates. Refresh status or review existing discovery results.")
    run=CompanyWebsiteDiscoveryRun(status="queued",include_uncertain=True,batch_size=25,total_candidates=remaining,created_at=datetime.now(timezone.utc))
    db.add(run); db.commit(); db.refresh(run)
    try:
        task=discover_company_websites.delay(run.id)
        run.celery_task_id=task.id; db.commit()
    except Exception as exc:
        db.rollback(); failed=db.get(CompanyWebsiteDiscoveryRun,run.id)
        if failed: failed.status="failed"; failed.error_message=str(exc)[:1000]; failed.completed_at=datetime.now(timezone.utc); db.commit()
        raise HTTPException(503,"Could not queue company website discovery. Check worker and Redis services.")
    return {"message":f"England-wide website discovery queued for up to {remaining:,} eligible companies in batches of 25. No providers or branches will be created or published.","run":_run_dict(run),"task_id":task.id}

@router.post("/runs/{run_id}/resume", status_code=202)
def resume_run(run_id: int, db: Session = Depends(get_db)):
    run=db.get(CompanyWebsiteDiscoveryRun,run_id)
    if not run: raise HTTPException(404,"Discovery run not found.")
    if run.status in ["queued","running"]: return {"message":"This discovery run is already active.","run":_run_dict(run)}
    if run.status not in ["paused","failed"]: raise HTTPException(409,"Only paused or failed discovery runs can be resumed.")
    if not settings.brave_search_api_key: raise HTTPException(400,"Configure BRAVE_SEARCH_API_KEY before resuming.")
    run.status="queued"; run.error_message=None; run.completed_at=None; db.commit()
    task=discover_company_websites.delay(run.id); run.celery_task_id=task.id; db.commit()
    return {"message":"Discovery resumed from unsearched companies. Previously saved candidates are retained.","run":_run_dict(run),"task_id":task.id}

@router.get("/candidates")
def candidates(limit: int=50, offset: int=0, db: Session=Depends(get_db)):
    q=db.query(CompanyWebsiteCandidate).order_by(CompanyWebsiteCandidate.match_score.desc(),CompanyWebsiteCandidate.id.desc())
    total=q.count(); rows=q.offset(max(0,offset)).limit(min(max(limit,1),200)).all()
    return {"total":total,"items":[{"id":x.id,"companies_house_candidate_id":x.companies_house_candidate_id,"company_name":x.companies_house_candidate.company_name if x.companies_house_candidate else None,
        "company_number":x.companies_house_candidate.company_number if x.companies_house_candidate else None,"classification":x.companies_house_candidate.classification if x.companies_house_candidate else None,
        "result_title":x.result_title,"result_url":x.result_url,"result_domain":x.result_domain,"result_snippet":x.result_snippet,"match_score":x.match_score,
        "verification_status":x.verification_status,"http_status":x.http_status,"robots_allowed":x.robots_allowed,"page_title":x.page_title,
        "extracted_data":x.extracted_data,"detail":x.detail,"created_at":x.created_at.isoformat() if x.created_at else None,"checked_at":x.checked_at.isoformat() if x.checked_at else None} for x in rows]}
