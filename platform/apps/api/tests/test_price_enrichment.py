import json

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
            "source_quote": "Standard funeral service: £3,250, including local collection.",
            "confidence": 0.94,
        }],
        "notes": "",
    }


def test_price_page_parser_captures_price_link_anchor_text():
    parser = _VisiblePageParser()
    parser.feed('<html><title>Example</title><a href="/services">Our services</a><a href="/fees">Our price list</a></html>')
    assert {"href": "/fees", "text": "Our price list"} in parser.links
    assert parser.title_parts == ["Example"]


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
            body = b'<html><title>Funeral fees</title><p>Standard funeral service: \xc2\xa33,250.</p></html>'
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

    pages = _fetch_price_pages("https://example-funerals.co.uk/", max_pages=6)
    assert len(pages) == 1
    assert pages[0]["url"] == "https://example-funerals.co.uk/fees"
    assert "£3,250" in pages[0]["text"]
    assert "£3,250" in pages[0]["ai_text"]


def test_ai_price_extraction_requires_amount_to_appear_in_exact_source_quote():
    page = {
        "url": "https://example-funerals.co.uk/prices",
        "title": "Funeral prices",
        "text": "Standard funeral service: £3,250, including local collection.",
        "sha256": "a" * 64,
    }
    assert len(_validate_extracted_prices(_price_payload(page["url"]), [page])) == 1

    fabricated = _price_payload(page["url"], amount=3590)
    assert _validate_extracted_prices(fabricated, [page]) == []

    wrong_page = _price_payload("https://example-funerals.co.uk/other")
    assert _validate_extracted_prices(wrong_page, [page]) == []


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


def test_enrichment_persists_ai_prices_as_pending_unverified_and_publicly_disclosed(monkeypatch):
    from app import pricing_enrichment

    engine, factory = _factory()
    monkeypatch.setattr(pricing_enrichment, "SessionLocal", factory)
    monkeypatch.setattr(pricing_enrichment.settings, "price_enrichment_enabled", True)
    monkeypatch.setattr(pricing_enrichment.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(pricing_enrichment.settings, "price_enrichment_model", "gpt-6-luna")
    monkeypatch.setattr(pricing_enrichment.settings, "price_enrichment_max_pages", 6)

    page_url = "https://example-funerals.co.uk/prices"
    page = {
        "url": page_url,
        "title": "Funeral prices",
        "text": "Standard funeral service: £3,250, including local collection.",
        "sha256": "b" * 64,
    }
    monkeypatch.setattr(pricing_enrichment, "verify_candidate", lambda url: {
        "status": "reachable",
        "final_url": url,
        "robots_allowed": True,
        "extracted_data": {"name": "Example Funeral Directors", "postcode": "RM17 5LS"},
    })
    monkeypatch.setattr(pricing_enrichment, "_fetch_price_pages", lambda url, limit: [page])
    monkeypatch.setattr(
        pricing_enrichment,
        "_call_openai_price_extractor",
        lambda pages, provider_name, branch_context: (_price_payload(page_url), "resp_test_price_001"),
    )

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
    assert provenance["extraction_method"] == "ai_extracted"
    assert provenance["verification_status"] == "unverified"
    assert provenance["label"] == "AI-extracted · Not verified"

    # Pending AI-extracted prices are visible to the public with a clear label.
    public = public_search("RM17", limit=50, db=db)
    assert len(public["items"]) == 1
    assert public["items"][0]["prices"][0]["verification_status"] == "unverified"
    assert public["items"][0]["prices"][0]["verification_label"] == "AI-extracted · Not verified"

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


def test_price_extraction_waits_for_explicit_source_permission(monkeypatch):
    from app import pricing_enrichment

    engine, factory = _factory()
    monkeypatch.setattr(pricing_enrichment, "SessionLocal", factory)
    monkeypatch.setattr(pricing_enrichment.settings, "price_enrichment_enabled", True)
    monkeypatch.setattr(pricing_enrichment.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(pricing_enrichment, "verify_candidate", lambda url: pytest.fail("Website must not be fetched before source permission approval"))

    db = factory()
    _, _, candidate, _ = _seed_approved_candidate(db, with_permission=False)
    candidate_id = candidate.id
    db.close()

    result = pricing_enrichment.enrich_overture_candidate_prices.run(candidate_id)
    assert result["status"] == "awaiting_permission"

    db = factory()
    candidate = db.get(OvertureCandidate, candidate_id)
    assert candidate.first_party_evidence["pricing_enrichment"]["status"] == "awaiting_permission"
    assert db.query(PricingEvidence).count() == 0
    db.close()
    engine.dispose()


def test_ai_price_cannot_be_verified_after_source_permission_is_revoked():
    from fastapi import HTTPException
    from app.routers.evidence import decide_pricing
    from app.pricing_enrichment import _persist_ai_prices

    engine, factory = _factory()
    db = factory()
    provider, branch, candidate, permission = _seed_approved_candidate(db)
    page = {
        "url": "https://example-funerals.co.uk/prices",
        "title": "Funeral prices",
        "text": "Standard funeral service: £3,250, including local collection.",
        "sha256": "c" * 64,
    }
    prices = __import__("app.pricing_enrichment", fromlist=["_validate_extracted_prices"])._validate_extracted_prices(
        _price_payload(page["url"]), [page]
    )
    _persist_ai_prices(
        db, candidate, provider, [page], prices,
        source_permission=permission, model="gpt-6-luna", response_id="resp_revoke_test",
    )
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
