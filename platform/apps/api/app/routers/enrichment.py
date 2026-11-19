from datetime import datetime, timezone
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Provider, SourcePermission, WebsiteEvidenceCheck, AuditEvent, OvertureCandidate
from app.pricing_enrichment import dispatch_queued_price_enrichment
from app.tasks import check_approved_sources
from app.identity_review_auth import require_identity_reviewer
router = APIRouter(prefix="/api/v1/enrichment", tags=["source permissions and enrichment"])
class SourceInput(BaseModel):
    provider_id: int
    source_url: str = Field(min_length=10, max_length=1000)
    permission_basis: str | None = Field(default=None, max_length=4000)
    permission_reference: str | None = Field(default=None, max_length=500)
@router.get("/sources", dependencies=[Depends(require_identity_reviewer)])
def list_sources(db: Session = Depends(get_db)):
    rows=db.query(SourcePermission).order_by(SourcePermission.created_at.desc()).limit(200).all()
    return {"items":[{"id":x.id,"provider_id":x.provider_id,"provider_name":db.get(Provider,x.provider_id).trading_name if db.get(Provider,x.provider_id) else "(deleted)","source_url":x.source_url,"source_domain":x.source_domain,"permission_status":x.permission_status,"permission_basis":x.permission_basis,"permission_reference":x.permission_reference,"approved_at":x.approved_at} for x in rows]}
@router.post("/sources",status_code=201)
def register_source(payload: SourceInput, reviewer: str = Depends(require_identity_reviewer), db: Session=Depends(get_db)):
    provider=db.get(Provider,payload.provider_id)
    if not provider: raise HTTPException(404,"Provider not found")
    parsed=urlparse(payload.source_url.strip())
    if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password: raise HTTPException(400,"Use a valid HTTPS URL without embedded credentials.")
    domain=parsed.hostname.lower().removeprefix("www.")
    row=SourcePermission(provider_id=provider.id,source_url=payload.source_url.strip(),source_domain=domain,permission_status="automated_check",permission_basis=(payload.permission_basis or "Provider-owned public website; factual business information only. Automated access and reuse remain subject to source terms, technical restrictions, applicable copyright/database rights and data-protection requirements.").strip(),permission_reference=payload.permission_reference)
    db.add(row); db.flush(); db.add(AuditEvent(entity_type="source_permission",entity_id=row.id,action="registered_pending",detail={"provider_id":provider.id,"domain":domain})); db.commit(); db.refresh(row)
    task = check_approved_sources.delay()
    return {"id":row.id,"permission_status":row.permission_status,"task_id":task.id,"message":"Registered for automatic technical screening. No individual permission record is required merely to identify a provider-owned website; any extraction, retention and publication remain subject to applicable rights, terms and data-protection rules."}
@router.post("/sources/{source_id}/approve")
def approve_source(source_id:int, reviewer: str = Depends(require_identity_reviewer), db:Session=Depends(get_db)):
    row=db.get(SourcePermission,source_id)
    if not row: raise HTTPException(404,"Source permission record not found")
    row.permission_status="approved"; row.approved_by=reviewer; row.approved_at=datetime.now(timezone.utc)
    db.add(AuditEvent(entity_type="source_permission",entity_id=row.id,action="approved_for_fetch",detail={"domain":row.source_domain,"permission_reference":row.permission_reference,"basis":row.permission_basis}))

    # Release only candidates that were held because this source did not yet
    # have reviewer approval. Candidate identity/publication state is unchanged.
    queued_ids = []
    candidates = (
        db.query(OvertureCandidate)
        .filter(OvertureCandidate.provider_id == row.provider_id)
        .order_by(OvertureCandidate.id.asc())
        .all()
    )
    for candidate in candidates:
        evidence = dict(candidate.first_party_evidence or {})
        candidate_url = str(evidence.get("website_url") or "")
        candidate_host = (urlparse(candidate_url).hostname or "").lower().removeprefix("www.")
        approved_domain = (row.source_domain or "").lower().removeprefix("www.")
        if not candidate_host or not (
            candidate_host == approved_domain or candidate_host.endswith("." + approved_domain)
        ):
            continue
        marker = evidence.get("pricing_enrichment")
        marker = dict(marker) if isinstance(marker, dict) else {}
        if marker.get("status") != "awaiting_permission":
            continue
        marker.update({
            "status": "queued",
            "permission_id": row.id,
            "permission_approved_at": row.approved_at.isoformat(),
            "permission_approved_by": reviewer,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        })
        evidence["pricing_enrichment"] = marker
        candidate.first_party_evidence = evidence
        queued_ids.append(candidate.id)
        db.add(AuditEvent(
            entity_type="overture_candidate",
            entity_id=candidate.id,
            action="pricing_enrichment_released_after_source_approval",
            detail={"provider_id": row.provider_id, "source_permission_id": row.id,
                    "source_domain": row.source_domain},
            actor=reviewer,
        ))
    db.commit()
    dispatched = dispatch_queued_price_enrichment(queued_ids)
    return {
        "id":row.id,
        "permission_status":row.permission_status,
        "pricing_candidates_requeued":len(queued_ids),
        "pricing_tasks_dispatched":dispatched,
        "message":"Source approved. Waiting price-enrichment candidates were released; retrieval runs when the price-enrichment feature is enabled.",
    }
@router.post("/run",status_code=202)
def run_enrichment(reviewer: str = Depends(require_identity_reviewer)):
    task=check_approved_sources.delay()
    return {"status":"queued","task_id":task.id,"message":"Eligible registered HTTPS sources will be checked automatically. robots.txt is treated only as a crawler instruction, not as a licence or reuse permission."}
@router.get("/checks", dependencies=[Depends(require_identity_reviewer)])
def list_checks(limit:int=100,db:Session=Depends(get_db)):
    rows=db.query(WebsiteEvidenceCheck).order_by(WebsiteEvidenceCheck.checked_at.desc()).limit(min(max(limit,1),250)).all()
    return {"items":[{"id":x.id,"source_permission_id":x.source_permission_id,"provider_id":x.provider_id,"checked_at":x.checked_at,"status":x.status,"http_status":x.http_status,"page_title":x.page_title,"content_sha256":x.content_sha256,"detail":x.detail} for x in rows]}
