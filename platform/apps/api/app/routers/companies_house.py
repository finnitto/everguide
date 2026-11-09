from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.config import settings
from app.models import CompaniesHouseRun, CompaniesHouseCandidate
from app.companies_house import import_companies_house_sic, enrich_company_profiles
from app.company_classification import run_classification, classification_summary

router = APIRouter(prefix="/api/v1/companies-house", tags=["companies-house"])

@router.get("/status")
def status(db: Session = Depends(get_db)):
    return {
        "configured": bool(settings.companies_house_api_key),
        "sic_codes": [x.strip() for x in settings.companies_house_sic_codes.split(",") if x.strip()],
        "candidates": db.query(func.count(CompaniesHouseCandidate.id)).scalar() or 0,
        "active_candidates": db.query(func.count(CompaniesHouseCandidate.id)).filter(CompaniesHouseCandidate.company_status == "active").scalar() or 0,
        "classification": classification_summary(db),
        "profile_enrichment": {
            "completed": db.query(func.count(CompaniesHouseCandidate.id)).filter(CompaniesHouseCandidate.profile_status == "completed").scalar() or 0,
            "failed": db.query(func.count(CompaniesHouseCandidate.id)).filter(CompaniesHouseCandidate.profile_status == "failed").scalar() or 0,
            "remaining": db.query(func.count(CompaniesHouseCandidate.id)).filter(CompaniesHouseCandidate.company_status == "active", CompaniesHouseCandidate.profile_status.in_(["not_requested", "failed"])).scalar() or 0,
        },
        "latest_run": _run_dict(db.query(CompaniesHouseRun).order_by(CompaniesHouseRun.id.desc()).first()),
        "note": "Companies House records identify legal entities, not verified funeral homes. Registered office addresses are never imported as branches."
    }

def _run_dict(run):
    if not run: return None
    return {"id":run.id,"status":run.status,"sic_codes":run.sic_codes,"total_results":run.total_results,"imported":run.imported,"pages_fetched":run.pages_fetched,"api_items_per_page":run.api_items_per_page,"unique_companies_seen":run.unique_companies_seen,"error_message":run.error_message,"created_at":run.created_at.isoformat() if run.created_at else None,"completed_at":run.completed_at.isoformat() if run.completed_at else None}

@router.get("/runs")
def runs(db: Session = Depends(get_db)):
    return {"items": [_run_dict(x) for x in db.query(CompaniesHouseRun).order_by(CompaniesHouseRun.id.desc()).limit(20).all()]}

@router.post("/runs")
def start_import(db: Session = Depends(get_db)):
    if not settings.companies_house_api_key:
        raise HTTPException(status_code=400, detail="Companies House API key is not configured. Add COMPANIES_HOUSE_API_KEY to .env and restart Docker services.")
    active = db.query(CompaniesHouseRun).filter(CompaniesHouseRun.status.in_(["queued", "running"])).first()
    if active: return {"message":"A Companies House import is already queued or running.","run":_run_dict(active)}
    sic_codes = [x.strip() for x in settings.companies_house_sic_codes.split(",") if x.strip()]
    run = CompaniesHouseRun(status="queued", sic_codes=sic_codes, created_at=datetime.now(timezone.utc))
    db.add(run); db.commit(); db.refresh(run)
    task = import_companies_house_sic.delay(run.id)
    return {"message":"Companies House SIC-code import queued. Existing provider directory remains empty; candidates are not published.","run":_run_dict(run),"task_id":task.id}

@router.get("/candidates")
def candidates(limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 500))
    q = db.query(CompaniesHouseCandidate).order_by(CompaniesHouseCandidate.company_name.asc())
    total = q.count()
    items = q.offset(max(0, offset)).limit(limit).all()
    return {"total":total,"items":[{"company_number":x.company_number,"company_name":x.company_name,"company_status":x.company_status,"company_type":x.company_type,"sic_codes":x.sic_codes,"registered_office_address":x.registered_office_address,"date_of_creation":x.date_of_creation,"company_profile_url":x.company_profile_url,"classification":x.classification,"classification_reason":x.classification_reason,"classification_confidence":x.classification_confidence,"classified_at":x.classified_at.isoformat() if x.classified_at else None,"review_status":x.review_status,"company_profile":x.company_profile,"profile_status":x.profile_status,"profile_checked_at":x.profile_checked_at.isoformat() if x.profile_checked_at else None,"previous_company_names":x.previous_company_names,"profile_error":x.profile_error,"last_seen_at":x.last_seen_at.isoformat() if x.last_seen_at else None} for x in items]}


@router.post("/profiles/enrich")
def start_profile_enrichment(db: Session = Depends(get_db)):
    if not settings.companies_house_api_key:
        raise HTTPException(status_code=400, detail="Companies House API key is not configured.")
    active = db.query(CompaniesHouseRun).filter(CompaniesHouseRun.status.in_(["queued", "running", "enriching"])).first()
    if active:
        return {"message": "A Companies House job is already queued or running.", "run": _run_dict(active)}
    remaining = db.query(func.count(CompaniesHouseCandidate.id)).filter(CompaniesHouseCandidate.company_status == "active", CompaniesHouseCandidate.profile_status.in_(["not_requested", "failed"])).scalar() or 0
    if not remaining:
        return {"message": "All active candidates already have a completed profile lookup.", "remaining": 0}
    run = CompaniesHouseRun(status="queued", sic_codes=["company-profile-enrichment"], total_results=remaining, created_at=datetime.now(timezone.utc))
    db.add(run); db.commit(); db.refresh(run)
    task = enrich_company_profiles.delay(run.id)
    return {"message": f"Queued profile enrichment for {remaining:,} active companies. No providers or branches will be created.", "run": _run_dict(run), "task_id": task.id}

@router.get("/profiles/summary")
def profile_summary(db: Session = Depends(get_db)):
    total = db.query(func.count(CompaniesHouseCandidate.id)).filter(CompaniesHouseCandidate.company_status == "active").scalar() or 0
    completed = db.query(func.count(CompaniesHouseCandidate.id)).filter(CompaniesHouseCandidate.company_status == "active", CompaniesHouseCandidate.profile_status == "completed").scalar() or 0
    failed = db.query(func.count(CompaniesHouseCandidate.id)).filter(CompaniesHouseCandidate.company_status == "active", CompaniesHouseCandidate.profile_status == "failed").scalar() or 0
    not_found = db.query(func.count(CompaniesHouseCandidate.id)).filter(CompaniesHouseCandidate.company_status == "active", CompaniesHouseCandidate.profile_status == "not_found").scalar() or 0
    return {"total_active": total, "completed": completed, "failed": failed, "not_found": not_found, "remaining": max(0, total-completed-not_found)}

@router.post("/classification/run")
def classify_candidates(db: Session = Depends(get_db)):
    result = run_classification(db)
    return {"message": "Candidate triage completed. No providers were created or published.", **result}

@router.get("/classification/summary")
def get_classification_summary(db: Session = Depends(get_db)):
    return classification_summary(db)
