from fastapi.testclient import TestClient

from app.main import app


def test_active_administrative_mutations_require_reviewer_credentials():
    requests = [
        ("patch", "/api/v1/providers/1/status?status=suspended", None),
        ("post", "/api/v1/companies-house/classification/run", None),
        ("post", "/api/v1/website-discovery/quality-assessments", None),
        ("post", "/api/v1/website-discovery/quality-assessments/reassess", None),
        ("post", "/api/v1/website-discovery/quality-actions/seed", None),
        ("post", "/api/v1/website-discovery/branch-enrichment/postcodes", None),
    ]

    with TestClient(app) as client:
        for method, path, payload in requests:
            response = getattr(client, method)(path, json=payload) if payload is not None else getattr(client, method)(path)
            assert response.status_code == 401, f"{method.upper()} {path}: {response.status_code} {response.text}"


def test_provider_and_observation_edits_require_reviewer_credentials():
    with TestClient(app) as client:
        provider = client.patch("/api/v1/providers/1", json={"trading_name": "Changed Name"})
        observation = client.patch("/api/v1/observations/1", json={"review_status": "accepted"})

    assert provider.status_code == 401, provider.text
    assert observation.status_code == 401, observation.text


def test_quality_action_decision_requires_reviewer_credentials():
    with TestClient(app) as client:
        response = client.post("/api/v1/website-discovery/quality-actions/1/decide", json={"decision": "reject"})

    assert response.status_code == 401, response.text



def test_administrative_read_endpoints_require_reviewer_credentials():
    paths = [
        "/api/v1/dashboard",
        "/api/v1/providers",
        "/api/v1/providers/1",
        "/api/v1/observations",
        "/api/v1/matching/summary",
        "/api/v1/matching/queue",
        "/api/v1/companies-house/status",
        "/api/v1/companies-house/runs",
        "/api/v1/companies-house/candidates",
        "/api/v1/companies-house/profiles/summary",
        "/api/v1/companies-house/classification/summary",
        "/api/v1/company-websites/status",
        "/api/v1/company-websites/runs",
        "/api/v1/company-websites/candidates",
        "/api/v1/discovery/status",
        "/api/v1/discovery/runs",
        "/api/v1/discovery/observations",
        "/api/v1/website-discovery/status",
        "/api/v1/website-discovery/verification-runs",
        "/api/v1/website-discovery/identity-review",
        "/api/v1/website-discovery/quality-actions",
        "/api/v1/website-discovery/analytics",
        "/api/v1/website-discovery/candidates",
        "/api/v1/overture/status",
        "/api/v1/overture/imports",
        "/api/v1/overture/candidates",
        "/api/v1/identity-review/summary",
        "/api/v1/identity-review/overture-links",
        "/api/v1/identity-review/identities",
        "/api/v1/identity-review/branches",
    ]

    with TestClient(app) as client:
        for path in paths:
            response = client.get(path)
            assert response.status_code == 401, f"GET {path}: {response.status_code} {response.text}"
