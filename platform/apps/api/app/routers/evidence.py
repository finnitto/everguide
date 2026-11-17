"""Reviewer-only capture and review APIs for independent evidence domains.

These routes record reviewer-supplied evidence. They do not fetch external sources,
infer membership/regulatory status, alter Overture identity fields, or publish providers.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.identity_review_auth import require_identity_reviewer
from app.models import (
    AuditEvent, Branch, EvidenceRevalidationAttempt, EvidenceRevalidationRequest,
    MembershipEvidence, PricingEvidence, Provider, RegulatoryEvidence, SourcePermission,
)

router = APIRouter(
    prefix="/api/v1/evidence",
    tags=["independent evidence"],
    dependencies=[Depends(require_identity_reviewer)],
)

REVALIDATION_RETRY_DELAYS_DAYS = (2, 7, 21)
EVIDENCE_MODELS = {
    "pricing": PricingEvidence,
    "membership": MembershipEvidence,
    "regulatory": RegulatoryEvidence,
}


def _now():
    return datetime.now(timezone.utc)


class EvidenceCommonIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    provider_id: int = Field(gt=0)
    branch_id: int | None = Field(default=None, gt=0)
    source_name: str = Field(min_length=2, max_length=240)
    source_url: HttpUrl
    source_rights_basis: str = Field(min_length=5, max_length=2000)
    source_permission_id: int | None = Field(default=None, gt=0)
    source_retrieved_at: datetime | None = None
    expires_at: datetime | None = None
    evidence_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    evidence_excerpt: str | None = Field(default=None, max_length=4000)
    evidence_payload: dict = Field(default_factory=dict)
    @field_validator("source_rights_basis")
    @classmethod
    def nonblank_rights_basis(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A source-rights basis is required.")
        return value.strip()


class PricingEvidenceIn(EvidenceCommonIn):
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    service_category: str = Field(min_length=2, max_length=60)
    service_name: str = Field(min_length=2, max_length=240)
    fee_type: str = Field(min_length=2, max_length=60)
    amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    amount_upper: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="GBP", min_length=3, max_length=3)
    price_basis: Literal["fixed", "from", "range", "estimate", "other"] = "fixed"
    includes: list[str] = Field(default_factory=list, max_length=100)
    excludes: list[str] = Field(default_factory=list, max_length=100)
    applicability: dict = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def currency_uppercase(cls, value: str) -> str:
        value = value.upper()
        if not value.isalpha():
            raise ValueError("Currency must be a three-letter code.")
        return value


class MembershipEvidenceIn(EvidenceCommonIn):
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    scheme_code: Literal["NAFD", "SAIF", "SAIFCharter", "other"]
    membership_number: str | None = Field(default=None, max_length=100)
    member_name: str | None = Field(default=None, max_length=240)
    reported_status: Literal["active", "inactive", "suspended", "expired", "not_found", "unknown", "pending"]
    applicability_status: Literal["applicable", "not_applicable", "unknown"] = "unknown"


class RegulatoryEvidenceIn(EvidenceCommonIn):
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    regulator_code: Literal["FCA", "other"]
    reference_number: str | None = Field(default=None, max_length=100)
    permissions: list[str] = Field(default_factory=list, max_length=100)
    reported_status: Literal["authorised", "not_authorised", "suspended", "cancelled", "no_match", "unknown", "pending"]
    applicability_status: Literal["applicable", "not_applicable", "unknown"] = "unknown"


class EvidenceDecisionIn(BaseModel):
    review_status: Literal["approved", "rejected", "requires_update"]
    review_notes: str | None = Field(default=None, max_length=2000)


class BusinessFormUpdateIn(BaseModel):
    business_form: Literal["unknown", "limited_company", "llp", "partnership", "sole_trader", "other"]


class RevalidationRequestIn(BaseModel):
    domain: Literal["pricing", "membership", "regulatory"]
    evidence_id: int = Field(gt=0)
    idempotency_key: str = Field(min_length=8, max_length=128)
    reason: str = Field(min_length=5, max_length=1000)


class RevalidationAttemptIn(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    outcome: Literal["success", "transient_failure", "permanent_failure"]
    source_url: HttpUrl | None = None
    evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    failure_class: str | None = Field(default=None, max_length=60)
    detail: str | None = Field(default=None, max_length=2000)


def _validate_subject(db: Session, provider_id: int, branch_id: int | None) -> None:
    if not db.get(Provider, provider_id):
        raise HTTPException(404, "Provider not found")
    if branch_id is not None:
        branch = db.get(Branch, branch_id)
        if not branch:
            raise HTTPException(404, "Branch not found")
        if branch.provider_id != provider_id:
            raise HTTPException(400, "Branch does not belong to the selected provider")


def _validate_source_permission(db: Session, provider_id: int, permission_id: int | None, source_url: str) -> None:
    if permission_id is None:
        return
    permission = db.get(SourcePermission, permission_id)
    if not permission or permission.provider_id != provider_id:
        raise HTTPException(400, "Source permission does not belong to this provider")
    if permission.permission_status != "approved":
        raise HTTPException(409, "The referenced source permission is not approved")
    source_host = (urlsplit(source_url).hostname or "").lower().removeprefix("www.")
    permitted_domain = (permission.source_domain or "").lower().removeprefix("www.")
    if not source_host or not permitted_domain or not (source_host == permitted_domain or source_host.endswith("." + permitted_domain)):
        raise HTTPException(400, "Source URL host is outside the approved source-permission domain")


def _common_fields(payload: EvidenceCommonIn) -> dict:
    values = payload.model_dump()
    values["source_url"] = str(payload.source_url)
    values["source_retrieved_at"] = payload.source_retrieved_at or _now()
    values["evidence_sha256"] = payload.evidence_sha256.lower()
    return values


def _validate_dates(payload: EvidenceCommonIn) -> None:
    date_values = {
        name: getattr(payload, name, None)
        for name in ("source_retrieved_at", "expires_at", "effective_from", "effective_to", "valid_from", "valid_to")
    }
    for name, value in date_values.items():
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise HTTPException(422, f"{name} must include a timezone")
    for start_name, end_name in (("effective_from", "effective_to"), ("valid_from", "valid_to")):
        start = getattr(payload, start_name, None)
        end = getattr(payload, end_name, None)
        if start and end and end < start:
            raise HTTPException(422, f"{end_name} must be on or after {start_name}")
    retrieved_at = payload.source_retrieved_at
    if retrieved_at and retrieved_at > _now() + timedelta(minutes=5):
        raise HTTPException(422, "source_retrieved_at cannot be more than five minutes in the future")
    if payload.expires_at and retrieved_at and payload.expires_at < retrieved_at:
        raise HTTPException(422, "expires_at must be on or after source_retrieved_at")


def _record_dict(row) -> dict:
    result = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    if "amount" in result and result["amount"] is not None:
        result["amount"] = str(result["amount"])
    if "amount_upper" in result and result["amount_upper"] is not None:
        result["amount_upper"] = str(result["amount_upper"])
    return result


def _request_dict(row) -> dict:
    return {
        "id": row.id,
        "idempotency_key": row.idempotency_key,
        "domain": row.domain,
        "evidence_id": row.evidence_id,
        "provider_id": row.provider_id,
        "branch_id": row.branch_id,
        "reason": row.reason,
        "status": row.status,
        "attempt_count": row.attempt_count,
        "max_attempts": row.max_attempts,
        "next_attempt_at": row.next_attempt_at,
        "last_attempt_at": row.last_attempt_at,
        "last_error": row.last_error,
        "requested_by": row.requested_by,
        "completed_at": row.completed_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _list_records(db: Session, model, provider_id, branch_id, review_status, include_expired, limit, offset):
    query = db.query(model)
    if provider_id is not None:
        query = query.filter(model.provider_id == provider_id)
    if branch_id is not None:
        query = query.filter(model.branch_id == branch_id)
    if review_status is not None:
        query = query.filter(model.review_status == review_status)
    if not include_expired:
        now = _now()
        expiry_conditions = [or_(model.expires_at.is_(None), model.expires_at >= now)]
        for expiry_field in ("effective_to", "valid_to"):
            expiry_column = getattr(model, expiry_field, None)
            if expiry_column is not None:
                expiry_conditions.append(or_(expiry_column.is_(None), expiry_column >= now))
        query = query.filter(*expiry_conditions)
    total = query.count()
    rows = query.order_by(model.source_retrieved_at.desc(), model.id.desc()).offset(offset).limit(limit).all()
    return {"count": total, "items": [_record_dict(row) for row in rows]}


def _create_evidence(db: Session, model, payload: EvidenceCommonIn, reviewer: str, detail: dict):
    _validate_subject(db, payload.provider_id, payload.branch_id)
    _validate_source_permission(db, payload.provider_id, payload.source_permission_id, str(payload.source_url))
    _validate_dates(payload)
    values = _common_fields(payload)
    # Shared request schemas contain both effective-date and validity-date pairs;
    # retain only fields defined by the selected evidence-domain table.
    model_columns = {column.name for column in model.__table__.columns}
    values = {key: value for key, value in values.items() if key in model_columns}
    values["review_status"] = "pending"
    row = model(**values)
    db.add(row)
    db.flush()
    db.add(AuditEvent(
        entity_type=model.__tablename__,
        entity_id=row.id,
        action="evidence_captured",
        detail={**detail, "provider_id": row.provider_id, "branch_id": row.branch_id,
                "source_name": row.source_name, "evidence_sha256": row.evidence_sha256},
        actor=reviewer,
    ))
    db.commit()
    db.refresh(row)
    return row


def _decide_evidence(db: Session, model, evidence_id: int, payload: EvidenceDecisionIn, reviewer: str):
    row = db.get(model, evidence_id)
    if not row:
        raise HTTPException(404, "Evidence record not found")
    row.review_status = payload.review_status
    row.reviewed_by = reviewer
    row.reviewed_at = _now()
    row.review_notes = payload.review_notes
    db.add(AuditEvent(
        entity_type=model.__tablename__,
        entity_id=row.id,
        action="evidence_reviewed",
        detail={"review_status": row.review_status, "review_notes": row.review_notes},
        actor=reviewer,
    ))
    db.commit()
    db.refresh(row)
    return row


@router.get("/summary")
def evidence_summary(provider_id: int | None = None, db: Session = Depends(get_db)):
    if provider_id is not None and not db.get(Provider, provider_id):
        raise HTTPException(404, "Provider not found")
    result = {}
    for domain, model in EVIDENCE_MODELS.items():
        query = db.query(model)
        if provider_id is not None:
            query = query.filter(model.provider_id == provider_id)
        result[domain] = {
            "total": query.count(),
            "pending_review": query.filter(model.review_status == "pending").count(),
            "approved": query.filter(model.review_status == "approved").count(),
            "rejected": query.filter(model.review_status == "rejected").count(),
        }
    return result


@router.get("/pricing")
def list_pricing(provider_id: int | None = None, branch_id: int | None = None,
                 review_status: str | None = None, include_expired: bool = False,
                 limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                 db: Session = Depends(get_db)):
    return _list_records(db, PricingEvidence, provider_id, branch_id, review_status, include_expired, limit, offset)


@router.post("/pricing", status_code=201)
def capture_pricing(payload: PricingEvidenceIn, reviewer: str = Depends(require_identity_reviewer),
                    db: Session = Depends(get_db)):
    if payload.amount_upper is not None and payload.amount_upper < payload.amount:
        raise HTTPException(422, "amount_upper must be greater than or equal to amount")
    row = _create_evidence(db, PricingEvidence, payload, reviewer, {
        "service_category": payload.service_category, "service_name": payload.service_name,
        "fee_type": payload.fee_type, "amount": str(payload.amount), "currency": payload.currency,
    })
    return _record_dict(row)


@router.post("/pricing/{evidence_id}/decision")
def decide_pricing(evidence_id: int, payload: EvidenceDecisionIn,
                   reviewer: str = Depends(require_identity_reviewer), db: Session = Depends(get_db)):
    return _record_dict(_decide_evidence(db, PricingEvidence, evidence_id, payload, reviewer))


@router.get("/membership")
def list_membership(provider_id: int | None = None, branch_id: int | None = None,
                    review_status: str | None = None, include_expired: bool = False,
                    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                    db: Session = Depends(get_db)):
    return _list_records(db, MembershipEvidence, provider_id, branch_id, review_status, include_expired, limit, offset)


@router.post("/membership", status_code=201)
def capture_membership(payload: MembershipEvidenceIn, reviewer: str = Depends(require_identity_reviewer),
                       db: Session = Depends(get_db)):
    _validate_dates(payload)
    row = _create_evidence(db, MembershipEvidence, payload, reviewer, {
        "scheme_code": payload.scheme_code, "reported_status": payload.reported_status,
        "applicability_status": payload.applicability_status,
    })
    return _record_dict(row)


@router.post("/membership/{evidence_id}/decision")
def decide_membership(evidence_id: int, payload: EvidenceDecisionIn,
                      reviewer: str = Depends(require_identity_reviewer), db: Session = Depends(get_db)):
    return _record_dict(_decide_evidence(db, MembershipEvidence, evidence_id, payload, reviewer))


@router.get("/regulatory")
def list_regulatory(provider_id: int | None = None, branch_id: int | None = None,
                    review_status: str | None = None, include_expired: bool = False,
                    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                    db: Session = Depends(get_db)):
    return _list_records(db, RegulatoryEvidence, provider_id, branch_id, review_status, include_expired, limit, offset)


@router.post("/regulatory", status_code=201)
def capture_regulatory(payload: RegulatoryEvidenceIn, reviewer: str = Depends(require_identity_reviewer),
                       db: Session = Depends(get_db)):
    _validate_dates(payload)
    row = _create_evidence(db, RegulatoryEvidence, payload, reviewer, {
        "regulator_code": payload.regulator_code, "reported_status": payload.reported_status,
        "applicability_status": payload.applicability_status,
    })
    return _record_dict(row)


@router.post("/regulatory/{evidence_id}/decision")
def decide_regulatory(evidence_id: int, payload: EvidenceDecisionIn,
                      reviewer: str = Depends(require_identity_reviewer), db: Session = Depends(get_db)):
    return _record_dict(_decide_evidence(db, RegulatoryEvidence, evidence_id, payload, reviewer))


@router.patch("/providers/{provider_id}/business-form")
def update_business_form(provider_id: int, payload: BusinessFormUpdateIn,
                         reviewer: str = Depends(require_identity_reviewer), db: Session = Depends(get_db)):
    provider = db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    previous = provider.business_form
    provider.business_form = payload.business_form
    db.add(AuditEvent(
        entity_type="provider",
        entity_id=provider.id,
        action="business_form_updated",
        detail={"previous": previous, "business_form": provider.business_form,
                "companies_house_link_required": False},
        actor=reviewer,
    ))
    db.commit()
    return {"provider_id": provider.id, "business_form": provider.business_form,
            "companies_house_link_required": False}


@router.post("/revalidation-requests", status_code=201)
def create_revalidation_request(payload: RevalidationRequestIn,
                                reviewer: str = Depends(require_identity_reviewer),
                                db: Session = Depends(get_db)):
    model = EVIDENCE_MODELS[payload.domain]
    evidence = db.get(model, payload.evidence_id)
    if not evidence:
        raise HTTPException(404, "Evidence record not found")
    existing = db.query(EvidenceRevalidationRequest).filter(
        EvidenceRevalidationRequest.idempotency_key == payload.idempotency_key
    ).first()
    if existing:
        if (existing.domain != payload.domain or existing.evidence_id != payload.evidence_id or existing.reason != payload.reason):
            raise HTTPException(409, "Idempotency key was already used for a different request payload")
        return _request_dict(existing)
    row = EvidenceRevalidationRequest(
        idempotency_key=payload.idempotency_key,
        domain=payload.domain,
        evidence_id=evidence.id,
        provider_id=evidence.provider_id,
        branch_id=evidence.branch_id,
        reason=payload.reason,
        status="requested",
        requested_by=reviewer,
        max_attempts=4,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.query(EvidenceRevalidationRequest).filter(
            EvidenceRevalidationRequest.idempotency_key == payload.idempotency_key
        ).first()
        if existing and existing.domain == payload.domain and existing.evidence_id == payload.evidence_id and existing.reason == payload.reason:
            return _request_dict(existing)
        if existing:
            raise HTTPException(409, "Idempotency key was already used for a different request payload")
        raise
    db.add(AuditEvent(
        entity_type="evidence_revalidation_request",
        entity_id=row.id,
        action="revalidation_requested",
        detail={"domain": row.domain, "evidence_id": row.evidence_id,
                "provider_id": row.provider_id, "branch_id": row.branch_id},
        actor=reviewer,
    ))
    db.commit()
    db.refresh(row)
    return _request_dict(row)


@router.get("/revalidation-requests")
def list_revalidation_requests(status: str | None = None, provider_id: int | None = None,
                               limit: int = Query(100, ge=1, le=500),
                               offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    query = db.query(EvidenceRevalidationRequest)
    if status:
        query = query.filter(EvidenceRevalidationRequest.status == status)
    if provider_id is not None:
        query = query.filter(EvidenceRevalidationRequest.provider_id == provider_id)
    total = query.count()
    rows = query.order_by(EvidenceRevalidationRequest.created_at.desc()).offset(offset).limit(limit).all()
    return {"count": total, "items": [_request_dict(row) for row in rows]}


@router.get("/revalidation-requests/{request_id}")
def get_revalidation_request(request_id: int, db: Session = Depends(get_db)):
    request = db.get(EvidenceRevalidationRequest, request_id)
    if not request:
        raise HTTPException(404, "Revalidation request not found")
    attempts = db.query(EvidenceRevalidationAttempt).filter(
        EvidenceRevalidationAttempt.request_id == request.id
    ).order_by(EvidenceRevalidationAttempt.attempt_number.asc()).all()
    return {
        "request": _request_dict(request),
        "attempts": [{
            "id": item.id,
            "attempt_number": item.attempt_number,
            "outcome": item.outcome,
            "failure_class": item.failure_class,
            "source_url": item.source_url,
            "evidence_sha256": item.evidence_sha256,
            "detail": item.detail,
            "checked_at": item.checked_at,
            "actor": item.actor,
        } for item in attempts],
    }


@router.post("/revalidation-requests/{request_id}/attempts")
def record_revalidation_attempt(request_id: int, payload: RevalidationAttemptIn,
                                reviewer: str = Depends(require_identity_reviewer),
                                db: Session = Depends(get_db)):
    request = db.query(EvidenceRevalidationRequest).filter(
        EvidenceRevalidationRequest.id == request_id
    ).with_for_update().first()
    if not request:
        raise HTTPException(404, "Revalidation request not found")
    prior = db.query(EvidenceRevalidationAttempt).filter(
        EvidenceRevalidationAttempt.request_id == request.id,
        EvidenceRevalidationAttempt.idempotency_key == payload.idempotency_key,
    ).first()
    if prior:
        same_payload = (
            prior.outcome == payload.outcome
            and prior.failure_class == payload.failure_class
            and prior.source_url == (str(payload.source_url) if payload.source_url else None)
            and prior.evidence_sha256 == (payload.evidence_sha256.lower() if payload.evidence_sha256 else None)
            and prior.detail == payload.detail
        )
        if not same_payload:
            raise HTTPException(409, "Attempt idempotency key was already used for a different payload")
        return {"request": _request_dict(request), "attempt": {
            "id": prior.id, "attempt_number": prior.attempt_number, "outcome": prior.outcome,
            "checked_at": prior.checked_at, "actor": prior.actor,
        }}
    now = _now()
    if request.status not in {"requested", "retry_wait"}:
        raise HTTPException(409, "Revalidation request is not open for another attempt")
    if request.next_attempt_at and request.next_attempt_at > now:
        raise HTTPException(409, "The next bounded retry is not due yet")
    if request.attempt_count >= request.max_attempts:
        raise HTTPException(409, "The bounded attempt limit has been reached")
    if payload.outcome == "success" and (not payload.source_url or not payload.evidence_sha256):
        raise HTTPException(422, "A successful check must record its source URL and evidence SHA-256")
    if payload.outcome != "success" and not payload.failure_class:
        raise HTTPException(422, "A failed check must include a failure class")

    attempt_number = request.attempt_count + 1
    attempt = EvidenceRevalidationAttempt(
        request_id=request.id,
        idempotency_key=payload.idempotency_key,
        attempt_number=attempt_number,
        outcome=payload.outcome,
        failure_class=payload.failure_class,
        source_url=str(payload.source_url) if payload.source_url else None,
        evidence_sha256=payload.evidence_sha256.lower() if payload.evidence_sha256 else None,
        detail=payload.detail,
        checked_at=now,
        actor=reviewer,
    )
    db.add(attempt)
    request.attempt_count = attempt_number
    request.last_attempt_at = now
    request.updated_at = now
    request.next_attempt_at = None
    request.last_error = payload.detail if payload.outcome != "success" else None
    if payload.outcome == "success":
        request.status = "completed"
        request.completed_at = now
        evidence_model = EVIDENCE_MODELS[request.domain]
        evidence_row = db.get(evidence_model, request.evidence_id)
        if evidence_row:
            evidence_row.last_checked_at = now
    elif payload.outcome == "permanent_failure":
        request.status = "failed"
        request.completed_at = now
    elif attempt_number >= request.max_attempts:
        request.status = "failed"
        request.last_error = (payload.detail or payload.failure_class or "Transient failure") + "; retry_limit_reached"
        request.completed_at = now
    else:
        request.status = "retry_wait"
        delay_days = REVALIDATION_RETRY_DELAYS_DAYS[min(attempt_number - 1, len(REVALIDATION_RETRY_DELAYS_DAYS) - 1)]
        request.next_attempt_at = now + timedelta(days=delay_days)

    db.add(AuditEvent(
        entity_type="evidence_revalidation_request",
        entity_id=request.id,
        action="revalidation_attempt_recorded",
        detail={"attempt_number": attempt_number, "outcome": payload.outcome,
                "request_status": request.status},
        actor=reviewer,
    ))
    db.commit()
    db.refresh(attempt)
    db.refresh(request)
    return {"request": _request_dict(request), "attempt": {
        "id": attempt.id, "attempt_number": attempt.attempt_number, "outcome": attempt.outcome,
        "failure_class": attempt.failure_class, "source_url": attempt.source_url,
        "evidence_sha256": attempt.evidence_sha256, "detail": attempt.detail,
        "checked_at": attempt.checked_at, "actor": attempt.actor,
    }}
