import json
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import OvertureCandidate, Provider, Branch, SourceObservation, AuditEvent
from app import overture_tasks


@pytest.fixture(autouse=True)
def isolate_celery_dispatch(monkeypatch):
    monkeypatch.setattr(overture_tasks, "dispatch_queued_price_enrichment", lambda *args, **kwargs: 0)
    monkeypatch.setattr(overture_tasks.process_overture_candidates, "delay", lambda *args, **kwargs: None)


def _session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _candidate_row():
    return {
        "gers_id": "gers-test-001", "version": "2026-10-15",
        "name": "Test Funeral Directors", "basic_category": "family_service",
        "taxonomy_primary": "funeral_service", "confidence": "0.99",
        "address": "1 High Street", "address_line_1": "1 High Street", "town_city": "Tilbury", "postcode": "RM18 7QX", "phone": "01375 856903",
        "website": "https://test-funerals.example/", "latitude": "1", "longitude": "1",
        "sources_json": [{"dataset": "Microsoft", "provider": "microsoft", "record_id": "source-1", "license": "CDLA-Permissive-2.0"}],
        "possible_duplicate": "False",
    }


def test_website_postcode_conflict_requires_same_branch_address_and_verified_first_party_source():
    raw = overture_tasks._normalised_assessment_row(_candidate_row())
    mismatch = {
        "name": "Test Funeral Directors",
        "street": "1 High Street",
        "town": "Tilbury",
        "postcode": "RM17 5LS",
        "has_complete_branch_address": True,
    }
    assert overture_tasks._first_party_website_conflicts(
        raw, mismatch, verified_first_party=True
    ) == ["official_site_branch_postcode_mismatch"]

    # A different branch on the same provider website is not this branch's conflict.
    other_branch = {**mismatch, "street": "2 Station Road"}
    assert overture_tasks._first_party_website_conflicts(
        raw, other_branch, verified_first_party=True
    ) == []

    different_locality = {**mismatch, "town": "Grays"}
    assert overture_tasks._first_party_website_conflicts(
        raw, different_locality, verified_first_party=True
    ) == []

    # Inaccessible/robots-blocked pages cannot provide official conflict evidence.
    closed = {**mismatch, "branch_status": "closed"}
    assert overture_tasks._first_party_website_conflicts(
        raw, closed, verified_first_party=False
    ) == []


def test_missing_website_postcode_is_unknown_when_name_matches():
    raw = overture_tasks._normalised_assessment_row(_candidate_row())
    # Name-only evidence remains insufficient for the stronger identity match
    # used by the publication gate.
    assert not overture_tasks._candidate_evidence_matches(raw, {"name": "Test Funeral Directors"})
    assert not overture_tasks._candidate_evidence_matches(raw, {
        "name": "Test Funeral Directors", "postcode": "RM17 5LS",
    })


def test_explicit_closure_requires_verified_first_party_evidence_for_same_branch():
    raw = overture_tasks._normalised_assessment_row(_candidate_row())
    closed = {
        "branch_status": "permanently_closed",
        "street": "1 High Street",
        "town": "Tilbury",
        "postcode": "RM18 7QX",
        "has_complete_branch_address": True,
    }
    assert overture_tasks._first_party_website_conflicts(
        raw, closed, verified_first_party=True
    ) == ["official_site_branch_closed"]

    other_branch = {**closed, "street": "2 Station Road"}
    assert overture_tasks._first_party_website_conflicts(
        raw, other_branch, verified_first_party=True
    ) == []
    assert overture_tasks._first_party_website_conflicts(
        raw, closed, verified_first_party=False
    ) == []


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


def test_pipeline_publishes_only_when_independent_evidence_and_boundary_pass(monkeypatch, tmp_path):
    engine, factory = _session_factory()
    monkeypatch.setattr(overture_tasks, "SessionLocal", factory)
    monkeypatch.setattr(overture_tasks, "ONS_BOUNDARY_CACHE_DIR", tmp_path)
    monkeypatch.setattr(overture_tasks.settings, "auto_approve_providers", True)
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
    pricing_enrichment = candidate.first_party_evidence["pricing_enrichment"]
    assert pricing_enrichment["status"] == "queued"
    assert pricing_enrichment["trigger"] == "automatic_approval"
    provider = db.get(Provider, candidate.provider_id)
    branch = db.get(Branch, candidate.branch_id)
    assert provider.status == "published" and provider.verification_status == "approved"
    assert branch.status == "published" and branch.postcode == "RM18 7QX"
    assert branch.address_line_1 == "1 High Street" and branch.town_city == "Tilbury"
    assert branch.latitude == 1.0 and branch.longitude == 1.0
    assert db.query(SourceObservation).filter_by(source_type="provider_owned_website_structured_data", review_status="accepted").count() == 1
    assert db.query(AuditEvent).filter_by(entity_type="provider", action="auto_approved_published").count() == 1
    db.close(); engine.dispose()


def test_overture_location_can_publish_without_a_website(monkeypatch, tmp_path):
    engine, factory = _session_factory()
    monkeypatch.setattr(overture_tasks, "SessionLocal", factory)
    monkeypatch.setattr(overture_tasks, "ONS_BOUNDARY_CACHE_DIR", tmp_path)
    monkeypatch.setattr(overture_tasks.settings, "auto_approve_providers", True)
    monkeypatch.setattr(overture_tasks, "_fetch_ons_geometry", lambda: {
        "type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]
    })
    db = factory()
    raw = _candidate_row()
    raw["website"] = ""
    candidate = OvertureCandidate(gers_id="gers-no-website", candidate_name="Test Funeral Directors",
        postcode="RM18 7QX", raw_data=raw, outcome="awaiting_enrichment", status="awaiting_enrichment")
    db.add(candidate); db.commit(); candidate_id = candidate.id; db.close()

    result = overture_tasks.process_overture_candidates.run(None, 20)
    assert result["outcomes"] == {"auto_approved_published": 1}
    db = factory()
    candidate = db.get(OvertureCandidate, candidate_id)
    branch = db.get(Branch, candidate.branch_id)
    provider = db.get(Provider, candidate.provider_id)
    assert provider.status == "published"
    assert provider.website is None
    assert branch.address_line_1 == "1 High Street"
    assert branch.town_city == "Tilbury"
    assert branch.postcode == "RM18 7QX"
    assert db.query(SourceObservation).filter_by(source_type="provider_owned_website_structured_data").count() == 0
    db.close(); engine.dispose()


def test_candidate_without_usable_overture_url_is_exception_for_enrichment(monkeypatch, tmp_path):
    engine, factory = _session_factory()
    monkeypatch.setattr(overture_tasks, "SessionLocal", factory)
    monkeypatch.setattr(overture_tasks, "ONS_BOUNDARY_CACHE_DIR", tmp_path)
    monkeypatch.setattr(overture_tasks.settings, "auto_approve_providers", False)
    monkeypatch.setattr(overture_tasks, "_fetch_ons_geometry", lambda: {
        "type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]
    })
    monkeypatch.setattr(overture_tasks.process_overture_candidates, "delay", lambda *a, **k: None)
    raw = _candidate_row()
    raw["website"] = ""
    raw["websites_json"] = []
    db = factory()
    candidate = OvertureCandidate(gers_id="gers-no-enrichment-url",
        candidate_name="Test Funeral Directors", postcode="RM18 7QX", raw_data=raw,
        outcome="awaiting_enrichment", status="awaiting_enrichment")
    db.add(candidate); db.commit(); candidate_id = candidate.id; db.close()

    result = overture_tasks.process_overture_candidates.run(None, 20)

    db = factory()
    candidate = db.get(OvertureCandidate, candidate_id)
    assert result["outcomes"] == {"exception_review": 1}
    assert candidate.status == candidate.outcome == "exception_review"
    assert "overture_first_party_website_unavailable" in candidate.assessment["reasons"]
    assert candidate.provider_id is None and candidate.branch_id is None
    db.close(); engine.dispose()


def test_manual_recheck_creates_one_tracked_run_for_waiting_and_url_bearing_exceptions(monkeypatch):
    from datetime import datetime, timezone
    from app.models import OvertureImportRun
    from app.routers.overture import queue_overture_processing

    engine, factory = _session_factory()
    dispatched = []
    monkeypatch.setattr(overture_tasks.process_overture_candidates, "delay",
        lambda *args: (dispatched.append(args) or type("Task", (), {"id": "task-full-run"})()))
    db = factory()
    checked_at = datetime.now(timezone.utc)
    candidates = [OvertureCandidate(
        gers_id=f"gers-recheck-{i}", candidate_name=f"Test Funeral Directors {i}",
        postcode="RM18 7QX", raw_data=_candidate_row(), outcome="awaiting_enrichment",
        status="awaiting_enrichment", last_checked_at=checked_at,
    ) for i in range(3)]
    url_exception = OvertureCandidate(
        gers_id="gers-url-exception", candidate_name="URL Exception Funeral Directors",
        postcode="RM18 7QX", raw_data=_candidate_row(), outcome="exception_review",
        status="exception_review", assessment={"outcome": "exception_review", "reasons": "automatic_approval_disabled"},
        last_checked_at=checked_at,
    )
    no_url_exception = OvertureCandidate(
        gers_id="gers-no-url-exception", candidate_name="No URL Exception Funeral Directors",
        postcode="RM18 7QX", raw_data={**_candidate_row(), "website": None}, outcome="exception_review",
        status="exception_review", assessment={"outcome": "exception_review", "reasons": "missing_site"},
        last_checked_at=checked_at,
    )
    candidates.extend([url_exception, no_url_exception])
    db.add_all(candidates); db.commit()

    result = queue_overture_processing(reviewer="reviewer-test", db=db)

    assert result["status"] == "queued"
    assert result["task_id"] == "task-full-run"
    assert result["candidates_queued"] == 4
    assert dispatched == [(result["run_id"], 20)]
    assert all(candidate.last_checked_at is None for candidate in candidates[:4])
    assert no_url_exception.last_checked_at == checked_at
    run = db.query(OvertureImportRun).filter_by(id=result["run_id"]).one()
    assert run.records_received == 4
    assert run.outcomes["_meta"]["candidate_ids"] == [candidate.id for candidate in candidates[:4]]
    assert db.query(AuditEvent).filter_by(action="full_overture_enrichment_run_queued").one().actor == "reviewer-test"

    repeated = queue_overture_processing(reviewer="reviewer-test", db=db)
    assert repeated["run_id"] == result["run_id"]
    assert len(dispatched) == 1
    from app.routers.overture import _run_dict
    candidates[0].last_checked_at = checked_at
    candidates[0].first_party_evidence = {"pricing_enrichment": {
        "overture_run_id": run.id, "status": "failed", "run_terminal_status": "failed",
    }}
    candidates[1].first_party_evidence = {"pricing_enrichment": {
        "overture_run_id": run.id, "status": "queued",
    }}
    run.records_processed = 0  # Batch-level counter has not committed yet.
    db.commit()
    progress = _run_dict(run, db)
    assert progress["progress"]["candidates_total"] == 4
    assert progress["progress"]["candidates_processed"] == 1
    assert progress["progress"]["prices_queued"] == 2
    assert progress["progress"]["prices_terminal"] == 1
    assert progress["progress"]["price_outcomes"] == {"failed": 1}
    assert "candidate_ids" not in progress["outcomes"]["_meta"]
    db.close(); engine.dispose()


def test_full_enrichment_run_rechecks_url_bearing_exception_without_import_provenance(monkeypatch, tmp_path):
    from app.models import OvertureImportRun
    engine, factory = _session_factory()
    monkeypatch.setattr(overture_tasks, "SessionLocal", factory)
    monkeypatch.setattr(overture_tasks, "ONS_BOUNDARY_CACHE_DIR", tmp_path)
    monkeypatch.setattr(overture_tasks.settings, "auto_approve_providers", False)
    monkeypatch.setattr(overture_tasks, "_fetch_ons_geometry", lambda: {
        "type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]
    })
    monkeypatch.setattr(overture_tasks, "verify_candidate", lambda url: {
        "status": "reachable", "final_url": url, "robots_allowed": True,
        "extracted_data": {"name": "Test Funeral Directors", "postcode": "RM18 7QX",
            "street": "1 High Street", "town": "Tilbury", "has_complete_branch_address": True},
    })
    db = factory()
    candidate = OvertureCandidate(gers_id="gers-full-run", candidate_name="Test Funeral Directors",
        postcode="RM18 7QX", raw_data=_candidate_row(), outcome="exception_review",
        status="exception_review", assessment={"outcome": "exception_review", "reasons": "automatic_approval_disabled"},
        last_checked_at=None)
    db.add(candidate); db.flush()
    run = OvertureImportRun(status="queued", records_received=1, outcomes={"_meta": {
        "ingestion_method": "manual_enrichment_retry", "run_type": "enrichment_retry",
        "candidate_ids": [candidate.id], "target_count": 1,
        "pricing_enrichment_queued": 0, "pricing_enrichment_terminal": 0,
        "pricing_enrichment_outcomes": {},
    }})
    db.add(run); db.commit(); candidate_id = candidate.id; run_id = run.id; db.close()

    result = overture_tasks.process_overture_candidates.run(run_id, 20)

    db = factory()
    candidate = db.get(OvertureCandidate, candidate_id)
    run = db.get(OvertureImportRun, run_id)
    meta = run.outcomes["_meta"]
    assert result["records_processed"] == 1
    assert candidate.outcome == "enrichment_approved"
    assert candidate.last_import_run_id is None
    assert candidate.first_party_evidence["pricing_enrichment"]["overture_run_id"] == run_id
    assert run.records_processed == 1
    assert run.status == "price_enrichment"
    assert meta["pricing_enrichment_queued"] == 1
    assert meta["pricing_enrichment_terminal"] == 0
    db.close(); engine.dispose()


def test_publication_write_gate_blocks_even_if_assessor_returns_eligible_when_disabled(monkeypatch, tmp_path):
    engine, factory = _session_factory()
    monkeypatch.setattr(overture_tasks, "SessionLocal", factory)
    monkeypatch.setattr(overture_tasks, "ONS_BOUNDARY_CACHE_DIR", tmp_path)
    monkeypatch.setattr(overture_tasks.settings, "auto_approve_providers", False)
    monkeypatch.setattr(overture_tasks, "dispatch_queued_price_enrichment", lambda *a, **k: 0)
    monkeypatch.setattr(overture_tasks, "_fetch_ons_geometry", lambda: {
        "type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]
    })
    monkeypatch.setattr(overture_tasks, "verify_candidate", lambda url: {
        "status": "reachable", "final_url": url, "robots_allowed": True,
        "page_title": "Test Funeral Directors", "content_sha256": "b" * 64,
        "extracted_data": {"name": "Test Funeral Directors", "street": "1 High Street",
            "town": "Tilbury", "postcode": "RM18 7QX", "telephone": "01375 856903",
            "email": None, "website": url, "source_type": "schema_org_funeralhome",
            "country": "gb", "confidence": 0.97, "funeral_signals": ["funeral directors"],
            "has_complete_branch_address": True},
    })
    # Simulate an assessor regression: the final write-boundary guard must still hold.
    monkeypatch.setattr(overture_tasks, "assess_overture_candidate", lambda *args, **kwargs: {
        "outcome": "auto_approved_eligible", "reasons": "", "ruleset_version": "test",
        "confidence": 0.97, "source_licences": "CDLA-Permissive-2.0",
    })
    monkeypatch.setattr(overture_tasks.process_overture_candidates, "delay", lambda *a, **k: None)
    db = factory()
    candidate = OvertureCandidate(gers_id="gers-disabled-write-gate", candidate_name="Test Funeral Directors",
        postcode="RM18 7QX", raw_data=_candidate_row(), outcome="awaiting_enrichment", status="awaiting_enrichment")
    db.add(candidate); db.commit(); candidate_id = candidate.id; db.close()

    result = overture_tasks.process_overture_candidates.run(None, 20)
    assert result["outcomes"] == {"enrichment_approved": 1}
    db = factory()
    candidate = db.get(OvertureCandidate, candidate_id)
    assert candidate.outcome == "enrichment_approved"
    assert candidate.assessment["outcome"] == "enrichment_approved"
    assert "automatic_approval_disabled" in candidate.assessment["reasons"]
    assert candidate.provider_id is not None and candidate.branch_id is not None
    provider = db.get(Provider, candidate.provider_id)
    branch = db.get(Branch, candidate.branch_id)
    assert provider.status == "draft" and provider.verification_status == "unverified"
    assert branch.status == "draft"
    assert candidate.first_party_evidence["enrichment_approval"]["status"] == "auto_approved"
    assert candidate.first_party_evidence["pricing_enrichment"]["status"] == "queued"
    assert db.query(Provider).filter_by(status="published").count() == 0
    assert db.query(Branch).filter_by(status="published").count() == 0
    assert db.query(SourceObservation).filter_by(source_type="provider_owned_website_structured_data").count() == 0
    assert db.query(AuditEvent).filter(AuditEvent.action.in_(["auto_approved_published", "auto_approved_branch_added"])).count() == 0
    db.close(); engine.dispose()


def test_overture_website_identity_mismatch_routes_candidate_to_exception_review(monkeypatch, tmp_path):
    engine, factory = _session_factory()
    monkeypatch.setattr(overture_tasks, "SessionLocal", factory)
    monkeypatch.setattr(overture_tasks, "ONS_BOUNDARY_CACHE_DIR", tmp_path)
    monkeypatch.setattr(overture_tasks.settings, "auto_approve_providers", False)
    monkeypatch.setattr(overture_tasks, "dispatch_queued_price_enrichment", lambda *a, **k: 0)
    monkeypatch.setattr(overture_tasks, "_fetch_ons_geometry", lambda: {
        "type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]
    })
    monkeypatch.setattr(overture_tasks, "verify_candidate", lambda url: {
        "status": "reachable", "final_url": url, "robots_allowed": True,
        "extracted_data": {"name": "Different Funeral Directors", "street": "1 High Street",
            "town": "Tilbury", "postcode": "RM17 5LS", "has_complete_branch_address": True},
    })
    db = factory()
    candidate = OvertureCandidate(gers_id="gers-website-mismatch", candidate_name="Test Funeral Directors",
        postcode="RM18 7QX", raw_data=_candidate_row(), outcome="awaiting_enrichment", status="awaiting_enrichment")
    db.add(candidate); db.commit(); candidate_id = candidate.id; db.close()

    result = overture_tasks.process_overture_candidates.run(None, 20)
    assert result["outcomes"] == {"exception_review": 1}
    db = factory()
    candidate = db.get(OvertureCandidate, candidate_id)
    assert "first_party_identity_mismatch" in candidate.assessment["reasons"]
    assert candidate.provider_id is None and candidate.branch_id is None
    assert "pricing_enrichment" not in candidate.first_party_evidence
    db.close(); engine.dispose()


@pytest.mark.parametrize("extracted_data", [None, {"name": "Test Funeral Directors"}])
def test_reachable_overture_url_without_complete_extracted_identity_is_approved_for_enrichment(
    monkeypatch, tmp_path, extracted_data,
):
    engine, factory = _session_factory()
    monkeypatch.setattr(overture_tasks, "SessionLocal", factory)
    monkeypatch.setattr(overture_tasks, "ONS_BOUNDARY_CACHE_DIR", tmp_path)
    monkeypatch.setattr(overture_tasks.settings, "auto_approve_providers", True)
    monkeypatch.setattr(overture_tasks, "dispatch_queued_price_enrichment", lambda *a, **k: 0)
    monkeypatch.setattr(overture_tasks, "_fetch_ons_geometry", lambda: {
        "type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]
    })
    monkeypatch.setattr(overture_tasks, "verify_candidate", lambda url: {
        "status": "reachable", "final_url": url, "robots_allowed": True,
        "extracted_data": extracted_data,
    })
    db = factory()
    candidate = OvertureCandidate(gers_id="gers-identity-unavailable",
        candidate_name="Test Funeral Directors", postcode="RM18 7QX",
        raw_data=_candidate_row(), outcome="awaiting_enrichment", status="awaiting_enrichment")
    db.add(candidate); db.commit(); candidate_id = candidate.id; db.close()

    result = overture_tasks.process_overture_candidates.run(None, 20)

    db = factory()
    candidate = db.get(OvertureCandidate, candidate_id)
    assert result["outcomes"] == {"enrichment_approved": 1}
    assert candidate.outcome == "enrichment_approved"
    assert candidate.first_party_evidence["identity_evidence_status"] == "unverified"
    assert candidate.first_party_evidence["website_url"] == "https://test-funerals.example/"
    assert "first_party_identity_mismatch" not in candidate.assessment["reasons"]
    assert "first_party_identity_unverified" not in candidate.assessment["reasons"]
    provider = db.get(Provider, candidate.provider_id)
    branch = db.get(Branch, candidate.branch_id)
    assert provider.status == "draft" and branch.status == "draft"
    assert db.query(Provider).filter_by(status="published").count() == 0
    db.close(); engine.dispose()


def test_pipeline_tries_multiple_overture_urls_and_uses_the_matching_provider_site(monkeypatch, tmp_path):
    engine, factory = _session_factory()
    monkeypatch.setattr(overture_tasks, "SessionLocal", factory)
    monkeypatch.setattr(overture_tasks, "ONS_BOUNDARY_CACHE_DIR", tmp_path)
    monkeypatch.setattr(overture_tasks.settings, "auto_approve_providers", False)
    monkeypatch.setattr(overture_tasks, "_fetch_ons_geometry", lambda: {
        "type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]
    })
    attempts = []
    def verify(url):
        attempts.append(url)
        name = "Wrong Website Funeral Directors" if "wrong" in url else "Test Funeral Directors"
        return {"status": "reachable", "final_url": url, "robots_allowed": True,
                "extracted_data": {"name": name, "postcode": "RM18 7QX"}}
    monkeypatch.setattr(overture_tasks, "verify_candidate", verify)
    db = factory()
    raw = _candidate_row()
    raw["website"] = "https://wrong-site.example/"
    raw["websites_json"] = ["https://wrong-site.example/", "https://test-funerals.example/"]
    candidate = OvertureCandidate(gers_id="gers-multiple-overture-sites", candidate_name="Test Funeral Directors",
        postcode="RM18 7QX", raw_data=raw, outcome="awaiting_enrichment", status="awaiting_enrichment")
    db.add(candidate); db.commit(); candidate_id = candidate.id; db.close()

    result = overture_tasks.process_overture_candidates.run(None, 20)
    assert result["outcomes"] == {"enrichment_approved": 1}
    assert attempts == ["https://wrong-site.example/", "https://test-funerals.example/"]
    db = factory()
    candidate = db.get(OvertureCandidate, candidate_id)
    assert candidate.first_party_evidence["website_url"] == "https://test-funerals.example/"
    assert [x["identity_match"] for x in candidate.first_party_evidence["overture_url_attempts"]] == [False, True]
    db.close(); engine.dispose()


def test_overture_related_service_is_linked_using_its_own_provider_type(monkeypatch, tmp_path):
    engine, factory = _session_factory()
    monkeypatch.setattr(overture_tasks, "SessionLocal", factory)
    monkeypatch.setattr(overture_tasks, "ONS_BOUNDARY_CACHE_DIR", tmp_path)
    monkeypatch.setattr(overture_tasks.settings, "auto_approve_providers", False)
    monkeypatch.setattr(overture_tasks, "_fetch_ons_geometry", lambda: {
        "type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]
    })
    monkeypatch.setattr(overture_tasks, "verify_candidate", lambda url: {
        "status": "reachable", "final_url": url, "robots_allowed": True,
        "extracted_data": {"name": "Simplicity Cremations", "postcode": "RM18 7QX"},
    })
    db = factory()
    raw = _candidate_row()
    raw.update({"name": "Simplicity Cremations", "basic_category": "family_service", "taxonomy_primary": "funeral_service"})
    candidate = OvertureCandidate(gers_id="gers-related-service", candidate_name="Simplicity Cremations",
        postcode="RM18 7QX", raw_data=raw, outcome="awaiting_enrichment", status="awaiting_enrichment")
    db.add(candidate); db.commit(); candidate_id = candidate.id; db.close()

    result = overture_tasks.process_overture_candidates.run(None, 20)
    assert result["outcomes"] == {"enrichment_approved": 1}
    db = factory()
    candidate = db.get(OvertureCandidate, candidate_id)
    provider = db.get(Provider, candidate.provider_id)
    assert provider.provider_type == "direct_cremation"
    assert provider.status == "draft"
    db.close(); engine.dispose()


def test_reviewer_can_approve_overture_exception_for_enrichment_without_publication(monkeypatch):
    from app.routers.overture import EnrichmentApprovalPayload, approve_overture_candidate_for_enrichment

    engine, factory = _session_factory()
    monkeypatch.setattr(overture_tasks.process_overture_candidates, "delay", lambda *a, **k: None)
    db = factory()
    candidate = OvertureCandidate(
        gers_id="gers-manual-enrichment-approval",
        candidate_name="Test Funeral Directors",
        postcode="RM18 7QX",
        raw_data=_candidate_row(),
        outcome="exception_review",
        status="exception_review",
        assessment={"outcome": "exception_review", "reasons": "first_party_identity_mismatch"},
    )
    db.add(candidate); db.commit(); candidate_id = candidate.id

    response = approve_overture_candidate_for_enrichment(
        candidate_id,
        EnrichmentApprovalPayload(review_notes="Checked the Overture URL and identity."),
        reviewer="reviewer-test",
        db=db,
    )
    assert response["status"] == "queued_for_reassessment"
    assert response["approval_scope"] == "enrichment_only"
    assert candidate.status == candidate.outcome == "awaiting_enrichment"
    assert candidate.first_party_evidence["enrichment_approval"]["status"] == "approved_by_reviewer"
    assert db.query(Provider).count() == 0
    assert db.query(AuditEvent).filter_by(action="enrichment_exception_approved").count() == 1
    db.close(); engine.dispose()


def test_publication_records_roll_back_together_if_first_party_evidence_flush_fails(monkeypatch, tmp_path):
    engine, factory = _session_factory()
    monkeypatch.setattr(overture_tasks, "SessionLocal", factory)
    monkeypatch.setattr(overture_tasks, "ONS_BOUNDARY_CACHE_DIR", tmp_path)
    monkeypatch.setattr(overture_tasks.settings, "auto_approve_providers", True)
    monkeypatch.setattr(overture_tasks, "_fetch_ons_geometry", lambda: {
        "type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]
    })
    monkeypatch.setattr(overture_tasks, "verify_candidate", lambda url: {
        "status": "reachable", "final_url": url, "robots_allowed": True,
        "page_title": "Test Funeral Directors", "content_sha256": "c" * 64,
        "extracted_data": {"name": "Test Funeral Directors", "street": "1 High Street",
            "town": "Tilbury", "postcode": "RM18 7QX", "telephone": "01375 856903",
            "email": None, "website": url, "source_type": "schema_org_funeralhome",
            "country": "gb", "confidence": 0.97, "funeral_signals": ["funeral directors"],
            "has_complete_branch_address": True},
    })
    monkeypatch.setattr(overture_tasks.process_overture_candidates, "delay", lambda *a, **k: None)
    db = factory()
    candidate = OvertureCandidate(gers_id="gers-atomic-publication", candidate_name="Test Funeral Directors",
        postcode="RM18 7QX", raw_data=_candidate_row(), outcome="awaiting_enrichment", status="awaiting_enrichment")
    db.add(candidate); db.commit(); candidate_id = candidate.id; db.close()

    def fail_on_first_party_evidence(session, flush_context, instances):
        if any(isinstance(item, SourceObservation) and item.source_type == "provider_owned_website_structured_data"
               for item in session.new):
            raise RuntimeError("injected first-party evidence flush failure")

    event.listen(factory.class_, "before_flush", fail_on_first_party_evidence)
    try:
        with pytest.raises(RuntimeError, match="injected first-party evidence flush failure"):
            overture_tasks.process_overture_candidates.run(None, 20)
    finally:
        event.remove(factory.class_, "before_flush", fail_on_first_party_evidence)

    db = factory()
    candidate = db.get(OvertureCandidate, candidate_id)
    assert candidate.status == "awaiting_enrichment"
    assert candidate.outcome == "awaiting_enrichment"
    assert candidate.provider_id is None and candidate.branch_id is None
    assert db.query(Provider).count() == 0
    assert db.query(Branch).count() == 0
    assert db.query(SourceObservation).filter_by(source_type="provider_owned_website_structured_data").count() == 0
    assert db.query(AuditEvent).filter(AuditEvent.action.in_(("auto_approved_published", "auto_approved_branch_added"))).count() == 0
    db.close(); engine.dispose()


def test_pipeline_fails_closed_when_official_boundary_unavailable(monkeypatch, tmp_path):
    engine, factory = _session_factory()
    monkeypatch.setattr(overture_tasks, "SessionLocal", factory)
    monkeypatch.setattr(overture_tasks, "ONS_BOUNDARY_CACHE_DIR", tmp_path)
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


def test_processing_run_scope_is_filtered_before_batch_limit(monkeypatch):
    engine, factory = _session_factory()
    monkeypatch.setattr(overture_tasks, "SessionLocal", factory)
    monkeypatch.setattr(overture_tasks, "_fetch_ons_geometry", lambda: {
        "type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]
    })
    monkeypatch.setattr(overture_tasks, "assess_overture_candidate", lambda *args, **kwargs: {
        "outcome": "excluded", "reasons": "not_funeral_director:cemetery",
        "ruleset_version": "test", "confidence": 0,
    })
    from app.models import OvertureImportRun
    db = factory()
    run = OvertureImportRun(status="imported", source_release="2026-10-21.0")
    db.add(run); db.flush()
    candidate = OvertureCandidate(
        gers_id="gers-run-filter-regression",
        candidate_name="Test Cemetery", postcode="RM18 7QX",
        raw_data={"geography_scope": "thurrock", "name": "Test Cemetery"},
        outcome="awaiting_enrichment", status="awaiting_enrichment",
        last_import_run_id=run.id,
    )
    db.add(candidate); db.commit()
    run_id, candidate_id = run.id, candidate.id
    db.close()

    result = overture_tasks.process_overture_candidates.run(run_id, 20)
    assert result["records_processed"] == 1
    assert result["outcomes"] == {"excluded": 1}

    db = factory()
    candidate = db.get(OvertureCandidate, candidate_id)
    run = db.get(OvertureImportRun, run_id)
    assert candidate.status == "excluded"
    assert run.status == "completed"
    assert run.records_processed == 1
    db.close(); engine.dispose()



def test_duplicate_detection_ignores_same_name_postcode_peer_in_another_service_class():
    engine, factory = _session_factory()
    db = factory()
    funeral_raw = _candidate_row()
    funeral = OvertureCandidate(
        gers_id="gers-funeral-class", candidate_name=funeral_raw["name"],
        postcode=funeral_raw["postcode"], raw_data=funeral_raw,
    )
    other_raw = _candidate_row()
    other_raw["basic_category"] = "cemetery"
    other_raw["taxonomy_primary"] = "cemetery"
    other = OvertureCandidate(
        gers_id="gers-cemetery-class", candidate_name=other_raw["name"],
        postcode=other_raw["postcode"], raw_data=other_raw,
    )
    db.add_all([funeral, other]); db.flush()
    assert overture_tasks._overture_identity_collision_flags(db, funeral) == (False, False)
    db.close(); engine.dispose()


def test_same_service_same_branch_collision_uses_supporting_signals_and_near_coordinates():
    engine, factory = _session_factory()
    db = factory()
    first_raw = _candidate_row()
    first_raw.update({"longitude": "-0.1", "latitude": "51.5"})
    second_raw = _candidate_row()
    second_raw.update({"longitude": "-0.1001", "latitude": "51.5001"})
    first = OvertureCandidate(
        gers_id="gers-near-a", candidate_name=first_raw["name"],
        postcode=first_raw["postcode"], raw_data=first_raw,
    )
    second = OvertureCandidate(
        gers_id="gers-near-b", candidate_name=second_raw["name"],
        postcode=second_raw["postcode"], raw_data=second_raw,
    )
    db.add_all([first, second]); db.flush()
    assert overture_tasks._overture_identity_collision_flags(db, first) == (True, False)
    db.close(); engine.dispose()



def test_duplicate_detection_normalizes_case_and_whitespace_in_postcodes():
    engine, factory = _session_factory()
    db = factory()
    first_raw = _candidate_row()
    first_raw.update({"longitude": "-0.1", "latitude": "51.5"})
    second_raw = _candidate_row()
    second_raw.update({"longitude": "-0.1001", "latitude": "51.5001"})
    first = OvertureCandidate(
        gers_id="gers-postcode-format-a", candidate_name=first_raw["name"],
        postcode="RM17 5LS", raw_data=first_raw,
    )
    second = OvertureCandidate(
        gers_id="gers-postcode-format-b", candidate_name=second_raw["name"],
        postcode="rm175ls", raw_data=second_raw,
    )
    db.add_all([first, second]); db.flush()
    assert overture_tasks._overture_identity_collision_flags(db, first) == (True, False)
    db.close(); engine.dispose()

def test_same_identity_signals_with_material_coordinate_separation_are_location_conflict():
    engine, factory = _session_factory()
    db = factory()
    first_raw = _candidate_row()
    first_raw.update({"longitude": "-0.1", "latitude": "51.5"})
    second_raw = _candidate_row()
    second_raw.update({"longitude": "-0.11", "latitude": "51.51"})
    first = OvertureCandidate(
        gers_id="gers-far-a", candidate_name=first_raw["name"],
        postcode=first_raw["postcode"], raw_data=first_raw,
    )
    second = OvertureCandidate(
        gers_id="gers-far-b", candidate_name=second_raw["name"],
        postcode=second_raw["postcode"], raw_data=second_raw,
    )
    db.add_all([first, second]); db.flush()
    duplicate, location_conflict = overture_tasks._overture_identity_collision_flags(db, first)
    assert duplicate is False
    assert location_conflict is True
    db.close(); engine.dispose()


def test_name_postcode_match_without_supporting_signals_remains_conservative_review():
    engine, factory = _session_factory()
    db = factory()
    first_raw = _candidate_row()
    first_raw.update({"longitude": "-0.1", "latitude": "51.5"})
    second_raw = _candidate_row()
    second_raw.update({
        "longitude": "-0.11", "latitude": "51.51",
        "address": "99 Other Street", "address_line_1": "99 Other Street",
        "phone": "", "website": "",
    })
    first = OvertureCandidate(
        gers_id="gers-weak-a", candidate_name=first_raw["name"],
        postcode=first_raw["postcode"], raw_data=first_raw,
    )
    second = OvertureCandidate(
        gers_id="gers-weak-b", candidate_name=second_raw["name"],
        postcode=second_raw["postcode"], raw_data=second_raw,
    )
    db.add_all([first, second]); db.flush()
    assert overture_tasks._overture_identity_collision_flags(db, first) == (True, False)
    db.close(); engine.dispose()
