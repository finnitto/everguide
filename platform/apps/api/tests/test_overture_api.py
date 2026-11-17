from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base, get_db
from app.identity_review_auth import require_identity_reviewer
from app.main import app
from app.models import OvertureImportRun
from app.overture_tasks import import_overture_records


def test_overture_import_endpoint_queues_and_reports_run(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_identity_reviewer] = lambda: "test-reviewer"
    monkeypatch.setattr(import_overture_records, "delay", lambda *a, **k: type("Task", (), {"id": "queued-task"})())
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/overture/imports", json={
                "source_release": "2026-10-15",
                "records": [{"gers_id": "api-gers-1", "name": "API Funeral Directors"}],
            })
            assert response.status_code == 202, response.text
            payload = response.json()
            assert payload["status"] == "queued"
            assert payload["records_received"] == 1
            assert client.get("/api/v1/overture/status").json()["candidate_count"] == 0
            assert client.get("/api/v1/overture/imports").json()["items"][0]["id"] == payload["id"]
            invalid = client.post("/api/v1/overture/imports", json={"records": [{"name": "No GERS"}]})
            assert invalid.status_code == 400
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_identity_reviewer, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_overture_feed_check_endpoint_queues_latest_release_check(monkeypatch):
    from app.routers import overture as overture_router
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_identity_reviewer] = lambda: "test-reviewer"
    monkeypatch.setattr(overture_router.settings, "overture_feed_enabled", True)
    monkeypatch.setattr(overture_router.poll_latest_overture_release, "delay",
        lambda *a, **k: type("Task", (), {"id": "feed-check-task"})())
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/overture/feed/check")
            assert response.status_code == 202, response.text
            assert response.json()["task_id"] == "feed-check-task"
            status = client.get("/api/v1/overture/status").json()
            assert status["feed_enabled"] is True
            assert status["feed_schedule"].startswith("Daily at")
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_identity_reviewer, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_manual_feed_check_remains_available_when_scheduling_is_disabled(monkeypatch):
    from app.routers import overture as overture_router
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_identity_reviewer] = lambda: "test-reviewer"
    monkeypatch.setattr(overture_router.settings, "overture_feed_enabled", True)
    monkeypatch.setattr(overture_router.settings, "overture_scheduled_tasks_enabled", False)
    monkeypatch.setattr(overture_router.poll_latest_overture_release, "delay",
        lambda *a, **k: type("Task", (), {"id": "manual-feed-check"})())
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/overture/feed/check")
            assert response.status_code == 202, response.text
            assert response.json()["task_id"] == "manual-feed-check"
            status = client.get("/api/v1/overture/status").json()
            assert status["feed_enabled"] is True
            assert status["scheduled_tasks_enabled"] is False
            assert status["feed_schedule_enabled"] is False
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(require_identity_reviewer, None)
        Base.metadata.drop_all(engine)
        engine.dispose()
