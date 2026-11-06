from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base, get_db
from app.main import app
from app import models  # noqa: F401


def test_provider_branch_publish_and_observation():
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
    try:
        with TestClient(app) as client:
            created = client.post("/api/v1/providers", json={
                "trading_name": "Example Funeral Care",
                "branches": [{
                    "branch_name": "Example Funeral Care York",
                    "address_line_1": "1 High Street",
                    "town_city": "York",
                    "postcode": "YO1 1AA",
                }],
            })
            assert created.status_code == 201
            provider = created.json()
            assert provider["branches"][0]["status"] == "draft"

            assert client.get("/api/v1/directory/search?q=York").json()["count"] == 0
            published = client.patch(f"/api/v1/providers/{provider['id']}/status?status=published")
            assert published.status_code == 200
            public_results = client.get("/api/v1/directory/search?q=York").json()
            assert public_results["count"] == 1

            observation = client.post("/api/v1/observations", json={
                "provider_id": provider["id"],
                "source_type": "manual",
                "source_name": "Example source",
                "confidence": 0.9,
                "observed_data": {"telephone": "01234 567890"},
            })
            assert observation.status_code == 201
            assert observation.json()["review_status"] == "pending"
            assert client.get("/api/v1/dashboard").json()["observations_pending"] == 1

            matchable = client.post("/api/v1/observations", json={
                "source_type": "manual", "source_name": "Independent source",
                "observed_data": {"name": "Example Funeral Care", "postcode": "YO1 1AA"}
            })
            assert matchable.status_code == 201
            queue = client.get("/api/v1/matching/queue")
            assert queue.status_code == 200
            suggested = next(item for item in queue.json()["items"] if item["id"] == matchable.json()["id"])
            assert suggested["match_state"] == "strong_candidate"
            linked = client.patch(f"/api/v1/observations/{matchable.json()['id']}", json={
                "review_status": "accepted", "provider_id": provider["id"],
                "branch_id": provider["branches"][0]["id"]
            })
            assert linked.status_code == 200
            assert linked.json()["provider_id"] == provider["id"]
            assert linked.json()["branch_id"] == provider["branches"][0]["id"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(engine)
        engine.dispose()
