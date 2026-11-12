"""Review-only consolidation of website identity leads and branch evidence."""
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (CompaniesHouseCandidate, CompanyWebsiteCandidate,
    CompanyIdentityReview, CompanyBranchProposal, AuditEvent, IdentityAssessmentRun)
from app.identity_tasks import run_identity_assessment

router = APIRouter(prefix="/api/v1/identity-review", tags=["identity and branch review"])

def _identity_dict(row, company):
    return {"id":row.id,"company_id":company.id,"company_number":company.company_number,
        "legal_name":company.company_name,"classification":company.classification,"status":row.status,
        "suggested_trading_name":row.suggested_trading_name,"website":row.suggested_website,
        "domain":row.suggested_domain,"confidence":row.confidence,"duplicate_leads_collapsed":row.duplicate_leads_collapsed,
        "evidence":row.evidence or {},"review_notes":row.review_notes}

def _branch_dict(row, company):
    return {"id":row.id,"company_id":company.id,"company_number":company.company_number,
        "legal_name":company.company_name,"status":row.status,"branch_name":row.proposed_branch_name,
        "address_line":row.address_line,"town_city":row.town_city,"postcode":row.postcode,
        "telephone":row.telephone,"website":row.website,"confidence":row.confidence,
        "evidence":row.evidence or {},"review_notes":row.review_notes}

@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    return {
        "identity_reviews": db.query(func.count(CompanyIdentityReview.id)).scalar() or 0,
        "identity_pending": db.query(func.count(CompanyIdentityReview.id)).filter(CompanyIdentityReview.status == "pending").scalar() or 0,
        "branch_proposals": db.query(func.count(CompanyBranchProposal.id)).scalar() or 0,
        "branch_pending": db.query(func.count(CompanyBranchProposal.id)).filter(CompanyBranchProposal.status == "pending").scalar() or 0,
        "published_providers_created": 0,
        "published_branches_created": 0,
        "latest_assessment_run": (lambda r: ({"id":r.id,"status":r.status,"processed_companies":r.processed_companies,"total_companies":r.total_companies} if r else None))(db.query(IdentityAssessmentRun).order_by(IdentityAssessmentRun.id.desc()).first()),
        "note": "All outputs are review-only proposals. No provider or branch records are created or published."
    }

@router.get("/runs")
def assessment_runs(limit: int = 10, db: Session = Depends(get_db)):
    rows = db.query(IdentityAssessmentRun).order_by(IdentityAssessmentRun.id.desc()).limit(min(max(limit,1),50)).all()
    return {"items":[{"id":r.id,"status":r.status,"total_companies":r.total_companies,
        "processed_companies":r.processed_companies,"identity_reviews_created":r.identity_reviews_created,
        "branch_proposals_created":r.branch_proposals_created,"branch_evidence_skipped":r.branch_evidence_skipped,
        "last_company_candidate_id":r.last_company_candidate_id,"error_message":r.error_message,
        "created_at":r.created_at.isoformat() if r.created_at else None,
        "started_at":r.started_at.isoformat() if r.started_at else None,
        "completed_at":r.completed_at.isoformat() if r.completed_at else None} for r in rows]}

@router.post("/prepare")
def prepare_review_queues(db: Session = Depends(get_db)):
    """Queue resumable background assessment; never processes data in the API request."""
    active = db.query(IdentityAssessmentRun).filter(IdentityAssessmentRun.status.in_(["queued","running"])).order_by(IdentityAssessmentRun.id.desc()).first()
    if active:
        return {"status":active.status,"run_id":active.id,"message":"An identity assessment is already queued or running."}
    total = (db.query(func.count(func.distinct(CompanyWebsiteCandidate.companies_house_candidate_id)))
        .join(CompaniesHouseCandidate, CompaniesHouseCandidate.id == CompanyWebsiteCandidate.companies_house_candidate_id)
        .filter(CompaniesHouseCandidate.company_status == "active").scalar() or 0)
    run = IdentityAssessmentRun(status="queued", total_companies=total)
    db.add(run); db.commit(); db.refresh(run)
    task = run_identity_assessment.delay(run.id)
    run.celery_task_id = task.id; db.commit()
    return {"status":"queued","run_id":run.id,"total_companies":total,
        "message":"Identity and England-only branch assessment queued. Processing is resumable; no providers or branches will be published."}

@router.post("/runs/{run_id}/resume")
def resume_assessment(run_id: int, db: Session = Depends(get_db)):
    run = db.get(IdentityAssessmentRun,run_id)
    if not run: raise HTTPException(404,"Assessment run not found")
    if run.status == "completed": raise HTTPException(409,"Assessment run is already completed")
    active = db.query(IdentityAssessmentRun).filter(IdentityAssessmentRun.status.in_(["queued","running"]),IdentityAssessmentRun.id != run_id).first()
    if active: raise HTTPException(409,"Another identity assessment is already active")
    run.status="queued"; run.error_message=None; db.commit()
    task=run_identity_assessment.delay(run.id); run.celery_task_id=task.id; db.commit()
    return {"status":"queued","run_id":run.id,"last_company_candidate_id":run.last_company_candidate_id,
        "message":"Assessment resumed from the last committed company. Existing decisions and evidence are preserved."}

@router.get("/identities")
def identities(limit: int = 50, status: str = "pending", db: Session = Depends(get_db)):
    q = db.query(CompanyIdentityReview, CompaniesHouseCandidate).join(CompaniesHouseCandidate,
        CompaniesHouseCandidate.id == CompanyIdentityReview.companies_house_candidate_id)
    if status != "all": q = q.filter(CompanyIdentityReview.status == status)
    rows = q.order_by(CompanyIdentityReview.confidence.desc(), CompanyIdentityReview.id.asc()).limit(min(max(limit,1),200)).all()
    return {"items":[_identity_dict(r,c) for r,c in rows]}

@router.get("/branches")
def branches(limit: int = 50, status: str = "pending", db: Session = Depends(get_db)):
    q = db.query(CompanyBranchProposal, CompaniesHouseCandidate).join(CompaniesHouseCandidate,
        CompaniesHouseCandidate.id == CompanyBranchProposal.companies_house_candidate_id)
    if status != "all": q = q.filter(CompanyBranchProposal.status == status)
    rows = q.order_by(CompanyBranchProposal.confidence.desc(), CompanyBranchProposal.id.asc()).limit(min(max(limit,1),200)).all()
    return {"items":[_branch_dict(r,c) for r,c in rows]}

@router.patch("/identities/{review_id}")
def update_identity(review_id: int, payload: dict, db: Session = Depends(get_db)):
    row = db.get(CompanyIdentityReview, review_id)
    if not row: raise HTTPException(404, "Identity review not found")
    status = payload.get("status")
    if status not in {"pending", "accepted_for_provider_setup", "rejected", "needs_more_evidence"}:
        raise HTTPException(400, "Unsupported review status")
    row.status = status
    row.review_notes = str(payload.get("review_notes") or "")[:4000] or None
    row.updated_at = datetime.now(timezone.utc)
    db.add(AuditEvent(entity_type="company_identity_review", entity_id=row.id, action="status_changed",
        detail={"status":status,"review_notes":row.review_notes,"publication_changes":0}))
    db.commit()
    return {"id":row.id,"status":row.status,"message":"Review decision recorded. No provider was created or published."}

@router.patch("/branches/{proposal_id}")
def update_branch(proposal_id: int, payload: dict, db: Session = Depends(get_db)):
    row = db.get(CompanyBranchProposal, proposal_id)
    if not row: raise HTTPException(404, "Branch proposal not found")
    status = payload.get("status")
    if status not in {"pending", "accepted_for_provider_setup", "rejected", "needs_more_evidence"}:
        raise HTTPException(400, "Unsupported review status")
    row.status = status
    row.review_notes = str(payload.get("review_notes") or "")[:4000] or None
    row.updated_at = datetime.now(timezone.utc)
    db.add(AuditEvent(entity_type="company_branch_proposal", entity_id=row.id, action="status_changed",
        detail={"status":status,"review_notes":row.review_notes,"publication_changes":0}))
    db.commit()
    return {"id":row.id,"status":row.status,"message":"Branch proposal decision recorded. No branch was created or published."}
