import json
from datetime import datetime, timezone, timedelta
from http.client import IncompleteRead

from app import overture_tasks as tasks


def _geometry():
    return {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}


def _extracted(name="Example Funeral Directors", postcode="RM17 5LS", telephone="01375 555000"):
    return {
        "name": name, "street": "1 High Street", "town": "Grays",
        "postcode": postcode, "telephone": telephone, "email": None,
        "website": "https://examplefunerals.co.uk", "source_type": "schema_org_funeralhome",
        "country": "gb", "confidence": 0.97,
        "funeral_signals": ["funeral directors"], "has_complete_branch_address": True,
    }


def test_known_third_party_leads_are_not_first_party_websites():
    for url in (
        "https://directory.shropshirestar.co.uk/search/telford/funeral-directors",
        "https://tyldesley.cylex-uk.co.uk/company/co-op-funeralcare.html",
        "https://www.yellowtom.co.uk/funeral-directors/wigan",
        "https://find-and-update.company-information.service.gov.uk/company/12345678",
        "https://www.thefarewellguide.co.uk/funeral-directors/example",
        "https://www.yell.com/biz/example-funeral-directors",
    ):
        assert tasks._is_non_first_party_url(url), url


def test_directory_url_is_retained_as_lead_but_search_can_find_matching_official_site(monkeypatch):
    monkeypatch.setattr(tasks.settings, "brave_search_api_key", "test-key")
    monkeypatch.setattr(tasks, "search_web", lambda *a, **k: [
        {"url": "https://www.examplefunerals.co.uk/", "title": "Example Funeral Directors"},
        {"url": "https://www.yell.com/biz/example", "title": "Example"},
    ])
    calls = []

    def verify(url):
        calls.append(url)
        return {"status": "reachable", "final_url": url, "robots_allowed": True,
                "extracted_data": _extracted()}

    monkeypatch.setattr(tasks, "verify_candidate", verify)
    raw = {"name": "Example Funeral Directors", "postcode": "RM17 5LS", "phone": "01375 555000"}
    url, result = tasks._verify_overture_website(raw,
        "https://tyldesley.cylex-uk.co.uk/company/example.html")
    assert url == "https://www.examplefunerals.co.uk/"
    assert result["discovery_source"] == "brave_search"
    assert calls == ["https://www.examplefunerals.co.uk/"]


def test_mismatched_search_result_is_not_promoted_to_identity_conflict(monkeypatch):
    monkeypatch.setattr(tasks.settings, "brave_search_api_key", "test-key")
    monkeypatch.setattr(tasks, "search_web", lambda *a, **k: [
        {"url": "https://www.unrelatedfunerals.co.uk/", "title": "Unrelated"},
    ])
    monkeypatch.setattr(tasks, "verify_candidate", lambda url: {
        "status": "reachable", "final_url": url, "robots_allowed": True,
        "extracted_data": _extracted(name="Unrelated Funeral Directors", postcode="AB1 2CD", telephone="01234 567890"),
    })
    raw = {"name": "Example Funeral Directors", "postcode": "RM17 5LS", "phone": "01375 555000"}
    url, result = tasks._verify_overture_website(raw, "https://www.yell.com/biz/example")
    assert url is None
    assert result["status"] == "website_missing"
    assert result["discovery_source"] == "third_party_discovery_lead"


def test_boundary_cache_persists_across_task_calls_and_records_provenance(monkeypatch, tmp_path):
    monkeypatch.setattr(tasks, "ONS_BOUNDARY_CACHE_DIR", tmp_path)
    monkeypatch.setattr(tasks, "ONS_BOUNDARY_CACHE_TTL_HOURS", 720)
    fetches = []
    monkeypatch.setattr(tasks, "_fetch_ons_geometry", lambda: (fetches.append(1) or _geometry()))

    first = tasks._get_ons_boundary("thurrock")
    second = tasks._get_ons_boundary("thurrock")

    assert first == second == _geometry()
    assert len(fetches) == 1
    payload = json.loads((tmp_path / "ons-thurrock-boundary-v2.json").read_text())
    assert payload["schema_version"] == 2
    assert payload["scope"] == "thurrock"
    assert payload["source"] == tasks.ONS_QUERY_URL
    assert payload["retrieved_at"]
    assert payload["sha256"]


def test_corrupt_boundary_cache_is_rejected_and_refetched(monkeypatch, tmp_path):
    monkeypatch.setattr(tasks, "ONS_BOUNDARY_CACHE_DIR", tmp_path)
    monkeypatch.setattr(tasks, "ONS_BOUNDARY_CACHE_TTL_HOURS", 720)
    calls = []
    monkeypatch.setattr(tasks, "_fetch_ons_geometry", lambda: (calls.append(1) or _geometry()))
    tasks._get_ons_boundary("thurrock")
    cache_file = tmp_path / "ons-thurrock-boundary-v2.json"
    payload = json.loads(cache_file.read_text())
    payload["sha256"] = "invalid"
    cache_file.write_text(json.dumps(payload))

    assert tasks._get_ons_boundary("thurrock") == _geometry()
    assert len(calls) == 2


def test_ons_incomplete_read_retries_with_verified_tls(monkeypatch):
    calls = []

    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return b'{"features": []}'

    def fake_urlopen(request, timeout, context):
        calls.append(context)
        assert context.check_hostname is True
        assert context.verify_mode == 2  # ssl.CERT_REQUIRED
        if len(calls) < 3:
            raise IncompleteRead(b"partial", 100)
        return Response()

    monkeypatch.setattr(tasks.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(tasks.time, "sleep", lambda _: None)
    assert tasks._fetch_ons_json("https://ons.example/query", timeout=5)["features"] == []
    assert len(calls) == 3


def test_expired_boundary_cache_is_not_used(monkeypatch, tmp_path):
    monkeypatch.setattr(tasks, "ONS_BOUNDARY_CACHE_DIR", tmp_path)
    monkeypatch.setattr(tasks, "ONS_BOUNDARY_CACHE_TTL_HOURS", 1)
    monkeypatch.setattr(tasks, "_fetch_ons_geometry", lambda: _geometry())
    tasks._write_boundary_cache("thurrock", _geometry())
    cache_file = tmp_path / "ons-thurrock-boundary-v2.json"
    payload = json.loads(cache_file.read_text())
    payload["retrieved_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    cache_file.write_text(json.dumps(payload))
    assert tasks._read_boundary_cache("thurrock") is None


def test_scheduled_retry_requeues_only_due_enrichment_candidates(monkeypatch):
    monkeypatch.setattr(tasks.settings, "overture_scheduled_tasks_enabled", True)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    from app.models import AuditEvent, OvertureCandidate

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(tasks, "SessionLocal", factory)
    queued = []
    monkeypatch.setattr(tasks.process_overture_candidates, "delay", lambda *a, **k: queued.append(a))
    now = datetime.now(timezone.utc)
    db = factory()
    due = OvertureCandidate(gers_id="retry-due", candidate_name="Example Funeral Directors",
        postcode="RM17 5LS", status="awaiting_enrichment", outcome="awaiting_enrichment",
        last_checked_at=now - timedelta(days=3),
        first_party_evidence={"enrichment_attempt_count": 1, "next_retry_at": (now - timedelta(hours=1)).isoformat()})
    not_due = OvertureCandidate(gers_id="retry-not-due", candidate_name="Another Funeral Directors",
        postcode="RM18 7QX", status="awaiting_enrichment", outcome="awaiting_enrichment",
        last_checked_at=now - timedelta(days=1),
        first_party_evidence={"enrichment_attempt_count": 1, "next_retry_at": (now + timedelta(days=1)).isoformat()})
    exhausted = OvertureCandidate(gers_id="retry-exhausted", candidate_name="Third Funeral Directors",
        postcode="SS1 1AA", status="awaiting_enrichment", outcome="awaiting_enrichment",
        last_checked_at=now - timedelta(days=30),
        first_party_evidence={"enrichment_attempt_count": 4, "retry_limit_reached": True})
    db.add_all([due, not_due, exhausted]); db.commit()
    due_id, not_due_id, exhausted_id = due.id, not_due.id, exhausted.id
    db.close()

    result = tasks.retry_awaiting_enrichment.run()
    db = factory()
    assert result["requeued"] == 1
    assert queued == [(None, 20)]
    assert db.get(OvertureCandidate, due_id).last_checked_at is None
    assert db.get(OvertureCandidate, not_due_id).last_checked_at is not None
    assert db.get(OvertureCandidate, exhausted_id).last_checked_at is not None
    assert db.query(AuditEvent).filter_by(action="enrichment_retry_queued").count() == 1
    db.close(); engine.dispose()


def test_stale_empty_import_run_is_closed_with_audit(monkeypatch):
    monkeypatch.setattr(tasks.settings, "overture_scheduled_tasks_enabled", True)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    from app.models import AuditEvent, OvertureImportRun

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(tasks, "SessionLocal", factory)
    db = factory()
    old = datetime.now(timezone.utc) - timedelta(days=3)
    run = OvertureImportRun(status="running", created_at=old, started_at=old, records_received=0)
    db.add(run); db.commit(); run_id = run.id; db.close()

    result = tasks.reconcile_stale_overture_import_runs.run()
    db = factory()
    run = db.get(OvertureImportRun, run_id)
    assert result["failed_runs"] == [run_id]
    assert run.status == "failed"
    assert "no linked candidate records" in run.error_message
    assert db.query(AuditEvent).filter_by(action="stale_import_run_closed_without_candidates").count() == 1
    db.close(); engine.dispose()


def test_stale_import_run_with_unprocessed_candidates_is_resumed(monkeypatch):
    monkeypatch.setattr(tasks.settings, "overture_scheduled_tasks_enabled", True)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    from app.models import OvertureCandidate, OvertureImportRun

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(tasks, "SessionLocal", factory)
    queued = []
    monkeypatch.setattr(tasks.process_overture_candidates, "delay", lambda *a, **k: queued.append(a))
    db = factory()
    old = datetime.now(timezone.utc) - timedelta(days=3)
    run = OvertureImportRun(status="processing", created_at=old, started_at=old, records_received=1)
    db.add(run); db.flush()
    candidate = OvertureCandidate(gers_id="stale-pending", candidate_name="Example Funeral Directors",
        postcode="RM17 5LS", last_import_run_id=run.id, status="awaiting_enrichment",
        outcome="awaiting_enrichment", last_checked_at=None)
    db.add(candidate); db.commit(); run_id = run.id; db.close()

    result = tasks.reconcile_stale_overture_import_runs.run()
    db = factory()
    assert result["resumed_runs"] == [run_id]
    assert db.get(OvertureImportRun, run_id).status == "processing"
    assert queued == [(run_id, 20)]
    db.close(); engine.dispose()


def test_automatic_publication_is_disabled_by_application_default():
    from app.config import Settings
    assert Settings(_env_file=None).auto_approve_providers is False


def test_social_news_jobs_and_public_register_urls_are_not_first_party():
    for url in (
        "https://www.facebook.com/examplefunerals/",
        "https://en.wikipedia.org/wiki/Co-op_Funeralcare",
        "https://jobs.coop.co.uk/funeralcare",
        "https://www.bristol247.com/news/example-funeral-service/",
        "https://funeral-notices.co.uk/",
        "https://www.example.co.uk/brochure.pdf",
    ):
        assert tasks._is_non_first_party_url(url), url


def test_search_mismatches_are_retained_as_attempts_not_promoted(monkeypatch):
    monkeypatch.setattr(tasks.settings, "brave_search_api_key", "test-key")
    monkeypatch.setattr(tasks, "search_web", lambda *a, **k: [
        {"url": "https://www.unrelatedfunerals.co.uk/", "title": "Unrelated"},
    ])
    monkeypatch.setattr(tasks, "verify_candidate", lambda url: {
        "status": "reachable", "final_url": url, "robots_allowed": True,
        "page_title": "Unrelated Funeral Directors", "content_sha256": "abc123",
        "extracted_data": _extracted(name="Unrelated Funeral Directors", postcode="AB1 2CD", telephone="01234 567890"),
    })
    raw = {"name": "Example Funeral Directors", "postcode": "RM17 5LS", "phone": "01375 555000"}
    url, result = tasks._verify_overture_website(raw, "https://www.yell.com/biz/example")
    assert url is None
    assert result["status"] == "website_missing"
    assert result["attempts"][0]["discovery_source"] == "brave_search"
    assert result["attempts"][0]["extracted_identity"]["name"] == "Unrelated Funeral Directors"
    assert result["attempts"][0]["content_sha256"] == "abc123"


def test_overture_mismatch_preserves_original_url_and_extracted_identity(monkeypatch):
    monkeypatch.setattr(tasks.settings, "brave_search_api_key", "")
    monkeypatch.setattr(tasks, "verify_candidate", lambda url: {
        "status": "reachable", "final_url": url, "robots_allowed": True,
        "extracted_data": _extracted(name="Different Funeral Directors", postcode="AB1 2CD", telephone="01234 567890"),
    })
    raw = {"name": "Example Funeral Directors", "postcode": "RM17 5LS", "phone": "01375 555000"}
    url, result = tasks._verify_overture_website(raw, "https://www.examplefunerals.co.uk/")
    assert url == "https://www.examplefunerals.co.uk/"
    assert result["discovery_source"] == "identity_or_branch_mismatch"
    assert result["attempts"][0]["extracted_identity"]["name"] == "Different Funeral Directors"
