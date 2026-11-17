from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.identity_review_auth import require_identity_reviewer
from app.main import app
from app.models import AuditEvent, Branch, EvidenceRevalidationRequest, MembershipEvidence, Provider, SourcePermission


SOURCE = {
    "source_name": "Official scheme register",
    "source_url": "https://example.org/register/record/123",
    "source_rights_basis": "Public register record; reviewer checked terms of use",
    "evidence_sha256": "a" * 64,
    "evidence_excerpt": "Member record shown as active",
    "evidence_payload": {"record_reference": "123"},
}


def _client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_identity_reviewer] = lambda: "stage3-reviewer"
    with factory() as db:
        provider = Provider(trading_name="Independent Funeral Care", business_form="unknown")
        other = Provider(trading_name="Other Funeral Care", business_form="unknown")
        db.add_all([provider, other])
        db.flush()
        branch = Branch(
            provider_id=provider.id,
            branch_name="York Branch",
            address_line_1="1 High Street",
            town_city="York",
            postcode="YO1 1AA",
        )
        other_branch = Branch(
            provider_id=other.id,
            branch_name="Leeds Branch",
            address_line_1="2 High Street",
            town_city="Leeds",
            postcode="LS1 1AA",
        )
        db.add_all([branch, other_branch])
        db.commit()
        ids = {
            "provider_id": provider.id,
            "other_provider_id": other.id,
            "branch_id": branch.id,
            "other_branch_id": other_branch.id,
        }
    return engine, factory, ids


def _close(engine):
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_identity_reviewer, None)
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_evidence_routes_require_reviewer_authentication():
    engine, _factory, ids = _client()
    try:
        app.dependency_overrides.pop(require_identity_reviewer, None)
        with TestClient(app) as client:
            assert client.get("/api/v1/evidence/summary").status_code == 401
            assert client.get("/api/v1/evidence/pricing").status_code == 401
    finally:
        _close(engine)


def test_pricing_evidence_is_separate_and_requires_review():
    engine, factory, ids = _client()
    try:
        payload = {
            **SOURCE,
            "provider_id": ids["provider_id"],
            "branch_id": ids["branch_id"],
            "service_category": "cremation",
            "service_name": "Attended funeral",
            "fee_type": "professional_services",
            "amount": "1950.00",
            "currency": "gbp",
            "price_basis": "fixed",
            "includes": ["staff", "coffin"],
            "excludes": ["third-party crematorium fee"],
            "applicability": {"branch_only": True},
        }
        with TestClient(app) as client:
            response = client.post("/api/v1/evidence/pricing", json=payload)
            assert response.status_code == 201, response.text
            item = response.json()
            assert item["amount"] == "1950.00"
            assert item["currency"] == "GBP"
            assert item["review_status"] == "pending"
            assert item["branch_id"] == ids["branch_id"]
            decision = client.post(
                f"/api/v1/evidence/pricing/{item['id']}/decision",
                json={"review_status": "approved", "review_notes": "Checked against source page"},
            )
            assert decision.status_code == 200, decision.text
            assert decision.json()["reviewed_by"] == "stage3-reviewer"
            assert decision.json()["review_status"] == "approved"
            assert client.get("/api/v1/evidence/summary").json()["pricing"]["approved"] == 1
        with factory() as db:
            provider = db.get(Provider, ids["provider_id"])
            assert provider.status == "draft"
            assert provider.business_form == "unknown"
    finally:
        _close(engine)


def test_branch_evidence_cannot_be_attached_to_another_provider():
    engine, _factory, ids = _client()
    try:
        payload = {
            **SOURCE,
            "provider_id": ids["provider_id"],
            "branch_id": ids["other_branch_id"],
            "service_category": "cremation",
            "service_name": "Direct cremation",
            "fee_type": "package",
            "amount": "950.00",
        }
        with TestClient(app) as client:
            response = client.post("/api/v1/evidence/pricing", json=payload)
            assert response.status_code == 400, response.text
    finally:
        _close(engine)


def test_sole_trader_and_partnership_do_not_need_companies_house_links():
    engine, factory, ids = _client()
    try:
        with TestClient(app) as client:
            response = client.patch(
                f"/api/v1/evidence/providers/{ids['provider_id']}/business-form",
                json={"business_form": "sole_trader"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["companies_house_link_required"] is False
        with factory() as db:
            provider = db.get(Provider, ids["provider_id"])
            assert provider.business_form == "sole_trader"
        with TestClient(app) as client:
            response = client.patch(
                f"/api/v1/evidence/providers/{ids['other_provider_id']}/business-form",
                json={"business_form": "partnership"},
            )
            assert response.status_code == 200, response.text
    finally:
        _close(engine)


def test_provider_update_audit_uses_authenticated_reviewer():
    engine, factory, ids = _client()
    try:
        with TestClient(app) as client:
            response = client.patch(
                f"/api/v1/providers/{ids['provider_id']}",
                json={"trading_name": "Updated Funeral Care"},
            )
            assert response.status_code == 200, response.text
        with factory() as db:
            event = (
                db.query(AuditEvent)
                .filter(AuditEvent.entity_type == "provider", AuditEvent.entity_id == ids["provider_id"])
                .order_by(AuditEvent.id.desc())
                .first()
            )
            assert event is not None
            assert event.actor == "stage3-reviewer"
    finally:
        _close(engine)

def test_membership_and_fca_evidence_are_independent_and_not_inferred():
    engine, _factory, ids = _client()
    try:
        membership_payload = {
            **SOURCE,
            "provider_id": ids["provider_id"],
            "scheme_code": "NAFD",
            "reported_status": "active",
            "applicability_status": "applicable",
            "membership_number": "NAFD-12345",
        }
        regulatory_payload = {
            **SOURCE,
            "provider_id": ids["provider_id"],
            "source_name": "FCA register",
            "source_url": "https://example.org/fca/firm/123",
            "regulator_code": "FCA",
            "reported_status": "unknown",
            "applicability_status": "unknown",
            "reference_number": "FRN123",
        }
        with TestClient(app) as client:
            membership = client.post("/api/v1/evidence/membership", json=membership_payload)
            regulatory = client.post("/api/v1/evidence/regulatory", json=regulatory_payload)
            assert membership.status_code == 201, membership.text
            assert regulatory.status_code == 201, regulatory.text
            assert membership.json()["review_status"] == "pending"
            assert regulatory.json()["reported_status"] == "unknown"
            assert client.get("/api/v1/evidence/summary").json()["membership"]["total"] == 1
            assert client.get("/api/v1/evidence/summary").json()["regulatory"]["total"] == 1
    finally:
        _close(engine)


def test_expired_evidence_cannot_be_approved():
    engine, _factory, ids = _client()
    try:
        payload = {
            **SOURCE,
            "provider_id": ids["provider_id"],
            "source_retrieved_at": "2026-01-01T00:00:00Z",
            "expires_at": "2026-01-02T00:00:00Z",
            "service_category": "cremation",
            "service_name": "Direct cremation",
            "fee_type": "package",
            "amount": "900.00",
        }
        with TestClient(app) as client:
            created = client.post("/api/v1/evidence/pricing", json=payload)
            assert created.status_code == 201, created.text
            response = client.post(
                f"/api/v1/evidence/pricing/{created.json()['id']}/decision",
                json={"review_status": "approved", "review_notes": "Should be rejected as expired"},
            )
            assert response.status_code == 409, response.text
            assert "Expired evidence" in response.json()["detail"]
    finally:
        _close(engine)

def test_approved_source_permission_cannot_authorise_another_domain():
    engine, factory, ids = _client()
    try:
        with factory() as db:
            permission = SourcePermission(
                provider_id=ids["provider_id"],
                source_url="https://allowed.example.org/terms",
                source_domain="allowed.example.org",
                permission_status="approved",
                permission_basis="Reviewed terms",
            )
            db.add(permission)
            db.commit()
            permission_id = permission.id
        payload = {
            **SOURCE,
            "provider_id": ids["provider_id"],
            "source_permission_id": permission_id,
            "service_category": "cremation",
            "service_name": "Direct cremation",
            "fee_type": "package",
            "amount": "900.00",
        }
        with TestClient(app) as client:
            response = client.post("/api/v1/evidence/pricing", json=payload)
            assert response.status_code == 400, response.text
            assert "outside the approved" in response.json()["detail"]
    finally:
        _close(engine)


def test_evidence_dates_must_be_timezone_aware():
    engine, _factory, ids = _client()
    try:
        payload = {
            **SOURCE,
            "provider_id": ids["provider_id"],
            "source_retrieved_at": "2026-01-01T00:00:00",
            "service_category": "cremation",
            "service_name": "Direct cremation",
            "fee_type": "package",
            "amount": "900.00",
        }
        with TestClient(app) as client:
            response = client.post("/api/v1/evidence/pricing", json=payload)
            assert response.status_code == 422, response.text
            assert "timezone" in response.text
    finally:
        _close(engine)

def test_revalidation_is_idempotent_bounded_and_transient_failures_do_not_change_evidence():
    from app.routers import evidence as evidence_router

    engine, factory, ids = _client()
    now = {"value": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    original_now = evidence_router._now
    evidence_router._now = lambda: now["value"]
    try:
        payload = {
            **SOURCE,
            "provider_id": ids["provider_id"],
            "scheme_code": "SAIF",
            "reported_status": "active",
            "applicability_status": "applicable",
        }
        with TestClient(app) as client:
            created = client.post("/api/v1/evidence/membership", json=payload)
            assert created.status_code == 201, created.text
            evidence_id = created.json()["id"]
            request_payload = {
                "domain": "membership",
                "evidence_id": evidence_id,
                "idempotency_key": "membership-check-001",
                "reason": "Periodic membership revalidation",
            }
            request1 = client.post("/api/v1/evidence/revalidation-requests", json=request_payload)
            request2 = client.post("/api/v1/evidence/revalidation-requests", json=request_payload)
            assert request1.status_code == 201
            assert request2.status_code == 201
            assert request1.json()["id"] == request2.json()["id"]
            changed_request = client.post(
                "/api/v1/evidence/revalidation-requests",
                json={**request_payload, "reason": "Different purpose"},
            )
            assert changed_request.status_code == 409, changed_request.text

            request_id = request1.json()["id"]
            first_attempt_payload = {
                "idempotency_key": "membership-attempt-001",
                "outcome": "transient_failure",
                "failure_class": "upstream_unavailable",
                "detail": "Register temporarily unavailable",
            }
            first_attempt = client.post(
                f"/api/v1/evidence/revalidation-requests/{request_id}/attempts",
                json=first_attempt_payload,
            )
            assert first_attempt.status_code == 200, first_attempt.text
            duplicate_attempt = client.post(
                f"/api/v1/evidence/revalidation-requests/{request_id}/attempts",
                json=first_attempt_payload,
            )
            assert duplicate_attempt.status_code == 200, duplicate_attempt.text
            assert duplicate_attempt.json()["attempt"]["id"] == first_attempt.json()["attempt"]["id"]
            changed_attempt = client.post(
                f"/api/v1/evidence/revalidation-requests/{request_id}/attempts",
                json={**first_attempt_payload, "detail": "Different result"},
            )
            assert changed_attempt.status_code == 409, changed_attempt.text
            state = first_attempt.json()["request"]
            now["value"] = datetime.fromisoformat(state["next_attempt_at"].replace("Z", "+00:00"))
            for attempt_number in range(2, 5):
                attempt = client.post(
                    f"/api/v1/evidence/revalidation-requests/{request_id}/attempts",
                    json={
                        "idempotency_key": f"membership-attempt-{attempt_number:03d}",
                        "outcome": "transient_failure",
                        "failure_class": "upstream_unavailable",
                        "detail": "Register temporarily unavailable",
                    },
                )
                assert attempt.status_code == 200, attempt.text
                state = attempt.json()["request"]
                if attempt_number < 4:
                    assert state["status"] == "retry_wait"
                    next_attempt = state["next_attempt_at"].replace("Z", "+00:00")
                    now["value"] = datetime.fromisoformat(next_attempt)
                else:
                    assert state["status"] == "failed"
                    assert "retry_limit_reached" in state["last_error"]

        with factory() as db:
            membership = db.get(MembershipEvidence, evidence_id)
            request = db.get(EvidenceRevalidationRequest, request_id)
            assert membership.reported_status == "active"
            assert membership.review_status == "pending"
            assert request.attempt_count == 4
    finally:
        evidence_router._now = original_now
        _close(engine)
