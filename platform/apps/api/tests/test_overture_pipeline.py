import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import OvertureCandidate, Provider, Branch, SourceObservation, AuditEvent
from app import overture_tasks


def _session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _candidate_row():
    return {
        "gers_id": "gers-test-001", "version": "2026-10-15",
        "name": "Test Funeral Directors", "basic_category": "family_service",
        "taxonomy_primary": "funeral_service", "confidence": "0.99",
        "address": "1 High Street", "postcode": "RM18 7QX", "phone": "01375 856903",
        "website": "https://test-funerals.example/", "latitude": "1", "longitude": "1",
        "sources_json": [{"dataset": "Microsoft", "provider": "microsoft", "record_id": "source-1", "license": "CDLA-Permissive-2.0"}],
        "possible_duplicate": "False",
    }


def test_import_persists_overture_provenance_and_is_idempotent(monkeypatch):
    engine, factory = _session_factory()
    monkeypatch.setattr(overture_tasks, "SessionLocal", factory)
    monkeypatch.setattr(overture_tasks.process_overture_candidates, "delay", lambda *a, **k: None)
    from app.models import OvertureImportRun
    db = factory()
    run = OvertureImportRun(status="queued")
    db.add(run); db.commit(); run_id = run.id; db.close()
    result = overture_tasks.import_overture_records.run(run_id, [_candidate_row()], "2026-10-15")
    assert result["imported"] == 1
    db = factory()
    candidate = db.query(OvertureCandidate).one()
    observation = db.get(SourceObservation, candidate.source_observation_id)
    assert candidate.gers_id == "gers-test-001"
    assert observation.observed_data["sources"][0]["record_id"] == "source-1"
    assert observation.observed_data["confidence_semantics"].startswith("place_existence")
    assert db.query(AuditEvent).filter_by(action="source_observation_imported").count() == 1
    db.close(); engine.dispose()


def test_pipeline_publishes_only_when_independent_evidence_and_boundary_pass(monkeypatch):
    engine, factory = _session_factory()
    monkeypatch.setattr(overture_tasks, "SessionLocal", factory)
    monkeypatch.setattr(overture_tasks, "_fetch_ons_geometry", lambda: {
        "type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]
    })
    monkeypatch.setattr(overture_tasks, "verify_candidate", lambda url: {
        "status": "reachable", "final_url": url, "robots_allowed": True,
        "page_title": "Test Funeral Directors", "content_sha256": "a" * 64,
        "extracted_data": {"name": "Test Funeral Directors", "street": "1 High Street",
            "town": "Tilbury", "postcode": "RM18 7QX", "telephone": "01375 856903",
            "email": None, "website": url, "source_type": "schema_org_funeralhome",
            "country": "gb", "confidence": 0.97, "funeral_signals": ["funeral directors"],
            "has_complete_branch_address": True},
    })
    db = factory()
    candidate = OvertureCandidate(gers_id="gers-test-002", candidate_name="Test Funeral Directors",
        postcode="RM18 7QX", raw_data=_candidate_row(), outcome="awaiting_enrichment", status="awaiting_enrichment")
    db.add(candidate); db.flush()
    obs = SourceObservation(source_type="overture_places", source_name="Overture Places",
        observed_data={"gers_id": candidate.gers_id}, review_status="pending")
    db.add(obs); db.flush(); candidate.source_observation_id = obs.id
    db.commit(); candidate_id = candidate.id; db.close()

    result = overture_tasks.process_overture_candidates.run(None, 250)
    assert result["outcomes"] == {"auto_approved_published": 1}
    db = factory()
    candidate = db.get(OvertureCandidate, candidate_id)
    assert candidate.outcome == "auto_approved_published"
    provider = db.get(Provider, candidate.provider_id)
    branch = db.get(Branch, candidate.branch_id)
    assert provider.status == "published" and provider.verification_status == "approved"
    assert branch.status == "published" and branch.postcode == "RM18 7QX"
    assert db.query(SourceObservation).filter_by(source_type="provider_owned_website_structured_data", review_status="accepted").count() == 1
    assert db.query(AuditEvent).filter_by(entity_type="provider", action="auto_approved_published").count() == 1
    db.close(); engine.dispose()


def test_pipeline_fails_closed_when_official_boundary_unavailable(monkeypatch):
    engine, factory = _session_factory()
    monkeypatch.setattr(overture_tasks, "SessionLocal", factory)
    monkeypatch.setattr(overture_tasks, "_fetch_ons_geometry", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(overture_tasks, "verify_candidate", lambda url: {
        "status": "reachable", "final_url": url, "robots_allowed": True,
        "extracted_data": {"name": "Test Funeral Directors", "street": "1 High Street",
            "town": "Tilbury", "postcode": "RM18 7QX", "telephone": "01375 856903",
            "website": url, "confidence": 0.99, "funeral_signals": ["funeral directors"],
            "has_complete_branch_address": True},
    })
    db = factory()
    candidate = OvertureCandidate(gers_id="gers-test-003", candidate_name="Test Funeral Directors",
        postcode="RM18 7QX", raw_data=_candidate_row(), outcome="awaiting_enrichment", status="awaiting_enrichment")
    db.add(candidate); db.commit(); candidate_id = candidate.id; db.close()
    result = overture_tasks.process_overture_candidates.run(None, 250)
    assert result["boundary_verified"] is False
    db = factory()
    candidate = db.get(OvertureCandidate, candidate_id)
    assert candidate.provider_id is None
    assert candidate.outcome == "awaiting_enrichment"
    assert "official_thurrock_boundary_not_confirmed" in candidate.assessment["reasons"]
    assert db.query(Provider).count() == 0
    db.close(); engine.dispose()


def test_point_in_boundary_respects_holes_and_outside_points():
    polygon = [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]], [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]]
    geometry = {"type": "Polygon", "coordinates": polygon}
    assert overture_tasks._inside_boundary(geometry, 0.5, 0.5) is True
    assert overture_tasks._inside_boundary(geometry, 2, 2) is False
    assert overture_tasks._inside_boundary(geometry, 8, 8) is False


def test_existing_same_parent_provider_accepts_new_distinct_branch(monkeypatch):
    engine, factory = _session_factory()
    db = factory()
    provider = Provider(trading_name="Test Funeral Directors", website="https://test-funerals.example", status="published")
    provider.branches.append(Branch(branch_name="Tilbury", address_line_1="1 High Street", town_city="Tilbury",
        postcode="RM18 7QX", telephone="01375 856903", status="published"))
    db.add(provider); db.commit()
    conflict, matched = overture_tasks._existing_provider_match(db, {
        "name": "Test Funeral Directors", "website": "https://test-funerals.example/branch-two",
        "postcode": "RM16 2YJ", "phone": "01375 856903"})
    assert conflict is False
    assert matched.id == provider.id
    conflict, matched = overture_tasks._existing_provider_match(db, {
        "name": "Test Funeral Directors", "website": "https://test-funerals.example/branch-two",
        "postcode": "RM18 7QX", "phone": "01375 856903"})
    assert conflict is True and matched is None
    db.close(); engine.dispose()


def test_england_scope_does_not_apply_thurrock_postcode_filter():
    from app.overture_approval import assess_overture_candidate
    row = _candidate_row()
    row["postcode"] = "SW1A 1AA"
    result = assess_overture_candidate(row, point_in_england=True, geography_scope="england",
        auto_approval_enabled=False, minimum_confidence=0.94)
    assert "postcode_outside_thurrock_area" not in result["reasons"]
    assert "official_england_boundary_not_confirmed" not in result["reasons"]
