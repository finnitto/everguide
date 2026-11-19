import json

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    Branch,
    OvertureCandidate,
    PricingEvidence,
    Provider,
    SourcePermission,
)
from app.pricing_enrichment import (
    _VisiblePageParser,
    _extract_rule_based_prices,
    _fetch_price_pages,
    _validate_extracted_prices,
    enrich_overture_candidate_prices,
)
from app.routers.evidence import EvidenceDecisionIn, decide_pricing
from app.routers.providers import public_search


def _factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _price_payload(url, amount=3250):
    return {
        "has_explicit_prices": True,
        "prices": [{
            "service_name": "Standard funeral service",
            "service_category": "funeral",
            "fee_type": "package",
            "amount": amount,
            "amount_upper": None,
            "currency": "GBP",
            "price_basis": "fixed",
            "includes": ["Local collection"],
            "excludes": [],
            "source_page_url": url,
            "source_page_number": None,
            "source_quote": "Standard funeral service: \u00a33,250, including local collection.",
            "confidence": 0.94,
        }],
        "notes": "",
    }


def test_price_page_parser_captures_price_link_anchor_text():
    parser = _VisiblePageParser()
    parser.feed('<html><title>Example</title><a href="/services">Our services</a><a href="/fees">Our price list</a></html>')
    assert {"href": "/fees", "text": "Our price list"} in parser.links
    assert parser.title_parts == ["Example"]


def test_failed_price_retry_creates_tracked_run_and_updates_terminal_progress(monkeypatch):
    from datetime import datetime, timezone
    from app.models import OvertureImportRun, AuditEvent
    from app.pricing_enrichment import _set_candidate_pricing_status
    from app.routers.overture import FailedPriceRetryPayload, _run_dict, retry_failed_price_enrichment

    engine, factory = _factory()
    db = factory()
    monkeypatch.setattr("app.routers.overture.settings.price_enrichment_enabled", True)
    dispatched = []
    monkeypatch.setattr("app.routers.overture.dispatch_queued_price_enrichment",
                        lambda ids, **kwargs: (dispatched.extend(ids) or len(ids)))
    provider = Provider(trading_name="Example Funeral Directors", display_name="Example Funeral Directors",
                        website="https://example-funerals.co.uk", provider_type="funeral_director",
                        status="draft", verification_status="pending")
    db.add(provider); db.flush()
    branch = Branch(provider_id=provider.id, branch_name="Example", address_line_1="1 High Street",
                    town_city="Grays", postcode="RM17 5LS", website="https://example-funerals.co.uk",
                    status="draft")
    db.add(branch); db.flush()
    candidate = OvertureCandidate(
        gers_id="gers-retry-test", candidate_name="Example Funeral Directors", postcode="RM17 5LS",
        provider_id=provider.id, branch_id=branch.id, outcome="enrichment_approved", status="enrichment_approved",
        first_party_evidence={"website_url":"https://example-funerals.co.uk/", "verification_status":"reachable",
                              "robots_allowed":True, "pricing_enrichment":{"status":"failed","last_error":"TimeoutError"}},
    )
    db.add(candidate); db.flush()
    no_price_candidate = OvertureCandidate(
        gers_id="gers-recheck-test", candidate_name="Example Funeral Directors", postcode="RM17 5LS",
        provider_id=provider.id, branch_id=branch.id, outcome="enrichment_approved", status="enrichment_approved",
        first_party_evidence={"website_url":"https://example-funerals.co.uk/", "verification_status":"reachable",
                              "robots_allowed":True, "pricing_enrichment":{"status":"no_prices_found","last_error":"No prices on previous check"}},
    )
    db.add(no_price_candidate); db.flush()
    source_run = OvertureImportRun(status="completed", records_received=1, records_processed=1,
        outcomes={"_meta":{"run_type":"enrichment_retry","candidate_ids":[candidate.id,no_price_candidate.id],"target_count":2}})
    db.add(source_run); db.flush()
    source_evidence = dict(candidate.first_party_evidence)
    source_evidence["pricing_enrichment"] = {**source_evidence["pricing_enrichment"], "overture_run_id": source_run.id}
    candidate.first_party_evidence = source_evidence
    sample_evidence = dict(no_price_candidate.first_party_evidence)
    sample_evidence["pricing_enrichment"] = {**sample_evidence["pricing_enrichment"], "overture_run_id": source_run.id}
    no_price_candidate.first_party_evidence = sample_evidence
    db.commit()

    result = retry_failed_price_enrichment(
        FailedPriceRetryPayload(source_run_id=source_run.id, recheck_no_price_sample=True), reviewer="reviewer-test", db=db,
    )
    assert result["candidates_queued"] == result["tasks_dispatched"] == 2
    assert result["no_price_sample_rechecked"] == 1
    assert dispatched == [candidate.id, no_price_candidate.id]
    candidate = db.get(OvertureCandidate, candidate.id)
    retry_id = candidate.first_party_evidence["pricing_enrichment"]["overture_run_id"]
    assert candidate.first_party_evidence["pricing_enrichment"]["status"] == "queued"
    assert candidate.first_party_evidence["pricing_enrichment"]["previous_error"] == "TimeoutError"
    no_price_candidate = db.get(OvertureCandidate, no_price_candidate.id)
    assert no_price_candidate.first_party_evidence["pricing_enrichment"]["status"] == "queued"
    assert no_price_candidate.first_party_evidence["pricing_enrichment"]["previous_error"] == "No prices on previous check"
    retry_run = db.get(OvertureImportRun, retry_id)
    assert retry_run.outcomes["_meta"]["run_type"] == "price_retry"
    assert _run_dict(retry_run, db)["progress"]["prices_queued"] == 2

    _set_candidate_pricing_status(db, candidate, "completed", extra={"price_records_created":1})
    db.commit()
    _set_candidate_pricing_status(db, no_price_candidate, "no_prices_found", extra={"price_records_created":0})
    db.commit()
    progress = _run_dict(retry_run, db)
    assert retry_run.status == "completed"
    assert progress["progress"]["prices_terminal"] == 2
    assert progress["progress"]["price_outcomes"] == {"completed":1,"no_prices_found":1}
    db.close(); engine.dispose()


def test_visible_html_parser_keeps_price_table_rows_and_normalizes_inline_whitespace():
    parser = _VisiblePageParser()
    parser.feed("<table><tr><th>Direct cremation</th><td>From</td><td>£1,250</td></tr></table>")
    parser.close()
    assert parser.lines == ["Direct cremation | From | £1,250"]


def test_crawler_follows_same_site_price_link_even_when_homepage_has_no_prices(monkeypatch):
    from email.message import Message
    from urllib.parse import urlsplit
    from app import pricing_enrichment

    class _Robots:
        def can_fetch(self, agent, url):
            return True

    def fake_get(url, limit):
        headers = Message()
        headers["Content-Type"] = "text/html; charset=utf-8"
        if url == "https://example-funerals.co.uk/":
            body = b'<html><a href="/fees">View our funeral price list</a></html>'
        elif url == "https://example-funerals.co.uk/fees":
            body = ("<html><title>Funeral fees</title><p>Standard funeral service: " + chr(163) + "3,250.</p></html>").encode("utf-8")
        else:
            raise AssertionError(f"Unexpected URL: {url}")
        return 200, headers, body, None

    monkeypatch.setattr(
        pricing_enrichment,
        "_validate_public_https",
        lambda url: (urlsplit(url), "example-funerals.co.uk"),
    )
    monkeypatch.setattr(pricing_enrichment, "_read_robots", lambda origin: _Robots())
    monkeypatch.setattr(pricing_enrichment, "_get", fake_get)

    diagnostics = {}
    pages = _fetch_price_pages("https://example-funerals.co.uk/", max_pages=6, diagnostics=diagnostics)
    assert len(pages) == 1
    assert pages[0]["url"] == "https://example-funerals.co.uk/fees"
    assert chr(163) + "3,250" in pages[0]["text"]
    assert diagnostics["pages_attempted"] == 2
    assert diagnostics["pages_fetched"] == 2
    assert chr(163) + "3,250" in pages[0]["text"]


def test_price_extraction_requires_amount_to_appear_in_exact_source_quote():
    page = {
        "url": "https://example-funerals.co.uk/prices",
        "title": "Funeral prices",
        "text": "Standard funeral service: \u00a33,250, including local collection.",
        "sha256": "a" * 64,
    }
    assert len(_validate_extracted_prices(_price_payload(page["url"]), [page])) == 1

    fabricated = _price_payload(page["url"], amount=3590)
    assert _validate_extracted_prices(fabricated, [page]) == []

    wrong_page = _price_payload("https://example-funerals.co.uk/other")
    assert _validate_extracted_prices(wrong_page, [page]) == []


def test_deterministic_parser_extracts_explicit_fixed_and_range_prices_and_skips_ambiguous_rows():
    page = {
        "url": "https://example-funerals.co.uk/prices.pdf",
        "title": "Funeral price list",
        "text": "Direct cremation £1,250\nTraditional funeral £2,500 to £3,200\nFrom £1,000 plus £250 optional flowers",
        "lines": [
            "Direct cremation £1,250",
            "Traditional funeral £2,500 to £3,200",
            "From £1,000 plus £250 optional flowers",
        ],
        "sha256": "f" * 64,
        "source_format": "pdf",
        "source_page_number": 2,
    }
    result = _extract_rule_based_prices([page])
    prices = _validate_extracted_prices(result, [page])
    assert [(p["service_name"], p["amount"], p["amount_upper"], p["price_basis"]) for p in prices] == [
        ("Direct cremation", Decimal("1250.00"), None, "fixed"),
        ("Traditional funeral", Decimal("2500.00"), Decimal("3200.00"), "range"),
    ]
    assert all(p["source_format"] == "pdf" and p["source_page_number"] == 2 for p in prices)


def test_deterministic_parser_keeps_option_group_tied_to_price_quote():
    page = {
        "url": "https://example-funerals.co.uk/prices",
        "title": "Funeral prices",
        "text": "Simple Funeral\nSimple funeral service £1,850",
        "lines": ["Simple Funeral", "Simple funeral service £1,850"],
        "sha256": "a" * 64,
    }
    prices = _validate_extracted_prices(_extract_rule_based_prices([page]), [page])
    assert len(prices) == 1
    assert prices[0]["option_group_name"] == "Simple Funeral"


def test_pdf_price_source_requires_matching_page_and_exact_quote():
    page = {
        "url": "https://example-funerals.co.uk/prices.pdf",
        "title": "PDF page 2",
        "text": "Standard funeral service: \u00a33,250, including local collection.",
        "sha256": "d" * 64,
        "source_format": "pdf",
        "source_page_number": 2,
    }
    payload = _price_payload(page["url"])
    payload["prices"][0]["source_page_number"] = 2
    assert _validate_extracted_prices(payload, [page])[0]["source_page_number"] == 2

    wrong_page = _price_payload(page["url"])
    wrong_page["prices"][0]["source_page_number"] = 1
    assert _validate_extracted_prices(wrong_page, [page]) == []

    wrong_quote = _price_payload(page["url"])
    wrong_quote["prices"][0]["source_page_number"] = 2
    wrong_quote["prices"][0]["source_quote"] = "Standard funeral service: Â£3,590."
    assert _validate_extracted_prices(wrong_quote, [page]) == []


def test_crawler_extracts_price_text_from_linked_pdf(monkeypatch):
    from email.message import Message
    from urllib.parse import urlsplit
    from app import pricing_enrichment

    class _Robots:
        def can_fetch(self, agent, url):
            return True

    class _PdfPage:
        def extract_text(self):
            return "Standard funeral service: Â£3,250, including local collection."

    class _Pdf:
        is_encrypted = False
        pages = [_PdfPage()]

        def __init__(self, *args, **kwargs):
            pass

    def fake_get(url, limit):
        headers = Message()
        if url.endswith("/"):
            headers["Content-Type"] = "text/html; charset=utf-8"
            return 200, headers, b'<a href="/price-list.pdf">Download our price list</a>', None
        assert url == "https://example-funerals.co.uk/price-list.pdf"
        headers["Content-Type"] = "application/pdf"
        return 200, headers, b"%PDF-test", None

    monkeypatch.setattr(pricing_enrichment, "_validate_public_https",
                        lambda url: (urlsplit(url), "example-funerals.co.uk"))
    monkeypatch.setattr(pricing_enrichment, "_read_robots", lambda origin: _Robots())
    monkeypatch.setattr(pricing_enrichment, "_get", fake_get)
    monkeypatch.setattr(pricing_enrichment, "PdfReader", _Pdf)

    pages = _fetch_price_pages("https://example-funerals.co.uk/", max_pages=6)
    assert len(pages) == 1
    assert pages[0]["source_format"] == "pdf"
    assert pages[0]["source_page_number"] == 1
    assert chr(163) + "3,250" in pages[0]["text"]


def test_crawler_percent_encodes_spaces_in_same_site_pdf_links(monkeypatch):
    from email.message import Message
    from urllib.parse import urlsplit
    from app import pricing_enrichment

    class _Robots:
        def can_fetch(self, agent, url):
            return True

    class _PdfPage:
        def extract_text(self):
            return "Simple funeral service: £1,850"

    class _Pdf:
        is_encrypted = False
        pages = [_PdfPage()]

        def __init__(self, *args, **kwargs):
            pass

    def fake_get(url, limit):
        headers = Message()
        if url == "https://example-funerals.co.uk/":
            headers["Content-Type"] = "text/html; charset=utf-8"
            return 200, headers, b'<a href="/Standardised Price List.pdf">Download price list</a>', None
        assert url == "https://example-funerals.co.uk/Standardised%20Price%20List.pdf"
        headers["Content-Type"] = "application/pdf"
        return 200, headers, b"%PDF-test", None

    monkeypatch.setattr(pricing_enrichment, "_validate_public_https",
                        lambda url: (urlsplit(url), "example-funerals.co.uk"))
    monkeypatch.setattr(pricing_enrichment, "_read_robots", lambda origin: _Robots())
    monkeypatch.setattr(pricing_enrichment, "_get", fake_get)
    monkeypatch.setattr(pricing_enrichment, "PdfReader", _Pdf)

    pages = _fetch_price_pages("https://example-funerals.co.uk/")
    assert len(pages) == 1
    assert pages[0]["source_format"] == "pdf"


def test_crawler_reports_bounded_oversize_responses_without_aborting(monkeypatch):
    from email.message import Message
    from urllib.parse import urlsplit
    from app import pricing_enrichment

    class _Robots:
        def can_fetch(self, agent, url):
            return True

    calls = []

    def fake_get(url, limit):
        calls.append(url)
        if url == "https://example-funerals.co.uk/":
            raise ValueError("Response exceeded the configured safety size limit.")
        headers = Message()
        headers["Content-Type"] = "text/html; charset=utf-8"
        return 200, headers, b"", None

    monkeypatch.setattr(pricing_enrichment, "_validate_public_https",
                        lambda url: (urlsplit(url), "example-funerals.co.uk"))
    monkeypatch.setattr(pricing_enrichment, "_read_robots", lambda origin: _Robots())
    monkeypatch.setattr(pricing_enrichment, "_get", fake_get)
    diagnostics = {}

    assert _fetch_price_pages("https://example-funerals.co.uk/", diagnostics=diagnostics) == []
    assert calls == ["https://example-funerals.co.uk/"]
    assert diagnostics["pages_attempted"] == 1
    assert diagnostics["pages_skipped"]["response_size_limit"] == 1


def test_crawler_marks_antibot_interstitial_as_challenge_not_price_content(monkeypatch):
    from email.message import Message
    from urllib.parse import urlsplit
    from app import pricing_enrichment

    class _Robots:
        def can_fetch(self, agent, url):
            return True

    def fake_get(url, limit):
        headers = Message()
        headers["Content-Type"] = "text/html; charset=utf-8"
        return 200, headers, b"<html><title>Pardon Our Interruption</title><p>Automated requests detected</p></html>", None

    monkeypatch.setattr(pricing_enrichment, "_validate_public_https",
                        lambda url: (urlsplit(url), "example-funerals.co.uk"))
    monkeypatch.setattr(pricing_enrichment, "_read_robots", lambda origin: _Robots())
    monkeypatch.setattr(pricing_enrichment, "_get", fake_get)
    diagnostics = {}

    assert _fetch_price_pages("https://example-funerals.co.uk/", diagnostics=diagnostics) == []
    assert diagnostics["access_challenge_pages"] == 1
    assert diagnostics["pages_fetched"] == 1


def _seed_approved_candidate(db, *, with_permission=True):
    provider = Provider(
        trading_name="Example Funeral Directors",
        display_name="Example Funeral Directors",
        website="https://example-funerals.co.uk",
        provider_type="funeral_director",
        status="published",
        verification_status="approved",
    )
    db.add(provider)
    db.flush()
    branch = Branch(
        provider_id=provider.id,
        branch_name="Example Funeral Directors",
        address_line_1="1 High Street",
        town_city="Grays",
        postcode="RM17 5LS",
        website="https://example-funerals.co.uk",
        status="published",
    )
    db.add(branch)
    db.flush()
    candidate = OvertureCandidate(
        gers_id="gers-price-test-001",
        candidate_name="Example Funeral Directors",
        postcode="RM17 5LS",
        raw_data={
            "name": "Example Funeral Directors",
            "postcode": "RM17 5LS",
            "address_line_1": "1 High Street",
            "town_city": "Grays",
        },
        provider_id=provider.id,
        branch_id=branch.id,
        first_party_evidence={
            "website_url": "https://example-funerals.co.uk",
            "verification_status": "reachable",
            "robots_allowed": True,
            "pricing_enrichment": {"status": "queued", "attempt_count": 0},
        },
    )
    db.add(candidate)
    db.flush()
    permission = None
    if with_permission:
        permission = SourcePermission(
            provider_id=provider.id,
            source_url="https://example-funerals.co.uk",
            source_domain="example-funerals.co.uk",
            permission_status="approved",
            permission_basis="Reviewer-approved provider-owned website factual price extraction.",
            approved_by="reviewer-test",
        )
        db.add(permission)
    db.commit()
    return provider, branch, candidate, permission


def test_enrichment_persists_rule_prices_as_pending_unverified_and_publicly_disclosed(monkeypatch):
    from app import pricing_enrichment

    engine, factory = _factory()
    monkeypatch.setattr(pricing_enrichment, "SessionLocal", factory)
    monkeypatch.setattr(pricing_enrichment.settings, "price_enrichment_enabled", True)
    monkeypatch.setattr(pricing_enrichment.settings, "price_enrichment_max_pages", 6)

    page_url = "https://example-funerals.co.uk/prices"
    page = {
        "url": page_url,
        "title": "Funeral prices",
        "text": "Standard funeral service: \u00a33,250, including local collection.",
        "sha256": "b" * 64,
    }
    monkeypatch.setattr(pricing_enrichment, "verify_candidate", lambda url: {
        "status": "reachable",
        "final_url": url,
        "robots_allowed": True,
        "extracted_data": {"name": "Example Funeral Directors", "postcode": "RM17 5LS"},
    })
    monkeypatch.setattr(pricing_enrichment, "_fetch_price_pages", lambda url, limit, **kwargs: [page])

    db = factory()
    _, _, candidate, permission = _seed_approved_candidate(db)
    candidate_id = candidate.id
    permission_id = permission.id
    db.close()

    result = pricing_enrichment.enrich_overture_candidate_prices.run(candidate_id)
    assert result["status"] == "completed"
    assert result["prices_extracted"] == 1

    db = factory()
    candidate = db.get(OvertureCandidate, candidate_id)
    price = db.query(PricingEvidence).one()
    assert candidate.first_party_evidence["pricing_enrichment"]["status"] == "completed"
    assert price.review_status == "pending"
    assert price.amount == 3250
    assert price.source_permission_id == permission_id
    assert price.evidence_excerpt == page["text"]
    provenance = price.evidence_payload["provenance"]
    assert provenance["extraction_method"] == "deterministic_rules"
    assert provenance["verification_status"] == "unverified"
    assert provenance["label"] == "Rule-extracted " + chr(183) + " Not verified"

    # Pending rule-extracted prices are visible to the public with a clear label.
    public = public_search("RM17", limit=50, db=db)
    assert len(public["items"]) == 1
    assert public["items"][0]["prices"][0]["verification_status"] == "unverified"
    assert public["items"][0]["prices"][0]["verification_label"] == "Rule-extracted " + chr(183) + " Not verified"

    # Only a reviewer decision changes the displayed label to verified.
    verified = decide_pricing(
        price.id,
        EvidenceDecisionIn(review_status="approved", review_notes="Amount checked on source page."),
        reviewer="reviewer-test",
        db=db,
    )
    assert verified["verification_status"] == "verified"
    assert verified["verification_label"] == "Verified by Everguide reviewer"
    public_after_review = public_search("RM17", limit=50, db=db)
    assert public_after_review["items"][0]["prices"][0]["verification_status"] == "verified"
    db.close()
    engine.dispose()


def test_overture_verified_website_is_auto_permitted_for_enrichment(monkeypatch):
    from app import pricing_enrichment

    engine, factory = _factory()
    monkeypatch.setattr(pricing_enrichment, "SessionLocal", factory)
    monkeypatch.setattr(pricing_enrichment.settings, "price_enrichment_enabled", True)
    page_url = "https://example-funerals.co.uk/prices"
    page = {
        "url": page_url,
        "title": "Funeral prices",
        "text": "Standard funeral service: \u00a33,250, including local collection.",
        "sha256": "e" * 64,
    }
    monkeypatch.setattr(pricing_enrichment, "verify_candidate", lambda url: {
        "status": "reachable",
        "final_url": url,
        "robots_allowed": True,
        "extracted_data": {"name": "Example Funeral Directors", "postcode": "RM17 5LS"},
    })
    monkeypatch.setattr(pricing_enrichment, "_fetch_price_pages", lambda url, limit, **kwargs: [page])

    db = factory()
    provider, branch, candidate, _ = _seed_approved_candidate(db, with_permission=False)
    provider.status = "draft"
    branch.status = "draft"
    candidate_id = candidate.id
    db.close()

    result = pricing_enrichment.enrich_overture_candidate_prices.run(candidate_id)
    assert result["status"] == "completed"

    db = factory()
    candidate = db.get(OvertureCandidate, candidate_id)
    assert candidate.first_party_evidence["pricing_enrichment"]["status"] == "completed"
    permission = db.query(SourcePermission).one()
    assert permission.permission_status == "approved"
    assert permission.approved_by == "system:overture_verified_website"
    assert "Overture-supplied website URL" in permission.permission_basis
    assert db.query(PricingEvidence).one().source_permission_id == permission.id
    db.close()
    engine.dispose()


def test_overture_price_fetch_allows_reachable_site_without_extracted_identity(monkeypatch):
    from app import pricing_enrichment

    engine, factory = _factory()
    monkeypatch.setattr(pricing_enrichment, "SessionLocal", factory)
    monkeypatch.setattr(pricing_enrichment.settings, "price_enrichment_enabled", True)
    page = {
        "url": "https://example-funerals.co.uk/prices",
        "title": "Funeral prices",
        "text": "Standard funeral service: \u00a33,250, including local collection.",
        "sha256": "f" * 64,
    }
    monkeypatch.setattr(pricing_enrichment, "verify_candidate", lambda url: {
        "status": "reachable", "final_url": url, "robots_allowed": True,
        "extracted_data": None,
    })
    monkeypatch.setattr(pricing_enrichment, "_fetch_price_pages", lambda url, limit, **kwargs: [page])

    db = factory()
    _, _, candidate, _ = _seed_approved_candidate(db, with_permission=False)
    candidate_id = candidate.id
    db.close()

    result = pricing_enrichment.enrich_overture_candidate_prices.run(candidate_id)

    db = factory()
    candidate = db.get(OvertureCandidate, candidate_id)
    assert result["status"] == "completed"
    assert candidate.first_party_evidence["pricing_enrichment"]["status"] == "completed"
    permission = db.query(SourcePermission).one()
    assert permission.permission_status == "approved"
    assert permission.approved_by == "system:overture_verified_website"
    assert db.query(PricingEvidence).one().amount == 3250
    db.close()
    engine.dispose()


def test_overture_price_worker_records_anti_automation_page_as_blocked(monkeypatch):
    from app import pricing_enrichment

    engine, factory = _factory()
    monkeypatch.setattr(pricing_enrichment, "SessionLocal", factory)
    monkeypatch.setattr(pricing_enrichment.settings, "price_enrichment_enabled", True)
    monkeypatch.setattr(pricing_enrichment, "verify_candidate", lambda url: {
        "status": "reachable", "final_url": url, "robots_allowed": True, "extracted_data": None,
    })

    def challenge_fetch(url, limit, *, diagnostics=None):
        diagnostics.update({"pages_attempted":1,"pages_fetched":1,
                            "pages_skipped":{"access_challenge":1},"access_challenge_pages":1})
        return []

    monkeypatch.setattr(pricing_enrichment, "_fetch_price_pages", challenge_fetch)
    db = factory()
    _, _, candidate, _ = _seed_approved_candidate(db, with_permission=False)
    candidate_id = candidate.id
    db.close()

    result = pricing_enrichment.enrich_overture_candidate_prices.run(candidate_id)
    assert result["status"] == "blocked"
    db = factory()
    candidate = db.get(OvertureCandidate, candidate_id)
    marker = candidate.first_party_evidence["pricing_enrichment"]
    assert marker["status"] == "blocked"
    assert marker["pages_checked"] == 1
    assert "no access controls were bypassed" in marker["last_error"]
    db.close(); engine.dispose()


def test_verified_site_conflict_requires_positive_same_branch_evidence():
    from app.pricing_enrichment import _verified_site_has_explicit_branch_conflict

    engine, factory = _factory()
    db = factory()
    _, _, candidate, _ = _seed_approved_candidate(db)
    assert not _verified_site_has_explicit_branch_conflict(candidate, None)
    assert not _verified_site_has_explicit_branch_conflict(candidate, {
        "name": "Different Provider", "postcode": "RM17 5LS",
    })
    assert _verified_site_has_explicit_branch_conflict(candidate, {
        "name": "Different Provider", "street": "1 High Street", "town": "Grays",
        "postcode": "RM17 5LS", "has_complete_branch_address": True,
    })
    assert _verified_site_has_explicit_branch_conflict(candidate, {
        "name": "Example Funeral Directors", "street": "1 High Street", "town": "Grays",
        "postcode": "RM17 6LS", "has_complete_branch_address": True,
    })
    db.close()
    engine.dispose()


def test_explicitly_blocked_overture_source_remains_blocked(monkeypatch):
    from app import pricing_enrichment

    engine, factory = _factory()
    monkeypatch.setattr(pricing_enrichment, "SessionLocal", factory)
    monkeypatch.setattr(pricing_enrichment.settings, "price_enrichment_enabled", True)
    monkeypatch.setattr(pricing_enrichment, "verify_candidate", lambda url: {
        "status": "reachable",
        "final_url": url,
        "robots_allowed": True,
        "extracted_data": {"name": "Example Funeral Directors", "postcode": "RM17 5LS"},
    })
    monkeypatch.setattr(pricing_enrichment, "_fetch_price_pages", lambda *args, **kwargs: pytest.fail("Blocked source must not be fetched"))

    db = factory()
    _, _, candidate, permission = _seed_approved_candidate(db)
    permission.permission_status = "blocked"
    candidate_id = candidate.id
    db.commit()
    db.close()

    result = pricing_enrichment.enrich_overture_candidate_prices.run(candidate_id)
    assert result["status"] == "blocked"

    db = factory()
    candidate = db.get(OvertureCandidate, candidate_id)
    assert candidate.first_party_evidence["pricing_enrichment"]["status"] == "blocked"
    assert db.query(PricingEvidence).count() == 0
    db.close()
    engine.dispose()


def test_rule_price_cannot_be_verified_after_source_permission_is_revoked():
    from fastapi import HTTPException
    from app.routers.evidence import decide_pricing
    from app.pricing_enrichment import _persist_extracted_prices

    engine, factory = _factory()
    db = factory()
    provider, branch, candidate, permission = _seed_approved_candidate(db)
    page = {
        "url": "https://example-funerals.co.uk/prices",
        "title": "Funeral prices",
        "text": "Standard funeral service: \u00a33,250, including local collection.",
        "sha256": "c" * 64,
    }
    prices = __import__("app.pricing_enrichment", fromlist=["_validate_extracted_prices"])._validate_extracted_prices(
        _price_payload(page["url"]), [page]
    )
    _persist_extracted_prices(db, candidate, provider, [page], prices, source_permission=permission)
    db.commit()
    price = db.query(PricingEvidence).one()
    permission.permission_status = "blocked"
    db.commit()

    with pytest.raises(HTTPException) as exc:
        decide_pricing(
            price.id,
            EvidenceDecisionIn(review_status="approved"),
            reviewer="reviewer-test",
            db=db,
        )
    assert exc.value.status_code == 409
    public = public_search("RM17", limit=50, db=db)
    assert public["items"][0]["prices"] == []
    db.close()
    engine.dispose()


def test_approving_source_requeues_candidates_waiting_for_source_permission(monkeypatch):
    from app import pricing_enrichment
    from app.routers.enrichment import approve_source

    engine, factory = _factory()
    monkeypatch.setattr(pricing_enrichment.settings, "price_enrichment_enabled", False)
    db = factory()
    provider = Provider(
        trading_name="Waiting Funeral Directors",
        provider_type="funeral_director",
        status="published",
    )
    db.add(provider)
    db.flush()
    source = SourcePermission(
        provider_id=provider.id,
        source_url="https://waiting-funerals.example",
        source_domain="waiting-funerals.example",
        permission_status="automated_check",
        permission_basis="Reviewer-reviewed factual price research basis.",
    )
    db.add(source)
    candidate = OvertureCandidate(
        gers_id="gers-waiting-permission-001",
        candidate_name="Waiting Funeral Directors",
        postcode="RM17 5LS",
        provider_id=provider.id,
        first_party_evidence={
            "website_url": "https://waiting-funerals.example",
            "verification_status": "reachable",
            "robots_allowed": True,
            "pricing_enrichment": {
                "status": "awaiting_permission",
                "last_error": "Waiting for reviewer source approval",
            },
        },
    )
    db.add(candidate)
    db.commit()
    candidate_id = candidate.id
    source_id = source.id

    result = approve_source(source_id, reviewer="reviewer-test", db=db)

    assert result["permission_status"] == "approved"
    assert result["pricing_candidates_requeued"] == 1
    assert result["pricing_tasks_dispatched"] == 0
    candidate = db.get(OvertureCandidate, candidate_id)
    marker = candidate.first_party_evidence["pricing_enrichment"]
    assert marker["status"] == "queued"
    assert marker["permission_id"] == source_id
    assert marker["permission_approved_by"] == "reviewer-test"
    db.close()
    engine.dispose()
