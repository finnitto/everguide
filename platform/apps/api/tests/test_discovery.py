from fastapi.testclient import TestClient
from app.main import app
from app.config import settings

def test_discovery_status_requires_reviewer_authentication(monkeypatch):
    monkeypatch.setattr(settings, "google_places_api_key", "")
    response = TestClient(app).get("/api/v1/discovery/status")
    assert response.status_code == 401

def test_discovery_is_disabled_by_overture_first_policy(monkeypatch):
    monkeypatch.setattr(settings, "google_places_api_key", "test-key")
    response = TestClient(app).post("/api/v1/discovery/runs")
    assert response.status_code == 410
    assert "Overture" in response.json()["detail"]


def test_independent_discovery_endpoints_return_gone():
    client = TestClient(app)
    endpoints = [
        "/api/v1/discovery/runs",
        "/api/v1/companies-house/runs",
        "/api/v1/companies-house/profiles/enrich",
        "/api/v1/company-websites/runs",
        "/api/v1/company-websites/runs/123/resume",
        "/api/v1/website-discovery/runs",
        "/api/v1/website-discovery/verification-runs",
    ]

    for endpoint in endpoints:
        response = client.post(endpoint)
        assert response.status_code == 410, (
            f"{endpoint} returned {response.status_code}: {response.text}"
        )
