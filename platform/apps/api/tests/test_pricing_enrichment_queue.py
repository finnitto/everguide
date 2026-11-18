from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AuditEvent, OvertureCandidate, Provider
from app.pricing_enrichment import (
    queue_overture_candidate_for_pricing,
    queue_approved_overture_candidates_for_pricing,
)
from app.routers.providers import set_provider_status


def _factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _candidate(gers_id, provider_id=None):
    return OvertureCandidate(
        gers_id=gers_id,
        candidate_name=f"{gers_id} Funeral Directors",
        postcode="RM17 5LS",
        provider_id=provider_id,
        first_party_evidence={"verification_status": "website_missing"},
    )


def test_queue_marker_is_idempotent_and_preserves_existing_evidence():
    engine, factory = _factory()
    db = factory()
    candidate = _candidate("gers-price-001", provider_id=10)
    db.add(candidate)
    db.flush()

    first = queue_overture_candidate_for_pricing(
        db, candidate, trigger="automatic_approval", requested_by="system"
    )
    second = queue_overture_candidate_for_pricing(
        db, candidate, trigger="automatic_approval", requested_by="system"
    )
    db.commit()

    assert first is True
    assert second is False
    assert candidate.first_party_evidence["verification_status"] == "website_missing"
    marker = candidate.first_party_evidence["pricing_enrichment"]
    assert marker["status"] == "queued"
    assert marker["trigger"] == "automatic_approval"
    assert db.query(AuditEvent).filter_by(action="pricing_enrichment_queued").count() == 1
    db.close()
    engine.dispose()


def test_manual_provider_approval_queues_every_linked_overture_candidate():
    engine, factory = _factory()
    db = factory()
    provider = Provider(
        trading_name="Manual Approval Funeral Directors",
        provider_type="funeral_director",
        status="draft",
    )
    db.add(provider)
    db.flush()
    first = _candidate("gers-manual-001", provider.id)
    second = _candidate("gers-manual-002", provider.id)
    db.add_all([first, second])
    db.commit()

    result = set_provider_status(
        provider.id, "approved", reviewer="reviewer-dev", db=db
    )

    assert result["status"] == "approved"
    assert result["pricing_enrichment_candidates_queued"] == 2
    for candidate in (first, second):
        marker = candidate.first_party_evidence["pricing_enrichment"]
        assert marker["status"] == "queued"
        assert marker["trigger"] == "manual_approval"
        assert marker["requested_by"] == "reviewer-dev"
    assert db.query(AuditEvent).filter_by(
        entity_type="provider",
        action="manual_approval_pricing_enrichment_requested",
    ).count() == 1
    db.close()
    engine.dispose()


def test_approved_candidate_backfill_queues_only_approved_funeral_directors():
    engine, factory = _factory()
    db = factory()
    approved = Provider(trading_name="Approved FD", provider_type="funeral_director", status="approved")
    published = Provider(trading_name="Published FD", provider_type="funeral_director", status="published")
    draft = Provider(trading_name="Draft FD", provider_type="funeral_director", status="draft")
    other = Provider(trading_name="Other Service", provider_type="direct_cremation", status="published")
    db.add_all([approved, published, draft, other])
    db.flush()
    candidates = [
        _candidate("gers-backfill-001", approved.id),
        _candidate("gers-backfill-002", published.id),
        _candidate("gers-backfill-003", draft.id),
        _candidate("gers-backfill-004", other.id),
    ]
    db.add_all(candidates)
    db.commit()

    result = queue_approved_overture_candidates_for_pricing(
        db, requested_by="reviewer-dev"
    )
    db.commit()

    assert result == {"matched_candidates": 2, "queued": 2, "already_marked": 0, "queued_candidate_ids": [candidates[0].id, candidates[1].id]}
    assert candidates[0].first_party_evidence["pricing_enrichment"]["status"] == "queued"
    assert candidates[1].first_party_evidence["pricing_enrichment"]["status"] == "queued"
    assert "pricing_enrichment" not in candidates[2].first_party_evidence
    assert "pricing_enrichment" not in candidates[3].first_party_evidence

    from app.routers.overture import list_pricing_enrichment_queue
    queue = list_pricing_enrichment_queue(status="queued", limit=100, offset=0, db=db)
    assert queue["count"] == 2
    assert {item["provider_status"] for item in queue["items"]} == {"approved", "published"}
    db.close()
    engine.dispose()
