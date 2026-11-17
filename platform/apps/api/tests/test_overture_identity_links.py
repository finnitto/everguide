from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import (
    AuditEvent,
    CompaniesHouseCandidate,
    OvertureCandidate,
    OvertureCompanyLink,
    IdentityAssessmentRun,
    CompanyWebsiteDiscoveryRun,
    CompanyWebsiteCandidate,
)
from app.identity_tasks import (
    _company_has_verified_overture_link,
    verified_overture_company_query,
    run_identity_assessment,
)
import app.identity_tasks as identity_tasks
from app.identity_review_auth import require_identity_reviewer


def make_database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


def seed_candidates(factory):
    db = factory()
    overture = OvertureCandidate(
        gers_id="GERS-TEST-001",
        candidate_name="Example Funeral Directors",
    )
    company = CompaniesHouseCandidate(
        company_number="01234567",
        company_name="EXAMPLE FUNERAL DIRECTORS LIMITED",
        company_status="active",
    )
    db.add_all([overture, company])
    db.commit()
    ids = (overture.id, company.id)
    db.close()
    return ids


def test_reviewer_token_resolves_configured_identity(monkeypatch):
    import hashlib
    from app.config import settings
    from fastapi.security import HTTPAuthorizationCredentials
    from app.identity_review_auth import require_identity_reviewer

    token = "test-only-high-entropy-reviewer-token"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    monkeypatch.setattr(settings, "identity_review_credentials", '{"reviewer-42":"' + digest + '"}')
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    assert require_identity_reviewer(credentials) == "reviewer-42"


def test_unknown_reviewer_token_is_rejected(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from app.config import settings
    from fastapi.security import HTTPAuthorizationCredentials
    from app.identity_review_auth import require_identity_reviewer

    monkeypatch.setattr(settings, "identity_review_credentials", '{"reviewer-42":"' + ("0" * 64) + '"}')
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong-token")
    with pytest.raises(HTTPException) as exc:
        require_identity_reviewer(credentials)
    assert exc.value.status_code == 401


def test_identity_review_api_rejects_requests_without_reviewer_credentials():
    with TestClient(app) as client:
        response = client.get("/api/v1/identity-review/overture-links")
    assert response.status_code == 401


def test_provenance_link_is_pending_until_reviewed_and_audited():
    engine, factory = make_database()

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_identity_reviewer] = lambda: "authenticated-reviewer"
    overture_id, company_id = seed_candidates(factory)
    try:
        with TestClient(app) as client:
            created = client.post("/api/v1/identity-review/overture-links", json={
                "overture_candidate_id": overture_id,
                "companies_house_candidate_id": company_id,
            })
            assert created.status_code == 200, created.text
            link_id = created.json()["id"]
            assert created.json()["status"] == "pending"

            db = factory()
            assert not _company_has_verified_overture_link(db, company_id)
            assert verified_overture_company_query(db).count() == 0
            db.close()

            missing_evidence = client.patch(
                f"/api/v1/identity-review/overture-links/{link_id}",
                json={
                    "status": "verified",
                    "reviewed_by": "attacker-supplied-name",
                    "evidence": {"source_reference": "just a note"},
                },
            )
            assert missing_evidence.status_code == 400

            verified = client.patch(
                f"/api/v1/identity-review/overture-links/{link_id}",
                json={
                    "status": "verified",
                    "reviewed_by": "attacker-supplied-name",
                    "evidence": {
                        "source_type": "official_website",
                        "source_reference": "https://examplefunerals.co.uk/about",
                        "finding": "The official site identifies the same trading name and company number.",
                        "matched_fields": ["trading_name", "branch_address", "company_number"],
                    },
                    "review_notes": "Identity relationship checked.",
                },
            )
            assert verified.status_code == 200, verified.text
            assert verified.json()["status"] == "verified"
            assert verified.json()["reviewed_by"] == "authenticated-reviewer"

            db = factory()
            assert _company_has_verified_overture_link(db, company_id)
            assert verified_overture_company_query(db).count() == 1
            db.close()

            listing = client.get("/api/v1/identity-review/overture-links?status=verified")
            assert listing.status_code == 200
            assert listing.json()["items"][0]["gers_id"] == "GERS-TEST-001"
            assert listing.json()["items"][0]["reviewed_by"] == "authenticated-reviewer"
            db = factory()
            audit = db.query(AuditEvent).filter(
                AuditEvent.entity_type == "overture_company_link",
                AuditEvent.entity_id == link_id,
                AuditEvent.action == "status_changed",
            ).first()
            assert audit is not None
            assert audit.detail["status"] == "verified"
            assert audit.actor == "authenticated-reviewer"
            db.close()
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_identity_reviewer, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_pending_and_rejected_links_never_qualify_for_identity_assessment():
    engine, factory = make_database()
    overture_id, company_id = seed_candidates(factory)
    db = factory()
    link = OvertureCompanyLink(
        overture_candidate_id=overture_id,
        companies_house_candidate_id=company_id,
        status="pending",
    )
    db.add(link)
    db.commit()
    assert not _company_has_verified_overture_link(db, company_id)

    link.status = "rejected"
    link.reviewed_by = "reviewer"
    link.reviewed_at = datetime.now(timezone.utc)
    link.evidence_json = {"reason": "not the same legal entity"}
    db.commit()
    assert not _company_has_verified_overture_link(db, company_id)
    assert verified_overture_company_query(db).count() == 0
    db.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_duplicate_candidate_pair_is_rejected_but_company_can_link_to_multiple_overture_branches():
    engine, factory = make_database()

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_identity_reviewer] = lambda: "authenticated-reviewer"
    overture_id, company_id = seed_candidates(factory)
    try:
        with TestClient(app) as client:
            first = client.post("/api/v1/identity-review/overture-links", json={
                "overture_candidate_id": overture_id,
                "companies_house_candidate_id": company_id,
            })
            assert first.status_code == 200
            duplicate = client.post("/api/v1/identity-review/overture-links", json={
                "overture_candidate_id": overture_id,
                "companies_house_candidate_id": company_id,
            })
            assert duplicate.status_code == 409

            # A second Overture candidate may represent another branch of the same
            # legal entity. Seed it directly; this route is intentionally not assumed.
            db = factory()
            from app.models import OvertureCandidate
            second = OvertureCandidate(gers_id="GERS-TEST-002", candidate_name="Example Funeral Directors - Branch 2")
            db.add(second)
            db.commit()
            second_id = second.id
            db.close()
            second_pair = client.post("/api/v1/identity-review/overture-links", json={
                "overture_candidate_id": second_id,
                "companies_house_candidate_id": company_id,
            })
            assert second_pair.status_code == 200, second_pair.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_identity_reviewer, None)
        Base.metadata.drop_all(engine)
        engine.dispose()



def test_direct_worker_invocation_completes_without_processing_unlinked_company(monkeypatch):
    engine, factory = make_database()
    overture_id, company_id = seed_candidates(factory)
    db = factory()
    discovery = CompanyWebsiteDiscoveryRun(status="completed")
    db.add(discovery)
    db.flush()
    db.add(
        CompanyWebsiteCandidate(
            companies_house_candidate_id=company_id,
            discovery_run_id=discovery.id,
            result_title="Example Funeral Directors",
            result_url="https://examplefunerals.co.uk",
            result_domain="examplefunerals.co.uk",
            search_provider="test",
            verification_status="identity_signals_found",
        )
    )
    run = IdentityAssessmentRun(status="queued")
    db.add(run)
    db.commit()
    run_id = run.id
    db.close()

    monkeypatch.setattr(identity_tasks, "SessionLocal", factory)

    def must_not_process(*args, **kwargs):
        raise AssertionError("Unlinked Companies House candidate reached process_company")

    monkeypatch.setattr(identity_tasks, "process_company", must_not_process)
    try:
        result = run_identity_assessment.run(run_id)
        assert result["status"] == "completed"
        db = factory()
        stored_run = db.get(IdentityAssessmentRun, run_id)
        assert stored_run.processed_companies == 0
        assert stored_run.identity_reviews_created == 0
        db.close()
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()

def test_overture_write_endpoints_reject_requests_without_reviewer_credentials():
    requests = [
        ("/api/v1/overture/imports", {"records": [{"gers_id": "GERS-AUTH-TEST", "name": "Test Funeral Directors"}]}),
        ("/api/v1/overture/feed/check", None),
        ("/api/v1/overture/process", None),
    ]
    with TestClient(app) as client:
        for path, payload in requests:
            response = client.post(path, json=payload) if payload is not None else client.post(path)
            assert response.status_code == 401, (path, response.status_code, response.text)

