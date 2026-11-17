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
    monkeypatch.setattr(overture_feed.settings, "geography_mode", "england")
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


def test_ons_england_geometry_fetches_all_pages_and_retains_authority_codes(monkeypatch):
    features = []
    for i in range(501):
        x = -5.0 + (i % 25) * 0.2
        y = 50.0 + (i // 25) * 0.1
        ring = [[x, y], [x + 0.1, y], [x + 0.1, y + 0.05], [x, y + 0.05], [x, y]]
        features.append({"properties": {"LAD25CD": f"E{i:05d}", "LAD25NM": f"Authority {i}"},
            "geometry": {"type": "Polygon", "coordinates": [ring]}})

    class Response:
        def __init__(self, payload): self.payload = payload
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return json.dumps(self.payload).encode()

    requested_offsets = []
    def fake_urlopen(request, **kwargs):
        url = request.full_url.lower()
        if "returncountonly=true" in url:
            return Response({"count": len(features)})
        offset = 500 if "resultoffset=500" in url else 0
        requested_offsets.append(offset)
        return Response({"features": features[offset:offset + 500], "exceededTransferLimit": False})

    monkeypatch.setattr(overture_feed.urllib.request, "urlopen", fake_urlopen)
    from app.overture_tasks import _fetch_ons_england_geometry, _inside_boundary, _authority_codes_for_point
    geometry = _fetch_ons_england_geometry()
    assert requested_offsets == [0, 500]
    assert geometry["type"] == "MultiPolygon"
    assert len(geometry["coordinates"]) == 501
    assert geometry["ons_feature_count"] == 501
    assert _inside_boundary(geometry, -4.95, 50.025) is True
    assert _authority_codes_for_point(geometry, -4.95, 50.025) == ["E00000"]


def test_ons_england_geometry_fails_closed_when_pages_do_not_match_count(monkeypatch):
    ring = [[-1, 51], [0, 51], [0, 52], [-1, 52], [-1, 51]]
    features = [{"properties": {"LAD25CD": f"E{i:05d}", "LAD25NM": "Authority"},
        "geometry": {"type": "Polygon", "coordinates": [ring]}} for i in range(300)]

    class Response:
        def __init__(self, payload): self.payload = payload
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return json.dumps(self.payload).encode()

    def fake_urlopen(request, **kwargs):
        url = request.full_url.lower()
        if "returncountonly=true" in url:
            return Response({"count": 301})
        if "resultoffset=300" in url:
            return Response({"features": [], "exceededTransferLimit": False})
        return Response({"features": features, "exceededTransferLimit": False})

    monkeypatch.setattr(overture_feed.urllib.request, "urlopen", fake_urlopen)
    from app.overture_tasks import _fetch_ons_england_geometry
    try:
        _fetch_ons_england_geometry()
        assert False, "Expected incomplete ONS response to fail closed"
    except RuntimeError as exc:
        assert "pagination" in str(exc).lower() or "feature count" in str(exc).lower()


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
    monkeypatch.setattr(overture_feed.settings, "geography_mode", "england")
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


def test_scheduled_run_resumes_existing_celery_delivery(monkeypatch):
    engine, factory = _session_factory()
    db = factory()
    original = OvertureImportRun(status="running", source_release="2026-11-11.0",
        outcomes={"_meta": {"ingestion_method": "scheduled_parquet", "geography_scope": "england"}},
        created_at=datetime.now(timezone.utc))
    db.add(original); db.commit(); db.refresh(original)
    run_id = original.id
    run, resumed = overture_feed._scheduled_run_for_task(db, "2026-11-11.0", "celery-task-123")
    assert resumed is True
    assert run.id == run_id
    assert run.celery_task_id == "celery-task-123"
    db.commit()
    run_again, resumed_again = overture_feed._scheduled_run_for_task(db, "2026-11-11.0", "celery-task-123")
    assert resumed_again is True
    assert run_again.id == run_id
    db.close(); engine.dispose()


def test_failed_scheduled_run_is_reopened_for_same_task_id():
    engine, factory = _session_factory()
    db = factory()
    original = OvertureImportRun(status="failed", source_release="2026-11-11.0",
        celery_task_id="celery-task-456", error_message="transient", completed_at=datetime.now(timezone.utc),
        outcomes={"_meta": {"ingestion_method": "scheduled_parquet", "geography_scope": "england"}},
        created_at=datetime.now(timezone.utc))
    db.add(original); db.commit(); db.refresh(original)
    run_id = original.id
    run, resumed = overture_feed._scheduled_run_for_task(db, "2026-11-11.0", "celery-task-456")
    assert resumed is True
    assert run.id == run_id
    assert run.status == "running"
    assert run.error_message is None
    assert run.completed_at is None
    db.close(); engine.dispose()


def test_discovery_sql_uses_native_geometry_and_avoids_taxonomy_json_cast():
    assert "ST_X(geometry)" in overture_feed.DISCOVERY_SQL
    assert "ST_Y(geometry)" in overture_feed.DISCOVERY_SQL
    assert "ST_GeomFromWKB" not in overture_feed.DISCOVERY_SQL
    assert "to_json(taxonomy)" not in overture_feed.DISCOVERY_SQL


def test_local_authority_feed_ingests_only_selected_authority(monkeypatch):
    engine, factory = _session_factory()
    monkeypatch.setattr(overture_feed, "SessionLocal", factory)
    monkeypatch.setattr(overture_feed, "_get_latest_release", lambda: "2026-11-12.0")
    ring_basildon = [[0, 50], [1, 50], [1, 52], [0, 52], [0, 50]]
    ring_havering = [[1, 50], [2, 50], [2, 52], [1, 52], [1, 50]]
    geometry = {"type": "MultiPolygon", "coordinates": [[ring_basildon], [ring_havering]],
                "authority_codes": ["E07000066", "E09000016"],
                "authority_names": ["Basildon", "Havering"], "ons_feature_count": 2}
    monkeypatch.setattr(overture_feed, "_fetch_ons_england_geometry", lambda: geometry)
    records = [
        {"gers_id": "basildon", "name": "Basildon Funeral Directors", "longitude": 0.5, "latitude": 51},
        {"gers_id": "havering", "name": "Havering Funeral Directors", "longitude": 1.5, "latitude": 51},
        {"gers_id": "outside", "name": "Outside Funeral Directors", "longitude": 3.0, "latitude": 51},
    ]
    monkeypatch.setattr(overture_feed, "_query_latest_places", lambda release: iter([records]))
    captured = []
    monkeypatch.setattr(overture_feed.import_overture_records, "run",
        lambda run_id, rows, release, finalize=False: captured.extend(rows))
    from app import overture_tasks
    monkeypatch.setattr(overture_tasks.process_overture_candidates, "delay", lambda *a, **k: None)
    monkeypatch.setattr(overture_feed.settings, "overture_feed_enabled", True)
    monkeypatch.setattr(overture_feed.settings, "overture_auto_process", False)
    monkeypatch.setattr(overture_feed.settings, "geography_mode", "local_authorities")
    monkeypatch.setattr(overture_feed.settings, "geography_authorities", "basildon")

    result = overture_feed.poll_latest_overture_release.run()

    assert result["status"] == "imported"
    assert [row["gers_id"] for row in captured] == ["basildon"]
    assert captured[0]["geography_scope"] == "basildon"
    db = factory()
    run = db.query(OvertureImportRun).one()
    meta = run.outcomes["_meta"]
    assert meta["geography_mode"] == "local_authorities"
    assert meta["geography_authorities"] == ["basildon"]
    db.close(); engine.dispose()


def test_fetches_exact_local_authority_by_lad_code(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self):
            return json.dumps({"features": [{"properties": {"LAD25CD": "E07000066", "LAD25NM": "Basildon"},
                "geometry": {"type": "Polygon", "coordinates": [[[-0.6, 51.5], [0.6, 51.5], [0.6, 52], [-0.6, 52], [-0.6, 51.5]]]}}]}).encode()

    requested = []
    def fake_urlopen(request, **kwargs):
        requested.append(request.full_url)
        return Response()

    monkeypatch.setattr(overture_feed.urllib.request, "urlopen", fake_urlopen)
    from app.overture_tasks import _fetch_ons_authority_geometry
    geometry = _fetch_ons_authority_geometry("E07000066")
    assert geometry["authority_codes"] == ["E07000066"]
    assert geometry["authority_names"] == ["Basildon"]
    assert "LAD25CD%3D%27E07000066%27" in requested[0] or "LAD25CD%3D%27E07000066%27" in requested[0].upper()


def test_scheduled_runs_are_separate_for_different_geographic_scopes():
    engine, factory = _session_factory()
    db = factory()
    original = OvertureImportRun(status="completed", source_release="2026-11-12.0",
        outcomes={"_meta": {"ingestion_method": "scheduled_parquet", "geography_scope": "england", "geography_key": "england"}},
        created_at=datetime.now(timezone.utc))
    db.add(original); db.commit()
    local_run, resumed = overture_feed._scheduled_run_for_task(db, "2026-11-12.0", None, "basildon")
    assert resumed is False
    assert local_run.id != original.id
    assert local_run.outcomes["_meta"]["geography_key"] == "basildon"
    db.close(); engine.dispose()
