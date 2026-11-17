"""Review-only consolidation of website identity leads and branch evidence."""
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (CompaniesHouseCandidate, CompanyWebsiteCandidate,
    CompanyIdentityReview, CompanyBranchProposal, AuditEvent, IdentityAssessmentRun, OvertureCandidate, OvertureCompanyLink)
from app.identity_tasks import run_identity_assessment, verified_overture_company_query
from app.identity_review_auth import require_identity_reviewer

router = APIRouter(prefix="/api/v1/identity-review", tags=["identity and branch review"], dependencies=[Depends(require_identity_reviewer)])

# Backwards-compatible helpers retained for older tests and integrations.
def _domain(url):
    host = (urlsplit(url or "").hostname or "").lower().removeprefix("www.")
    return host or None


def _confidence(lead):
    from app.candidate_quality import DIRECTORY_DOMAINS
    domain = _domain(getattr(lead, "result_url", None) or getattr(lead, "final_url", None))
    if domain and any(domain == item or domain.endswith("." + item) for item in DIRECTORY_DOMAINS):
        return min(float(getattr(lead, "match_score", 0) or 0), 0.49)
    if getattr(lead, "verification_status", None) == "identity_signals_found":
        return max(float(getattr(lead, "match_score", 0) or 0), 0.75)
    return float(getattr(lead, "match_score", 0) or 0)


def _branch_eligible(lead, data):
    from app.candidate_quality import DIRECTORY_DOMAINS, is_valid_uk_postcode
    domain = _domain(getattr(lead, "result_url", None) or getattr(lead, "final_url", None))
    if not domain or any(domain == item or domain.endswith("." + item) for item in DIRECTORY_DOMAINS):
        return False
    country = str(data.get("country") or "").strip().lower()
    source_type = str(data.get("source_type") or "").strip().lower()
    return bool(data.get("has_complete_branch_address") and data.get("street") and data.get("town")
        and is_valid_uk_postcode(data.get("postcode")) and country in {"gb", "uk", "england", "united kingdom"}
        and source_type in {"schema_org_localbusiness", "schema_org_funeralhome"})


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
        "overture_company_link_id":row.overture_company_link_id,
        "evidence":row.evidence or {},"review_notes":row.review_notes}

@router.get("/overture-links")
def overture_links(limit: int = 50, status: str = "all", db: Session = Depends(get_db)):
    """List explicit Overture-to-Companies House provenance links."""
    q = db.query(OvertureCompanyLink, OvertureCandidate, CompaniesHouseCandidate).join(
        OvertureCandidate, OvertureCandidate.id == OvertureCompanyLink.overture_candidate_id
    ).join(
        CompaniesHouseCandidate, CompaniesHouseCandidate.id == OvertureCompanyLink.companies_house_candidate_id
    )
    if status != "all":
        q = q.filter(OvertureCompanyLink.status == status)
    rows = q.order_by(OvertureCompanyLink.id.desc()).limit(min(max(limit, 1), 200)).all()
    return {"items": [{
        "id": link.id,
        "overture_candidate_id": overture.id,
        "gers_id": overture.gers_id,
        "overture_name": overture.candidate_name,
        "companies_house_candidate_id": company.id,
        "company_number": company.company_number,
        "company_name": company.company_name,
        "status": link.status,
        "link_method": link.link_method,
        "evidence": link.evidence_json or {},
        "review_notes": link.review_notes,
        "reviewed_by": link.reviewed_by,
        "reviewed_at": link.reviewed_at.isoformat() if link.reviewed_at else None,
    } for link, overture, company in rows]}


@router.post("/overture-links")
def create_overture_link(payload: dict, db: Session = Depends(get_db), reviewer: str = Depends(require_identity_reviewer)):
    """Create a pending link only; creation never verifies provenance."""
    overture_id = payload.get("overture_candidate_id")
    company_id = payload.get("companies_house_candidate_id")
    if not isinstance(overture_id, int) or not isinstance(company_id, int):
        raise HTTPException(400, "Both candidate IDs must be integers")
    if not db.get(OvertureCandidate, overture_id):
        raise HTTPException(404, "Overture candidate not found")
    if not db.get(CompaniesHouseCandidate, company_id):
        raise HTTPException(404, "Companies House candidate not found")
    existing = db.query(OvertureCompanyLink).filter(
        OvertureCompanyLink.overture_candidate_id == overture_id,
        OvertureCompanyLink.companies_house_candidate_id == company_id,
    ).first()
    if existing:
        raise HTTPException(409, "This Overture-to-Companies House candidate pair already has a provenance link")
    link = OvertureCompanyLink(
        overture_candidate_id=overture_id,
        companies_house_candidate_id=company_id,
        status="pending",
        link_method="manual_review",
        evidence_json={},
        review_notes=str(payload.get("review_notes") or "")[:4000] or None,
    )
    db.add(link)
    db.flush()
    db.add(AuditEvent(
        entity_type="overture_company_link",
        entity_id=link.id,
        action="created_pending",
        detail={"overture_candidate_id": overture_id, "companies_house_candidate_id": company_id},
        actor=reviewer,
    ))
    db.commit()
    return {"id": link.id, "status": link.status, "message": "Pending link created. It cannot enter identity assessment until explicitly verified."}


@router.patch("/overture-links/{link_id}")
def review_overture_link(link_id: int, payload: dict, db: Session = Depends(get_db), reviewer: str = Depends(require_identity_reviewer)):
    """Verify or reject a provenance link with reviewer attribution and evidence."""
    link = db.get(OvertureCompanyLink, link_id)
    if not link:
        raise HTTPException(404, "Overture provenance link not found")
    status = payload.get("status")
    if status not in {"verified", "rejected", "needs_more_evidence", "pending"}:
        raise HTTPException(400, "Unsupported provenance link status")
    # Reviewer identity comes only from the authenticated bearer credential.
    evidence = payload.get("evidence")
    if status == "verified":
        if not isinstance(evidence, dict) or not evidence:
            raise HTTPException(400, "Non-empty structured evidence is required to verify provenance")
        source_type = str(evidence.get("source_type") or "").strip().lower()
        source_reference = str(evidence.get("source_reference") or "").strip()
        finding = str(evidence.get("finding") or "").strip()
        matched_fields = evidence.get("matched_fields")
        allowed_source_types = {"official_website", "companies_house_profile", "official_document", "first_party_record"}
        allowed_match_fields = {"trading_name", "branch_address", "postcode", "company_number", "official_domain"}
        if source_type not in allowed_source_types or not source_reference or not finding:
            raise HTTPException(
                400,
                "Evidence must include an allowed source_type, source_reference and finding",
            )
        if not isinstance(matched_fields, list) or not matched_fields:
            raise HTTPException(400, "Evidence matched_fields must be a non-empty list")
        if any(not isinstance(value, str) or not value.strip() for value in matched_fields):
            raise HTTPException(400, "Evidence matched_fields must contain only non-empty strings")
        matched_fields = {value.strip().lower() for value in matched_fields}
        if len(matched_fields & allowed_match_fields) < 2:
            raise HTTPException(400, "At least two recognised identity fields must be evidenced")
        if not (matched_fields & {"trading_name", "branch_address", "postcode"}):
            raise HTTPException(400, "Evidence must connect the Overture location to the trading identity")
        if not (matched_fields & {"company_number", "official_domain"}):
            raise HTTPException(400, "Evidence must connect the trading identity to the legal company")
        if not db.get(CompaniesHouseCandidate, link.companies_house_candidate_id):
            raise HTTPException(409, "Companies House candidate no longer exists")
        if not db.get(OvertureCandidate, link.overture_candidate_id):
            raise HTTPException(409, "Overture candidate no longer exists")
        link.evidence_json = evidence
    else:
        if isinstance(evidence, dict):
            link.evidence_json = evidence
    link.reviewed_by = reviewer
    link.reviewed_at = datetime.now(timezone.utc)
    link.status = status
    link.review_notes = str(payload.get("review_notes") or "")[:4000] or link.review_notes
    link.updated_at = datetime.now(timezone.utc)
    db.add(AuditEvent(
        entity_type="overture_company_link",
        entity_id=link.id,
        action="status_changed",
        detail={"status": status, "reviewed_by": link.reviewed_by, "evidence": link.evidence_json or {}},
        actor=reviewer,
    ))
    db.commit()
    return {"id": link.id, "status": link.status, "reviewed_by": link.reviewed_by,
            "reviewed_at": link.reviewed_at.isoformat() if link.reviewed_at else None}


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
        "note": "This queue is reserved for candidates not automatically approved, including ambiguous identity and branch evidence. High-confidence candidates are published by the automatic approval workflow; this exception queue does not re-review them."
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
    eligible_ids = verified_overture_company_query(db).subquery()
    total = (db.query(func.count(func.distinct(CompanyWebsiteCandidate.companies_house_candidate_id)))
        .join(eligible_ids, eligible_ids.c.id == CompanyWebsiteCandidate.companies_house_candidate_id)
        .filter(CompanyWebsiteCandidate.verification_status != "auto_approved_published").scalar() or 0)
    run = IdentityAssessmentRun(status="queued", total_companies=total)
    db.add(run); db.commit(); db.refresh(run)
    task = run_identity_assessment.delay(run.id)
    run.celery_task_id = task.id; db.commit()
    return {"status":"queued","run_id":run.id,"total_companies":total,
        "message":"Exception-only identity and England-only branch assessment queued. Automatically approved providers are excluded; unresolved proposals remain for administrator review."}

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
def update_identity(review_id: int, payload: dict, db: Session = Depends(get_db), reviewer: str = Depends(require_identity_reviewer)):
    row = db.get(CompanyIdentityReview, review_id)
    if not row: raise HTTPException(404, "Identity review not found")
    status = payload.get("status")
    if status not in {"pending", "accepted_for_provider_setup", "rejected", "needs_more_evidence"}:
        raise HTTPException(400, "Unsupported review status")
    row.status = status
    row.review_notes = str(payload.get("review_notes") or "")[:4000] or None
    row.updated_at = datetime.now(timezone.utc)
    db.add(AuditEvent(entity_type="company_identity_review", entity_id=row.id, action="status_changed",
        detail={"status":status,"review_notes":row.review_notes,"publication_changes":0}, actor=reviewer))
    db.commit()
    return {"id":row.id,"status":row.status,"message":"Review decision recorded. No provider was created or published."}

@router.patch("/branches/{proposal_id}")
def update_branch(proposal_id: int, payload: dict, db: Session = Depends(get_db), reviewer: str = Depends(require_identity_reviewer)):
    row = db.get(CompanyBranchProposal, proposal_id)
    if not row: raise HTTPException(404, "Branch proposal not found")
    status = payload.get("status")
    if status not in {"pending", "accepted_for_provider_setup", "rejected", "needs_more_evidence"}:
        raise HTTPException(400, "Unsupported review status")
    row.status = status
    row.review_notes = str(payload.get("review_notes") or "")[:4000] or None
    row.updated_at = datetime.now(timezone.utc)
    db.add(AuditEvent(entity_type="company_branch_proposal", entity_id=row.id, action="status_changed",
        detail={"status":status,"review_notes":row.review_notes,"publication_changes":0}, actor=reviewer))
    db.commit()
    return {"id":row.id,"status":row.status,"message":"Branch proposal decision recorded. No branch was created or published."}
