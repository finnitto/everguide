from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import CompaniesHouseCandidate, OvertureCandidate, OvertureCompanyLink
from app.identity_tasks import _company_has_verified_overture_link, verified_overture_company_query


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


def test_provenance_link_is_pending_until_reviewed_and_audited():
    engine, factory = make_database()

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
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
                json={"status": "verified", "reviewed_by": "reviewer"},
            )
            assert missing_evidence.status_code == 400

            verified = client.patch(
                f"/api/v1/identity-review/overture-links/{link_id}",
                json={
                    "status": "verified",
                    "reviewed_by": "reviewer",
                    "evidence": {
                        "company_number_match": "01234567",
                        "source_reference": "manual evidence review",
                    },
                    "review_notes": "Identity relationship checked.",
                },
            )
            assert verified.status_code == 200, verified.text
            assert verified.json()["status"] == "verified"

            db = factory()
            assert _company_has_verified_overture_link(db, company_id)
            assert verified_overture_company_query(db).count() == 1
            db.close()

            listing = client.get("/api/v1/identity-review/overture-links?status=verified")
            assert listing.status_code == 200
            assert listing.json()["items"][0]["gers_id"] == "GERS-TEST-001"
            assert listing.json()["items"][0]["reviewed_by"] == "reviewer"
    finally:
        app.dependency_overrides.pop(get_db, None)
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


def test_duplicate_companies_house_provenance_link_is_rejected():
    engine, factory = make_database()

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
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
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(engine)
        engine.dispose()
