from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app.identity_review_auth import require_identity_reviewer
from app.config import settings
from app.models import (CompaniesHouseCandidate, CompanyWebsiteCandidate, CompanyWebsiteDiscoveryRun, Provider, AuditEvent)
from app.tasks import discover_company_websites

router = APIRouter(prefix="/api/v1/company-websites", tags=["company website discovery"], dependencies=[Depends(require_identity_reviewer)])

def _run_dict(run):
    if not run: return None
    return {"id":run.id,"status":run.status,"include_uncertain":run.include_uncertain,"batch_size":run.batch_size,
        "total_candidates":run.total_candidates,"processed_candidates":run.processed_candidates,"results_found":run.results_found,
        "websites_checked":run.websites_checked,"identity_signals":run.identity_signals,"no_results":run.no_results,
        "error_message":run.error_message,"created_at":run.created_at.isoformat() if run.created_at else None,
        "started_at":run.started_at.isoformat() if run.started_at else None,"completed_at":run.completed_at.isoformat() if run.completed_at else None}

@router.get("/status", dependencies=[Depends(require_identity_reviewer)])
def status(db: Session = Depends(get_db)):
    eligible = db.query(func.count(CompaniesHouseCandidate.id)).filter(CompaniesHouseCandidate.company_status == "active",
        CompaniesHouseCandidate.profile_status == "completed", CompaniesHouseCandidate.classification.in_(["likely_funeral_director", "uncertain"])).scalar() or 0
    unsearched = db.query(func.count(CompaniesHouseCandidate.id)).filter(CompaniesHouseCandidate.company_status == "active",
        CompaniesHouseCandidate.profile_status == "completed", CompaniesHouseCandidate.classification.in_(["likely_funeral_director", "uncertain"]),
        CompaniesHouseCandidate.website_discovery_status.in_(["not_requested", "search_failed"])).scalar() or 0
    found = db.query(func.count(CompanyWebsiteCandidate.id)).scalar() or 0
    verified = db.query(func.count(CompanyWebsiteCandidate.id)).filter(CompanyWebsiteCandidate.verification_status.in_(["identity_signals_found", "auto_approved_published", "exception_review"])).scalar() or 0
    latest = db.query(CompanyWebsiteDiscoveryRun).order_by(CompanyWebsiteDiscoveryRun.id.desc()).first()
    auto_approved = db.query(func.count(AuditEvent.id)).filter(
        AuditEvent.entity_type == "provider", AuditEvent.action == "auto_approved_published").scalar() or 0
    exceptions = db.query(func.count(CompanyWebsiteCandidate.id)).filter(
        CompanyWebsiteCandidate.verification_status == "exception_review").scalar() or 0
    return {"configured": settings.search_provider == "brave" and bool(settings.brave_search_api_key),
        "provider": settings.search_provider, "eligible_companies": eligible,"unsearched_companies":unsearched,
        "website_candidates":found,"identity_signal_candidates":verified,"latest_run":_run_dict(latest),
        "auto_approval": {"enabled": settings.auto_approve_providers,
            "minimum_confidence": settings.auto_approval_min_confidence,
            "published_providers": auto_approved, "exception_candidates": exceptions,
            "published_provider_total": db.query(Provider).filter(Provider.status == "published").count()},
        "note":"Eligible high-confidence first-party provider website evidence is automatically approved and published. Incomplete, conflicting, low-confidence and duplicate candidates are routed to the administrator exception queue. Website page bodies are discarded."}

@router.get("/runs", dependencies=[Depends(require_identity_reviewer)])
def runs(limit: int = 10, db: Session = Depends(get_db)):
    rows = db.query(CompanyWebsiteDiscoveryRun).order_by(CompanyWebsiteDiscoveryRun.id.desc()).limit(min(max(limit,1),50)).all()
    return {"items":[_run_dict(x) for x in rows]}

@router.post("/runs", status_code=202)
def start_run():
    raise HTTPException(status_code=410, detail="Independent company website discovery is disabled pending the Overture-led workflow.")

@router.post("/runs/{run_id}/resume", status_code=202)
def resume_run(run_id: int):
    raise HTTPException(status_code=410, detail="Legacy company website discovery runs cannot be resumed.")

@router.get("/candidates", dependencies=[Depends(require_identity_reviewer)])
def candidates(limit: int=50, offset: int=0, db: Session=Depends(get_db)):
    q=db.query(CompanyWebsiteCandidate).order_by(CompanyWebsiteCandidate.match_score.desc(),CompanyWebsiteCandidate.id.desc())
    total=q.count(); rows=q.offset(max(0,offset)).limit(min(max(limit,1),200)).all()
    return {"total":total,"items":[{"id":x.id,"companies_house_candidate_id":x.companies_house_candidate_id,"company_name":x.companies_house_candidate.company_name if x.companies_house_candidate else None,
        "company_number":x.companies_house_candidate.company_number if x.companies_house_candidate else None,"classification":x.companies_house_candidate.classification if x.companies_house_candidate else None,
        "result_title":x.result_title,"result_url":x.result_url,"result_domain":x.result_domain,"result_snippet":x.result_snippet,"match_score":x.match_score,
        "verification_status":x.verification_status,"http_status":x.http_status,"robots_allowed":x.robots_allowed,"page_title":x.page_title,
        "extracted_data":x.extracted_data,"detail":x.detail,"created_at":x.created_at.isoformat() if x.created_at else None,"checked_at":x.checked_at.isoformat() if x.checked_at else None} for x in rows]}
