import io
import json
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base, get_db
from app.main import app
from app.models import Provider, Branch, AuditEvent
from app import models  # noqa: F401


def test_postcode_county_enrichment_only_fills_explicit_counties():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    db = session_factory()
    try:
        provider = Provider(trading_name="County Test Funeral Service", status="published")
        db.add(provider)
        db.flush()
        db.add_all([
            Branch(provider_id=provider.id, branch_name="Lancashire branch", address_line_1="1 High Street",
                   town_city="Preston", postcode="PR3 0SG", county=None, status="published"),
            Branch(provider_id=provider.id, branch_name="London branch", address_line_1="2 High Street",
                   town_city="London", postcode="SW1A 2AA", county=None, status="published"),
            Branch(provider_id=provider.id, branch_name="Existing county branch", address_line_1="3 High Street",
                   town_city="York", postcode="YO1 1AA", county="Existing County", status="published"),
        ])
        db.commit()
        db.close()

        response_payload = {
            "status": 200,
            "result": [
                {"query": "PR3 0SG", "result": {"postcode": "PR3 0SG", "country": "England",
                    "admin_county": "Lancashire", "admin_district": "Wyre", "region": "North West"}},
                {"query": "SW1A 2AA", "result": {"postcode": "SW1A 2AA", "country": "England",
                    "admin_county": None, "admin_district": "Westminster", "region": "London"}},
            ],
        }
        mocked_response = io.BytesIO(json.dumps(response_payload).encode("utf-8"))
        with patch("app.routers.website_discovery.urllib.request.urlopen", return_value=mocked_response):
            with TestClient(app) as client:
                result = client.post("/api/v1/website-discovery/branch-enrichment/postcodes")

        assert result.status_code == 200, result.text
        data = result.json()
        assert data["updated"] == 1
        assert data["not_applicable"] == 1
        db = session_factory()
        branches = {b.branch_name: b for b in db.query(Branch).all()}
        assert branches["Lancashire branch"].county == "Lancashire"
        assert branches["London branch"].county is None
        assert branches["Existing county branch"].county == "Existing County"
        assert db.query(AuditEvent).filter(AuditEvent.action == "postcode_county_lookup").count() == 2
        db.close()
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(engine)
        engine.dispose()
