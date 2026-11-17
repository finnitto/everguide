import hashlib
import json

from fastapi.testclient import TestClient

from app.config import settings
from app.identity_review_auth import require_identity_reviewer
from app.main import app


def test_active_administrative_mutations_require_reviewer_credentials():
    requests = [
        ("patch", "/api/v1/providers/1/status?status=suspended", None),
        ("post", "/api/v1/companies-house/classification/run", None),
        ("post", "/api/v1/website-discovery/quality-assessments", None),
        ("post", "/api/v1/website-discovery/quality-assessments/reassess", None),
        ("post", "/api/v1/website-discovery/quality-actions/seed", None),
        ("post", "/api/v1/website-discovery/branch-enrichment/postcodes", None),
        ("post", "/api/v1/observations", {"source_name": "Unauthenticated test observation"}),
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


def test_disabled_legacy_admin_mutations_also_require_reviewer_authentication():
    requests = [
        ("/api/v1/providers", {"trading_name": "Unauthorised provider"}),
        ("/api/v1/providers/1/branches", {
            "branch_name": "Unauthorised branch",
            "address_line_1": "1 High Street",
            "town_city": "York",
            "postcode": "YO1 1AA",
        }),
        ("/api/v1/companies-house/runs", None),
        ("/api/v1/companies-house/profiles/enrich", None),
        ("/api/v1/company-websites/runs", None),
        ("/api/v1/company-websites/runs/1/resume", None),
        ("/api/v1/discovery/runs", None),
        ("/api/v1/website-discovery/runs", None),
        ("/api/v1/website-discovery/verification-runs", None),
    ]
    with TestClient(app) as client:
        for path, payload in requests:
            response = client.post(path, json=payload) if payload is not None else client.post(path)
            assert response.status_code == 401, f"POST {path}: {response.status_code} {response.text}"


def test_internal_router_accepts_valid_reviewer_credential(monkeypatch):
    token = "stage4-route-matrix-reviewer-token"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    monkeypatch.setattr(settings, "identity_review_credentials", json.dumps({"stage4-reviewer": digest}))
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/discovery/status",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200, response.text


def test_health_and_api_root_remain_public():
    with TestClient(app) as client:
        health = client.get("/health")
        api_root = client.get("/api/v1")
    assert health.status_code == 200, health.text
    assert api_root.status_code == 200, api_root.text



def _has_reviewer_dependency(dependant):
    if getattr(dependant, "call", None) is require_identity_reviewer:
        return True
    return any(_has_reviewer_dependency(child) for child in dependant.dependencies)


def test_every_internal_api_route_has_reviewer_dependency_except_public_directory_search():
    missing = []
    for route in app.routes:
        path = getattr(route, "path", "")
        dependant = getattr(route, "dependant", None)
        if not dependant or not path.startswith("/api/v1/"):
            continue
        if path == "/api/v1/directory/search":
            continue
        if not _has_reviewer_dependency(dependant):
            missing.append(path)
    assert missing == [], f"Internal API routes without reviewer auth: {missing}"
