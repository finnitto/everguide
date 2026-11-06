from datetime import datetime, timezone
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Provider, SourcePermission, WebsiteEvidenceCheck, AuditEvent
from app.tasks import check_approved_sources
router = APIRouter(prefix="/api/v1/enrichment", tags=["source permissions and enrichment"])
class SourceInput(BaseModel):
    provider_id: int
    source_url: str = Field(min_length=10, max_length=1000)
    permission_basis: str | None = Field(default=None, max_length=4000)
    permission_reference: str | None = Field(default=None, max_length=500)
@router.get("/sources")
def list_sources(db: Session = Depends(get_db)):
    rows=db.query(SourcePermission).order_by(SourcePermission.created_at.desc()).limit(200).all()
    return {"items":[{"id":x.id,"provider_id":x.provider_id,"provider_name":db.get(Provider,x.provider_id).trading_name if db.get(Provider,x.provider_id) else "(deleted)","source_url":x.source_url,"source_domain":x.source_domain,"permission_status":x.permission_status,"permission_basis":x.permission_basis,"permission_reference":x.permission_reference,"approved_at":x.approved_at} for x in rows]}
@router.post("/sources",status_code=201)
def register_source(payload: SourceInput, db: Session=Depends(get_db)):
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
def approve_source(source_id:int, db:Session=Depends(get_db)):
    row=db.get(SourcePermission,source_id)
    if not row: raise HTTPException(404,"Source permission record not found")
    row.permission_status="approved"; row.approved_by="local-admin"; row.approved_at=datetime.now(timezone.utc)
    db.add(AuditEvent(entity_type="source_permission",entity_id=row.id,action="approved_for_fetch",detail={"domain":row.source_domain,"permission_reference":row.permission_reference,"basis":row.permission_basis})); db.commit()
    return {"id":row.id,"permission_status":row.permission_status,"message":"Approved source can be checked by the enrichment job."}
@router.post("/run",status_code=202)
def run_enrichment():
    task=check_approved_sources.delay()
    return {"status":"queued","task_id":task.id,"message":"Eligible registered HTTPS sources will be checked automatically. robots.txt is treated only as a crawler instruction, not as a licence or reuse permission."}
@router.get("/checks")
def list_checks(limit:int=100,db:Session=Depends(get_db)):
    rows=db.query(WebsiteEvidenceCheck).order_by(WebsiteEvidenceCheck.checked_at.desc()).limit(min(max(limit,1),250)).all()
    return {"items":[{"id":x.id,"source_permission_id":x.source_permission_id,"provider_id":x.provider_id,"checked_at":x.checked_at,"status":x.status,"http_status":x.http_status,"page_title":x.page_title,"content_sha256":x.content_sha256,"detail":x.detail} for x in rows]}
