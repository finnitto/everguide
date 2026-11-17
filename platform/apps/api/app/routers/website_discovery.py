import re
import html
import json
import urllib.request
import urllib.error
from collections import Counter
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit, urlunsplit
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from app.database import get_db
from app.identity_review_auth import require_identity_reviewer
from app.config import settings
from app.models import AuditEvent, WebsiteDiscoveryResult, WebsiteVerification, WebsiteVerificationRun, Provider, Branch, SourceObservation, ProviderQualityAction
from app.tasks import discover_provider_websites, verify_website_candidates
from app.identity_rules import _classify, _normalise_identity_name, _provider_quality_assessment

router = APIRouter(prefix="/api/v1/website-discovery", tags=["automatic website discovery"])


def _clean_text(value):
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]*>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _canonical_url(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = re.sub(r"/{2,}", "/", parsed.path or "/").rstrip("/") or "/"
    return urlunsplit(("https", host, path, "", ""))


def _name_tokens(value):
    ignored = {"limited", "ltd", "plc", "the", "and", "funeral", "directors", "director", "services"}
    return {x for x in re.findall(r"[a-z0-9]+", (value or "").lower()) if len(x) > 2 and x not in ignored}

def _recover_stale_verification_runs(db: Session):
    """Mark abandoned batches failed only when a live worker no longer reports their task.

    This preserves active work and its committed candidate checks while allowing the
    dashboard to recover after a worker/container restart or an unhandled task crash.
    """
    from app.celery_app import celery_app
    from app.models import WebsiteVerificationRun

    try:
        inspector = celery_app.control.inspect(timeout=1.5)
        snapshots = [inspector.active(), inspector.reserved(), inspector.scheduled()]
        if all(snapshot is None for snapshot in snapshots):
            # No reliable worker response: do not make assumptions about queued work.
            return 0
        known_task_ids = set()
        for snapshot in snapshots:
            if not snapshot:
                continue
            for tasks in snapshot.values():
                for item in tasks or []:
                    request = item.get("request", item)
                    task_id = request.get("id")
                    if task_id:
                        known_task_ids.add(task_id)
    except Exception:
        # Monitoring must never prevent the admin API from serving its dashboard.
        return 0

    now = datetime.now(timezone.utc)
    recovered = 0
    active_runs = (db.query(WebsiteVerificationRun)
                   .filter(WebsiteVerificationRun.status.in_(["queued", "running"]))
                   .all())
    for run in active_runs:
        if run.celery_task_id and run.celery_task_id in known_task_ids:
            continue
        reference_time = run.started_at if run.status == "running" and run.started_at else run.created_at
        if reference_time is None:
            continue
        if reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=timezone.utc)
        age_seconds = (now - reference_time).total_seconds()
        threshold = 180 if run.status == "running" else 600
        if age_seconds < threshold:
            continue
        run.status = "failed"
        run.error_message = (
            "Verification task is no longer reported by the Celery worker. "
            "The batch was marked interrupted; previously committed checks and approvals are preserved."
        )
        run.completed_at = now
        db.add(AuditEvent(entity_type="website_verification", entity_id=run.id,
                          action="batch_recovered_as_interrupted",
                          detail={"task_id": run.celery_task_id, "checked": run.checked,
                                  "reason": "task_missing_from_worker_active_reserved_and_scheduled"}))
        recovered += 1
    if recovered:
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
    return recovered


@router.get("/status")
def status(db: Session = Depends(get_db)):
    configured = bool(settings.brave_search_api_key) if settings.search_provider == "brave" else False
    rows = db.query(WebsiteDiscoveryResult).all()
    verification_count = db.query(WebsiteVerification).count()
    backlog_count = db.query(WebsiteDiscoveryResult).filter(
        WebsiteDiscoveryResult.status.in_(["candidate", "verification_checked"])
    ).count()
    domains = {x.result_domain for x in rows}
    return {
        "configured": configured,
        "provider": settings.search_provider,
        "candidates": len(rows),
        "unique_domains": len(domains),
        "verification_checks": verification_count,
        "backlog_reassessment_candidates": backlog_count,
        "message": "Search provider configured." if configured else "Configure credentials for the selected search provider."
    }

@router.post("/runs", status_code=202)
def start_run():
    raise HTTPException(status_code=410, detail="Independent regional website discovery is disabled. Overture is the sole source of initial discovery candidates.")

@router.post("/verification-runs", status_code=202)
def start_verification_run():
    raise HTTPException(status_code=410, detail="Legacy website candidate verification is disabled pending the Overture-led workflow.")

@router.get("/verification-runs")
def verification_runs(limit: int = 10, db: Session = Depends(get_db)):
    _recover_stale_verification_runs(db)
    rows = db.query(WebsiteVerificationRun).order_by(WebsiteVerificationRun.id.desc()).limit(min(max(limit,1),50)).all()
    return {"items":[{"id":r.id,"status":r.status,"requested_limit":r.requested_limit,"total":r.total,
        "checked":r.checked,"outcomes":r.outcomes or {},"error_message":r.error_message,
        "created_at":r.created_at,"started_at":r.started_at,"completed_at":r.completed_at,
        "task_id":r.celery_task_id} for r in rows]}




@router.post("/quality-assessments", status_code=200)
def assess_existing_provider_quality(reviewer: str = Depends(require_identity_reviewer), db: Session = Depends(get_db)):
    """Idempotently assess existing provider records from retained evidence only."""
    providers = db.query(Provider).order_by(Provider.id.asc()).all()
    observations = db.query(SourceObservation).all()
    by_provider = {}
    for observation in observations:
        if observation.provider_id is not None:
            by_provider.setdefault(observation.provider_id, []).append(observation)
    assessed = {"confirmed": 0, "needs_review": 0, "insufficient_evidence": 0, "already_assessed": 0}
    now = datetime.now(timezone.utc)
    for provider in providers:
        if provider.quality_status != "unassessed":
            assessed["already_assessed"] += 1
            continue
        status, reason = _provider_quality_assessment(provider, by_provider.get(provider.id, []))
        provider.quality_status = status
        db.add(AuditEvent(entity_type="provider", entity_id=provider.id, action="provider_quality_assessed",
            detail={"quality_status": status, "reason": reason, "assessment_basis": "retained_everguide_records_only", "assessed_at": now.isoformat()}))
        assessed[status] += 1
    db.commit()
    return {"status": "completed", "total_providers": len(providers), "results": assessed,
            "message": "Existing records assessed using retained Everguide evidence only. Insufficient evidence is not treated as proof that a provider is invalid."}


@router.post("/quality-assessments/reassess", status_code=200)
def reassess_existing_provider_quality(reviewer: str = Depends(require_identity_reviewer), db: Session = Depends(get_db)):
    """Re-evaluate all providers using the corrected retained-evidence rules.

    Provider publication status and branch records are deliberately untouched.
    Every changed quality assessment is audited.
    """
    providers = db.query(Provider).order_by(Provider.id.asc()).all()
    observations = db.query(SourceObservation).all()
    by_provider = {}
    for observation in observations:
        if observation.provider_id is not None:
            by_provider.setdefault(observation.provider_id, []).append(observation)
    changed = {"confirmed": 0, "needs_review": 0, "insufficient_evidence": 0, "unchanged": 0}
    now = datetime.now(timezone.utc)
    for provider in providers:
        old_status = provider.quality_status or "unassessed"
        new_status, reason = _provider_quality_assessment(provider, by_provider.get(provider.id, []))
        if old_status == new_status:
            changed["unchanged"] += 1
            continue
        provider.quality_status = new_status
        db.add(AuditEvent(entity_type="provider", entity_id=provider.id, action="provider_quality_reassessed",
            detail={"previous_quality_status": old_status, "quality_status": new_status, "reason": reason,
                    "assessment_basis": "retained_everguide_records_corrected_rules", "assessed_at": now.isoformat()}))
        changed[new_status] += 1
    db.commit()
    return {"status": "completed", "total_providers": len(providers), "results": changed,
            "message": "Quality statuses re-evaluated using retained evidence. Provider publication and branch records were not changed."}


@router.get("/identity-review")
def provider_identity_review(db: Session = Depends(get_db)):
    """Return evidence-backed identity anomalies without changing provider records."""
    providers = db.query(Provider).order_by(Provider.id.asc()).all()
    observations = db.query(SourceObservation).filter(SourceObservation.review_status == "accepted").all()
    by_provider = {}
    for observation in observations:
        if observation.provider_id is not None:
            by_provider.setdefault(observation.provider_id, []).append(observation)
    auto_events = (db.query(AuditEvent).filter(AuditEvent.entity_type == "provider",
                    AuditEvent.action == "auto_approved_published").all())
    candidate_ids = {event.entity_id: (event.detail or {}).get("candidate_id") for event in auto_events}
    candidate_rows = {row.id: row for row in db.query(WebsiteDiscoveryResult).filter(
        WebsiteDiscoveryResult.id.in_([v for v in candidate_ids.values() if isinstance(v, int)] or [-1])).all()}
    results = []
    for provider in providers:
        current = (provider.trading_name or "").strip()
        current_norm = _normalise_identity_name(current)
        domain = (urlsplit(provider.website or "").hostname or "").lower().removeprefix("www.")
        suggestions = []
        flags = []
        if current.lower() in {"admin", "administrator", "unknown", "home", "welcome"} or current.lower().startswith(("http://", "https://", "www.")):
            flags.append("generic_or_url_provider_name")
        for obs in by_provider.get(provider.id, []):
            obs_domain = (urlsplit(obs.source_url or "").hostname or "").lower().removeprefix("www.")
            if not domain or obs_domain != domain:
                continue
            data = obs.observed_data or {}
            proposed = str(data.get("provider_name") or "").strip()
            proposed_norm = _normalise_identity_name(proposed)
            if proposed and proposed_norm and proposed_norm != current_norm and proposed.lower() not in {"admin", "unknown", "home", "welcome"}:
                suggestions.append({"name": proposed, "source_url": obs.source_url, "observation_id": obs.id,
                                    "confidence": obs.confidence, "source_type": obs.source_type})
        discovery = candidate_rows.get(candidate_ids.get(provider.id))
        if discovery:
            # Search title/snippet are context for an administrator, not proof of a rename.
            flags.append("original_discovery_context_available")
        discovery_context = None
        recommendation = "retain_and_monitor"
        category = "identity_review"
        if discovery:
            discovery_context = {"title": discovery.result_title, "snippet": discovery.result_snippet,
                                 "url": discovery.result_url, "domain": discovery.result_domain}
            classification = _classify(discovery.result_title, discovery.result_snippet, discovery.result_domain)
            if classification == "directory_or_comparison":
                category, recommendation = "directory_or_comparison", "exclude_from_funeral_director_category_review_existing_record"
                flags.append("discovery_source_appears_to_be_directory")
            elif classification == "related_service_not_funeral_director":
                category, recommendation = "related_service", "reclassify_service_type_review_existing_record"
                flags.append("discovery_source_appears_to_be_related_public_service")
            elif any(term in (discovery.result_url or "").lower() for term in ("/locations/", "/our-branches/", "/funeral-directors/manchester/")):
                category, recommendation = "parent_branch_relationship", "review_canonical_parent_and_branch_urls"
                flags.append("discovery_url_appears_location_specific")
        if current.lower() in {"admin", "administrator", "unknown", "home", "welcome"}:
            recommendation = "review_trading_name_against_independent_website_evidence"
            category = "trading_name_extraction"
        elif current.lower().startswith(("http://", "https://", "www.")):
            recommendation = "review_trading_name_against_independent_website_evidence"
            category = "trading_name_extraction"
        results.append({"provider_id": provider.id, "current_name": current, "website": provider.website,
                        "quality_status": provider.quality_status, "flags": flags,
                        "review_category": category, "recommended_action": recommendation,
                        "name_suggestions": suggestions[:3],
                        "discovery_context": discovery_context})
    return {"items": results, "count": len(results),
            "message": "Complete read-only identity review. Recommendations are advisory; no provider names, publication statuses or branches were changed."}


@router.get("/quality-actions")
def list_quality_actions(status: str | None = "pending", db: Session = Depends(get_db)):
    query = db.query(ProviderQualityAction)
    if status and status != "all":
        query = query.filter(ProviderQualityAction.status == status)
    rows = query.order_by(ProviderQualityAction.created_at.desc(), ProviderQualityAction.id.desc()).limit(500).all()
    provider_ids = {row.provider_id for row in rows}
    providers = {p.id: p for p in db.query(Provider).filter(Provider.id.in_(provider_ids or [-1])).all()}
    return {"items": [{"id": r.id, "provider_id": r.provider_id,
        "provider_name": providers[r.provider_id].trading_name if r.provider_id in providers else "(deleted)",
        "action_type": r.action_type, "category": r.category, "proposed_value": r.proposed_value,
        "evidence": r.evidence, "confidence": r.confidence, "status": r.status,
        "decision_note": r.decision_note, "created_at": r.created_at, "decided_at": r.decided_at}
        for r in rows], "count": len(rows)}


@router.post("/quality-actions/seed")
def seed_quality_actions(reviewer: str = Depends(require_identity_reviewer), db: Session = Depends(get_db)):
    """Create idempotent, evidence-linked proposals; never mutate live providers."""
    report = provider_identity_review(db)
    created = 0
    # Explicit proposals are intentionally limited to cases supported by the retained report.
    proposals = {
        17: ("rename", "trading_name_correction", {"trading_name": "Desmond L Bannon & Sons", "display_name": "Bannon’s"}, "high"),
        41: ("reclassify", "directory_or_comparison", {"provider_type": "directory"}, "high"),
        42: ("rename", "trading_name_correction", {"trading_name": "AH Freemantle Funeral Directors"}, "high"),
        58: ("reclassify", "related_service", {"provider_type": "related_service"}, "high"),
        65: ("rename", "trading_name_correction", {"trading_name": "S.C. & B.S. Cocks"}, "high"),
        72: ("reclassify", "directory_or_comparison", {"provider_type": "directory"}, "high"),
    }
    by_id = {item["provider_id"]: item for item in report["items"]}
    for provider_id, (action_type, category, value, confidence) in proposals.items():
        item = by_id.get(provider_id)
        provider = db.get(Provider, provider_id)
        if not item or not provider:
            continue
        if provider_id == 17:
            obsolete = db.query(ProviderQualityAction).filter(
                ProviderQualityAction.provider_id == 17,
                ProviderQualityAction.status == "pending").all()
            for old_action in obsolete:
                if (old_action.proposed_value or {}).get("trading_name") == "Bannons Funerals":
                    old_action.status = "superseded"
                    old_action.decision_note = "Superseded by a more specific evidence-linked distinction between business name and public display name."
                    old_action.decided_by = "system"
                    old_action.decided_at = datetime.now(timezone.utc)
                    db.add(AuditEvent(entity_type="provider_quality_action", entity_id=old_action.id,
                        action="superseded", detail={"reason": "More specific website name evidence"}, actor="system"))
        # Idempotency is based on the complete proposed payload, not merely
        # provider + action type. A superseded or older rename must not block
        # creation of a materially different replacement proposal.
        existing_rows = db.query(ProviderQualityAction).filter(
            ProviderQualityAction.provider_id == provider_id,
            ProviderQualityAction.action_type == action_type,
            ProviderQualityAction.status.in_(["pending", "approved"])).all()
        if any((row.proposed_value or {}) == value for row in existing_rows):
            continue
        evidence = {"website": provider.website, "discovery_context": item.get("discovery_context"),
                    "flags": item.get("flags", []), "report_category": item.get("review_category")}
        if provider_id == 17:
            evidence["name_interpretation"] = {
                "business_name": "Desmond L Bannon & Sons",
                "public_display_name": "Bannon’s",
                "registered_name": None,
                "registered_name_note": "Not inferred from website wording; requires independent legal-entity evidence."
            }
        db.add(ProviderQualityAction(provider_id=provider_id, action_type=action_type,
            category=category, proposed_value=value, evidence=evidence, confidence=confidence, status="pending"))
        created += 1
    # Parent/branch relationships are surfaced as non-executable review items.
    for item in report["items"]:
        if item.get("review_category") != "parent_branch_relationship":
            continue
        provider_id = item["provider_id"]
        exists = db.query(ProviderQualityAction).filter(ProviderQualityAction.provider_id == provider_id,
            ProviderQualityAction.category == "parent_branch_relationship",
            ProviderQualityAction.status.in_(["pending", "approved"])).first()
        if exists:
            continue
        db.add(ProviderQualityAction(provider_id=provider_id, action_type="review_only",
            category="parent_branch_relationship", proposed_value={},
            evidence={"website": item.get("website"), "discovery_context": item.get("discovery_context"),
                      "flags": item.get("flags", [])}, confidence="review", status="pending"))
        created += 1
    db.commit()
    return {"created": created, "message": "Proposals created. No provider data or publication status was changed."}


@router.post("/quality-actions/{action_id}/decide")
def decide_quality_action(action_id: int, decision: dict, reviewer: str = Depends(require_identity_reviewer), db: Session = Depends(get_db)):
    action = db.get(ProviderQualityAction, action_id)
    if not action:
        raise HTTPException(404, "Quality action not found")
    if action.status != "pending":
        raise HTTPException(409, "This proposal has already been decided")
    outcome = decision.get("decision")
    if outcome not in {"approve", "reject"}:
        raise HTTPException(400, "Decision must be approve or reject")
    provider = db.get(Provider, action.provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    if outcome == "approve":
        if action.action_type == "rename":
            new_name = (action.proposed_value or {}).get("trading_name", "").strip()
            if not new_name or len(new_name) > 240:
                raise HTTPException(400, "Proposed trading name is invalid")
            old_name = provider.trading_name
            old_display_name = provider.display_name
            proposed_display = (action.proposed_value or {}).get("display_name")
            provider.trading_name = new_name
            if proposed_display:
                if not isinstance(proposed_display, str) or len(proposed_display.strip()) > 240:
                    raise HTTPException(400, "Proposed display name is invalid")
                provider.display_name = proposed_display.strip()
            db.add(AuditEvent(entity_type="provider", entity_id=provider.id, action="quality_name_correction_approved",
                detail={"old_trading_name": old_name, "new_trading_name": new_name,
                        "old_display_name": old_display_name, "new_display_name": provider.display_name,
                        "registered_name_unchanged": provider.registered_name,
                        "quality_action_id": action.id, "evidence": action.evidence}, actor=reviewer))
        elif action.action_type == "reclassify":
            new_type = (action.proposed_value or {}).get("provider_type")
            if new_type not in {"directory", "related_service"}:
                raise HTTPException(400, "Unsupported provider reclassification")
            old_type = provider.provider_type
            provider.provider_type = new_type
            db.add(AuditEvent(entity_type="provider", entity_id=provider.id, action="quality_reclassification_approved",
                detail={"old_provider_type": old_type, "new_provider_type": new_type,
                        "quality_action_id": action.id, "evidence": action.evidence}, actor=reviewer))
        else:
            raise HTTPException(400, "This proposal is review-only and cannot be applied automatically")
        action.status = "approved"
    else:
        action.status = "rejected"
    action.decision_note = str(decision.get("note") or "")[:2000] or None
    action.decided_by = reviewer
    action.decided_at = datetime.now(timezone.utc)
    db.add(AuditEvent(entity_type="provider_quality_action", entity_id=action.id,
        action=("approved" if outcome == "approve" else "rejected"), detail={"provider_id": provider.id, "category": action.category,
        "action_type": action.action_type, "note": action.decision_note}, actor=reviewer))
    db.commit()
    return {"id": action.id, "status": action.status, "provider_id": provider.id,
            "provider_status": provider.status, "provider_type": provider.provider_type,
            "trading_name": provider.trading_name, "display_name": provider.display_name,
            "registered_name": provider.registered_name}


@router.post("/branch-enrichment/postcodes")
def enrich_published_branch_counties(reviewer: str = Depends(require_identity_reviewer), db: Session = Depends(get_db)):
    """Fill missing published-branch counties from the Postcodes.io bulk API.

    Only explicit admin_county values are written. Unitary-authority and other
    records with no county-level authority remain blank rather than substituting
    a district, region, postal town, or guessed ceremonial county.
    """
    published_provider_ids = [row[0] for row in db.query(Provider.id).filter(Provider.status == "published").all()]
    if not published_provider_ids:
        return {"status": "completed", "checked": 0, "updated": 0, "not_applicable": 0, "not_found": 0, "failed": 0,
                "message": "No published providers were found."}

    branches = (db.query(Branch).filter(Branch.provider_id.in_(published_provider_ids),
                 Branch.status == "published", or_(Branch.county.is_(None), func.trim(Branch.county) == ""))
                .order_by(Branch.id).all())
    if not branches:
        return {"status": "completed", "checked": 0, "updated": 0, "not_applicable": 0, "not_found": 0, "failed": 0,
                "message": "No published branches are currently missing a county."}

    postcodes = sorted({re.sub(r"\s+", " ", (b.postcode or "").strip()).upper() for b in branches if (b.postcode or "").strip()})
    if not postcodes:
        return {"status": "completed", "checked": len(branches), "updated": 0, "not_applicable": 0, "not_found": 0,
                "failed": len(branches), "message": "No usable postcodes were recorded."}
    if len(postcodes) > 100:
        raise HTTPException(400, "This enrichment batch exceeds the postcode service limit of 100 unique postcodes.")

    request_body = json.dumps({"postcodes": postcodes}).encode("utf-8")
    request = urllib.request.Request("https://api.postcodes.io/postcodes", data=request_body,
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "Everguide/1.7.0 postcode enrichment"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise HTTPException(502, f"Postcode lookup service could not be reached: {type(exc).__name__}")

    results = {}
    for item in payload.get("result") or []:
        query = re.sub(r"\s+", " ", (item.get("query") or "").strip()).upper()
        if query:
            results[query] = item.get("result")

    updated = not_applicable = not_found = failed = 0
    now = datetime.now(timezone.utc)
    for branch in branches:
        postcode = re.sub(r"\s+", " ", (branch.postcode or "").strip()).upper()
        result = results.get(postcode)
        if not postcode:
            outcome = "missing_postcode"
            failed += 1
        elif result is None:
            outcome = "postcode_not_found"
            not_found += 1
        elif result.get("country") != "England":
            outcome = "outside_england"
            not_applicable += 1
        elif (result.get("admin_county") or "").strip():
            # Recheck the field immediately before writing; never overwrite existing data.
            if (branch.county or "").strip():
                continue
            county = result["admin_county"].strip()
            branch.county = county
            outcome = "county_enriched"
            updated += 1
        else:
            # A null admin_county is expected for London, unitary authorities and
            # other areas without a county-level administrative authority.
            outcome = "no_county_level_authority"
            not_applicable += 1
        db.add(AuditEvent(entity_type="branch", entity_id=branch.id, action="postcode_county_lookup",
            detail={"outcome": outcome, "postcode": postcode, "source": "Postcodes.io", "source_url": "https://postcodes.io/",
                    "looked_up_at": now.isoformat(), "admin_county": (result or {}).get("admin_county"),
                    "admin_district": (result or {}).get("admin_district"), "region": (result or {}).get("region"),
                    "country": (result or {}).get("country")}))
    db.add(AuditEvent(entity_type="branch_enrichment", entity_id=0, action="postcode_county_enrichment_completed",
        detail={"checked": len(branches), "updated": updated, "not_applicable": not_applicable,
                "not_found": not_found, "failed": failed, "unique_postcodes": len(postcodes),
                "source": "Postcodes.io", "completed_at": now.isoformat()}))
    db.commit()
    return {"status": "completed", "checked": len(branches), "updated": updated,
            "not_applicable": not_applicable, "not_found": not_found, "failed": failed,
            "unique_postcodes": len(postcodes),
            "message": "County enrichment completed. Only explicit administrative county values were added; districts and regions were not substituted."}


@router.get("/analytics")
def provider_analytics(db: Session = Depends(get_db)):
    """Distinct provider, branch, geography and duplicate-quality reporting."""
    providers = db.query(Provider).all()
    branches = db.query(Branch).all()
    published = [p for p in providers if p.status == "published"]
    published_ids = {p.id for p in published}
    published_branches = [b for b in branches if b.provider_id in published_ids and b.status == "published"]

    def norm(value):
        return re.sub(r"[^a-z0-9]", "", (value or "").lower())

    name_groups = {}
    domain_groups = {}
    for p in published:
        key = norm(p.trading_name)
        if key:
            name_groups.setdefault(key, []).append(p)
        host = (urlsplit(p.website or "").hostname or "").lower().removeprefix("www.")
        if host:
            domain_groups.setdefault(host, []).append(p)
    postcode_groups = {}
    for b in published_branches:
        key = norm(b.postcode)
        if key:
            postcode_groups.setdefault(key, set()).add(b.provider_id)
    duplicate_groups = []
    seen_pairs = set()
    for kind, groups in (("provider_name", name_groups), ("website_domain", domain_groups)):
        for key, values in groups.items():
            ids = sorted({p.id for p in values})
            if len(ids) > 1:
                pair = (kind, tuple(ids))
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    duplicate_groups.append({"type": kind, "value": key, "provider_ids": ids,
                                            "provider_names": [next(p.trading_name for p in values if p.id == i) for i in ids]})
    for postcode, ids_set in postcode_groups.items():
        ids = sorted(ids_set)
        if len(ids) > 1:
            duplicate_groups.append({"type": "branch_postcode", "value": postcode, "provider_ids": ids,
                                     "provider_names": [next(p.trading_name for p in published if p.id == i) for i in ids]})

    county_counts = Counter((b.county or "County not recorded").strip() for b in published_branches)
    region_rows = [{"county": name, "published_branches": count} for name, count in county_counts.most_common()]
    paused_candidates = db.query(WebsiteDiscoveryResult).filter(WebsiteDiscoveryResult.status.in_(["exception_review", "held_quality_review", "auto_approval_held_possible_duplicate"])).order_by(WebsiteDiscoveryResult.id.desc()).limit(100).all()
    latest_checks = {}
    if paused_candidates:
        paused_ids = [c.id for c in paused_candidates]
        for check in db.query(WebsiteVerification).filter(WebsiteVerification.candidate_id.in_(paused_ids)).order_by(WebsiteVerification.checked_at.desc()).all():
            latest_checks.setdefault(check.candidate_id, check)
    paused_candidate_rows = [{"id": c.id, "title": c.result_title, "url": c.result_url,
        "extracted_data": (latest_checks[c.id].extracted_data if c.id in latest_checks else None),
        "checked_at": (latest_checks[c.id].checked_at if c.id in latest_checks else None)} for c in paused_candidates]
    auto_events = db.query(AuditEvent).filter(AuditEvent.action == "auto_approved_published").all()
    auto_provider_ids = sorted({e.entity_id for e in auto_events if e.entity_type == "provider" and e.entity_id in published_ids})
    auto_providers = [p for p in published if p.id in set(auto_provider_ids)]
    recent = sorted([e for e in auto_events if e.entity_type == "provider"], key=lambda e: e.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)[:50]
    return {
        "providers": {"total": len(providers), "published_distinct": len(published),
                      "auto_approved_distinct_published": len(auto_provider_ids),
                      "draft": sum(p.status == "draft" for p in providers),
                      "needs_review": sum(p.status == "needs_review" for p in providers)},
        "branches": {"total": len(branches), "published_distinct": len(published_branches),
                     "published_without_county": sum(not (b.county or "").strip() for b in published_branches),
                     "published_without_postcode": sum(not (b.postcode or "").strip() for b in published_branches)},
        "quality": {"needs_review": sum(p.quality_status == "needs_review" for p in providers),
                    "confirmed": sum(p.quality_status == "confirmed" for p in providers),
                    "insufficient_evidence": sum(p.quality_status == "insufficient_evidence" for p in providers),
                    "unassessed": sum(p.quality_status == "unassessed" for p in providers),
                    "paused_candidate_count": db.query(WebsiteDiscoveryResult).filter(WebsiteDiscoveryResult.status.in_(["exception_review", "held_quality_review", "auto_approval_held_possible_duplicate"])).count(),
                    "paused_candidates": paused_candidate_rows,
                    "flagged_providers": [{"id": p.id, "name": p.trading_name, "website": p.website,
                        "status": p.status, "quality_status": p.quality_status, "verification_status": p.verification_status}
                        for p in providers if p.quality_status == "needs_review"][:100],
                    "assessed_providers": [{"id": p.id, "name": p.trading_name, "website": p.website,
                        "status": p.status, "quality_status": p.quality_status}
                        for p in providers if p.quality_status != "unassessed"][:200]},
        "geography": region_rows,
        "duplicate_checks": {"groups_flagged": len(duplicate_groups), "groups": duplicate_groups[:100]},
        "auto_approval": {"enabled": settings.auto_approve_providers,
            "minimum_confidence": settings.auto_approval_min_confidence,
            "published_providers": len(auto_provider_ids),
            "exception_candidates": db.query(WebsiteDiscoveryResult).filter(WebsiteDiscoveryResult.status.in_(["exception_review", "held_quality_review", "auto_approval_held_possible_duplicate"])).count(),
            "not_eligible_candidates": db.query(WebsiteDiscoveryResult).filter(WebsiteDiscoveryResult.status == "reassessed_not_eligible").count()},
        "auto_approval_audit": [{"provider_id": e.entity_id, "provider_name": next((p.trading_name for p in providers if p.id == e.entity_id), None),
            "created_at": e.created_at, "detail": e.detail or {}} for e in recent],
        "branch_enrichment": {"latest_runs": [{"created_at": e.created_at, **(e.detail or {})}
            for e in db.query(AuditEvent).filter(AuditEvent.action == "postcode_county_enrichment_completed")
            .order_by(AuditEvent.created_at.desc()).limit(5).all()]},
        "source_observations": {"total": db.query(SourceObservation).count(),
            "accepted": db.query(SourceObservation).filter(SourceObservation.review_status == "accepted").count(),
            "pending": db.query(SourceObservation).filter(SourceObservation.review_status == "pending").count(),
            "by_source_type": [{"source_type": kind, "count": count} for kind, count in db.query(SourceObservation.source_type, func.count(SourceObservation.id)).group_by(SourceObservation.source_type).order_by(func.count(SourceObservation.id).desc()).all()] }
    }

@router.get("/candidates")
def candidates(limit:int=100, db:Session=Depends(get_db)):
    rows = db.query(WebsiteDiscoveryResult).order_by(WebsiteDiscoveryResult.created_at.desc()).limit(min(max(limit,1),500)).all()
    all_rows = db.query(WebsiteDiscoveryResult).all()
    verification_rows = (db.query(WebsiteVerification).order_by(WebsiteVerification.checked_at.desc()).all())
    latest_verification = {}
    for verification in verification_rows:
        latest_verification.setdefault(verification.candidate_id, verification)
    domain_counts = Counter(x.result_domain for x in all_rows)
    providers = db.query(Provider).all()
    items = []
    for x in rows:
        title = _clean_text(x.result_title)
        snippet = _clean_text(x.result_snippet)[:1200]
        candidate_type = _classify(title, snippet, x.result_domain)
        tokens = _name_tokens(title)
        possible_matches = []
        if candidate_type == "provider_candidate":
            for provider in providers:
                provider_tokens = _name_tokens(provider.trading_name)
                overlap = tokens & provider_tokens
                if len(overlap) >= 2 or (len(provider_tokens) == 1 and provider_tokens <= tokens):
                    possible_matches.append({"provider_id": provider.id, "provider_name": provider.trading_name,
                                             "shared_terms": sorted(overlap)})
        items.append({"id":x.id,"region":x.query_region,"title":title,"url":x.result_url,
                      "canonical_url":_canonical_url(x.result_url),"domain":x.result_domain,
                      "domain_candidate_count":domain_counts[x.result_domain],"snippet":snippet,
                      "status":x.status,"candidate_type":candidate_type,
                      "verification": ({"status":latest_verification[x.id].status, "checked_at":latest_verification[x.id].checked_at, "http_status":latest_verification[x.id].http_status, "page_title":latest_verification[x.id].page_title, "final_url":latest_verification[x.id].final_url, "robots_allowed":latest_verification[x.id].robots_allowed, "detail":latest_verification[x.id].detail,
                          "extracted_data":latest_verification[x.id].extracted_data} if x.id in latest_verification else None),
                      "possible_matches":possible_matches[:5],"created_at":x.created_at})
    summary = Counter(item["candidate_type"] for item in items)
    return {"items":items,"summary":{"shown":len(items),"provider_candidates":summary["provider_candidate"],
            "directories":summary["directory_or_comparison"],"related_services":summary["related_service_not_funeral_director"],
            "uncertain":summary["uncertain"],"likely_irrelevant":summary["likely_irrelevant"],
            "unique_domains_in_database":len(domain_counts)}}
