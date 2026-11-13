import io
import json
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AuditEvent, OvertureImportRun
from app import overture_feed


def _session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_latest_release_is_read_from_stac(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return json.dumps({"latest": "2026-10-21.0"}).encode()
    monkeypatch.setattr(overture_feed.urllib.request, "urlopen", lambda *a, **k: Response())
    assert overture_feed._get_latest_release() == "2026-10-21.0"


def test_latest_release_rejects_unexpected_catalogue_value(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return b'{"latest":"not-a-release"}'
    monkeypatch.setattr(overture_feed.urllib.request, "urlopen", lambda *a, **k: Response())
    try:
        overture_feed._get_latest_release()
        assert False, "Expected invalid STAC release to fail closed"
    except RuntimeError as exc:
        assert "valid latest release" in str(exc)


def test_normalise_record_retains_gers_and_contributor_provenance():
    row = (
        "gers-123", "Example Funeral Directors", "family_service", "funeral_service", "0.91",
        json.dumps([{"freeform": "1 High Street", "postcode": "RM18 7QX", "country": "GB"}]),
        json.dumps(["01375 123456"]), json.dumps([{"value": "https://example.org"}]),
        json.dumps([{"provider": "microsoft", "record_id": "abc", "license": "CDLA-Permissive-2.0"}]),
        0.36, 51.46,
    )
    result = overture_feed._normalise_record(row)
    assert result["gers_id"] == "gers-123"
    assert result["postcode"] == "RM18 7QX"
    assert result["website"] == "https://example.org"
    assert result["sources_json"][0]["record_id"] == "abc"
    assert result["geography_scope"] == "england"


def test_poll_skips_release_already_ingested(monkeypatch):
    engine, factory = _session_factory()
    monkeypatch.setattr(overture_feed, "SessionLocal", factory)
    monkeypatch.setattr(overture_feed, "_get_latest_release", lambda: "2026-10-21.0")
    monkeypatch.setattr(overture_feed.settings, "overture_feed_enabled", True)
    db = factory()
    db.add(OvertureImportRun(status="completed", source_release="2026-10-21.0",
        outcomes={"_meta": {"ingestion_method": "scheduled_parquet", "geography_scope": "england"}},
        created_at=datetime.now(timezone.utc)))
    db.commit(); db.close()
    result = overture_feed.poll_latest_overture_release.run()
    assert result == {"status": "no_new_release", "latest_release": "2026-10-21.0"}
    db = factory()
    event = db.query(AuditEvent).filter_by(action="latest_release_unchanged").one()
    assert event.detail["latest_release"] == "2026-10-21.0"
    db.close(); engine.dispose()


def test_ons_england_geometry_combines_valid_english_authority_polygons(monkeypatch):
    ring = [[-1.0, 51.0], [0.0, 51.0], [0.0, 52.0], [-1.0, 52.0], [-1.0, 51.0]]
    features = [{"properties": {"CTYUA25CD": f"E{i:05d}"},
        "geometry": {"type": "Polygon", "coordinates": [ring]}} for i in range(100)]
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return json.dumps({"features": features}).encode()
    monkeypatch.setattr(overture_feed.urllib.request, "urlopen", lambda *a, **k: Response())
    from app.overture_tasks import _fetch_ons_england_geometry, _inside_boundary
    geometry = _fetch_ons_england_geometry()
    assert geometry["type"] == "MultiPolygon"
    assert len(geometry["coordinates"]) == 100
    assert _inside_boundary(geometry, -0.5, 51.5) is True


def test_new_release_ingests_only_points_inside_ons_england(monkeypatch):
    engine, factory = _session_factory()
    monkeypatch.setattr(overture_feed, "SessionLocal", factory)
    monkeypatch.setattr(overture_feed, "_get_latest_release", lambda: "2026-11-11.0")
    monkeypatch.setattr(overture_feed, "_fetch_ons_england_geometry", lambda: {
        "type": "Polygon", "coordinates": [[[-1, 50], [1, 50], [1, 53], [-1, 53], [-1, 50]]]
    })
    inside = {"gers_id": "inside", "name": "Inside Funeral Directors", "longitude": 0, "latitude": 51}
    outside = {"gers_id": "outside", "name": "Outside Funeral Directors", "longitude": 10, "latitude": 51}
    monkeypatch.setattr(overture_feed, "_query_latest_places", lambda release: iter([[inside, outside]]))
    captured = []
    monkeypatch.setattr(overture_feed.import_overture_records, "run",
        lambda run_id, records, release, finalize=False: captured.extend(records))
    from app import overture_tasks
    monkeypatch.setattr(overture_tasks.process_overture_candidates, "delay", lambda *a, **k: None)
    monkeypatch.setattr(overture_feed.settings, "overture_feed_enabled", True)
    monkeypatch.setattr(overture_feed.settings, "overture_auto_process", True)
    result = overture_feed.poll_latest_overture_release.run()
    assert result["status"] == "imported"
    assert result["records_discovered"] == 1
    assert [row["gers_id"] for row in captured] == ["inside"]
    assert captured[0]["source_release"] == "2026-11-11.0"
    db = factory()
    run = db.query(OvertureImportRun).one()
    assert run.source_release == "2026-11-11.0"
    assert run.status == "imported"
    assert db.query(AuditEvent).filter_by(action="release_ingestion_completed").count() == 1
    db.close(); engine.dispose()
