from fastapi.testclient import TestClient
from app.main import app
from app.config import settings

def test_discovery_status_reports_missing_key(monkeypatch):
    monkeypatch.setattr(settings, "google_places_api_key", "")
    response = TestClient(app).get("/api/v1/discovery/status")
    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert response.json()["scope"] == "England"

def test_discovery_requires_google_api_key(monkeypatch):
    monkeypatch.setattr(settings, "google_places_api_key", "")
    response = TestClient(app).post("/api/v1/discovery/runs")
    assert response.status_code == 400
    assert "GOOGLE_PLACES_API_KEY" in response.json()["detail"]
