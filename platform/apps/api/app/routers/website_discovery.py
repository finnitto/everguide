import re
import html
from collections import Counter
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit, urlunsplit
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.config import settings
from app.models import AuditEvent, WebsiteDiscoveryResult, WebsiteVerification, WebsiteVerificationRun, Provider, Branch, SourceObservation
from app.tasks import discover_provider_websites, verify_website_candidates

router = APIRouter(prefix="/api/v1/website-discovery", tags=["automatic website discovery"])

DIRECTORY_TERMS = ("directory", "funeral guide", "compare funeral", "find a funeral", "reviews", "listings")
IRRELEVANT_TERMS = ("jobs", "careers", "vacancies", "wikipedia", "news", "facebook", "instagram", "linkedin")

def _clean_text(value):
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]*>", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def _canonical_url(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = re.sub(r"/{2,}", "/", parsed.path or "/").rstrip("/") or "/"
    return urlunsplit(("https", host, path, "", ""))

def _classify(title, snippet, domain):
    text = f"{title} {snippet} {domain}".lower()
    if any(term in text for term in IRRELEVANT_TERMS):
        return "likely_irrelevant"
    if any(term in text for term in DIRECTORY_TERMS) or domain in {"funeralguide.co.uk", "funeral-directory.co.uk"}:
        return "directory_or_comparison"
    if any(term in text for term in ("funeral directors", "funeral director", "funeral services", "undertakers", "funeral care")):
        return "provider_candidate"
    return "uncertain"

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
    if settings.search_provider == "brave" and not settings.brave_search_api_key:
        raise HTTPException(400, "The selected search provider is not configured. Check its credentials in .env and restart API and worker.")
    task = discover_provider_websites.delay()
    return {"status":"queued","task_id":task.id,"message":"Automatic England regional website search queued."}

@router.post("/verification-runs", status_code=202)
def start_verification_run(db: Session = Depends(get_db)):
    _recover_stale_verification_runs(db)
    active = db.query(WebsiteVerificationRun).filter(WebsiteVerificationRun.status.in_(["queued", "running"])).order_by(WebsiteVerificationRun.id.desc()).first()
    if active:
        return {"status": active.status, "run_id": active.id, "task_id": active.celery_task_id,
                "message": "A website verification batch is already queued or running. No duplicate batch was created."}
    run = WebsiteVerificationRun(status="queued", requested_limit=250, total=0, checked=0, outcomes={})
    db.add(run); db.commit(); db.refresh(run)
    try:
        task = verify_website_candidates.delay(limit=250, run_id=run.id)
        run.celery_task_id = task.id; db.commit()
    except Exception as exc:
        run.status = "failed"; run.error_message = str(exc)[:1000]; run.completed_at = datetime.now(timezone.utc); db.commit()
        raise HTTPException(503, "Could not queue website verification. Check the worker and Redis services.")
    return {"status":"queued", "run_id":run.id, "task_id":task.id,
            "message":"Automatic backlog processing has started. Everguide will process up to 250 candidates per batch and queue the next batch when work remains."}

@router.get("/verification-runs")
def verification_runs(limit: int = 10, db: Session = Depends(get_db)):
    _recover_stale_verification_runs(db)
    rows = db.query(WebsiteVerificationRun).order_by(WebsiteVerificationRun.id.desc()).limit(min(max(limit,1),50)).all()
    return {"items":[{"id":r.id,"status":r.status,"requested_limit":r.requested_limit,"total":r.total,
        "checked":r.checked,"outcomes":r.outcomes or {},"error_message":r.error_message,
        "created_at":r.created_at,"started_at":r.started_at,"completed_at":r.completed_at,
        "task_id":r.celery_task_id} for r in rows]}


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
    paused_candidates = db.query(WebsiteDiscoveryResult).filter(WebsiteDiscoveryResult.status == "held_quality_review").order_by(WebsiteDiscoveryResult.id.desc()).limit(100).all()
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
                    "unassessed": sum(p.quality_status == "unassessed" for p in providers),
                    "paused_candidate_count": db.query(WebsiteDiscoveryResult).filter(WebsiteDiscoveryResult.status == "held_quality_review").count(),
                    "paused_candidates": paused_candidate_rows,
                    "flagged_providers": [{"id": p.id, "name": p.trading_name, "website": p.website,
                        "status": p.status, "quality_status": p.quality_status, "verification_status": p.verification_status}
                        for p in providers if p.quality_status == "needs_review"][:100]},
        "geography": region_rows,
        "duplicate_checks": {"groups_flagged": len(duplicate_groups), "groups": duplicate_groups[:100]},
        "auto_approval_audit": [{"provider_id": e.entity_id, "provider_name": next((p.trading_name for p in providers if p.id == e.entity_id), None),
            "created_at": e.created_at, "detail": e.detail or {}} for e in recent],
        "source_observations": {"total": db.query(SourceObservation).count(),
            "accepted": db.query(SourceObservation).filter(SourceObservation.review_status == "accepted").count(),
            "pending": db.query(SourceObservation).filter(SourceObservation.review_status == "pending").count()}
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
            "directories":summary["directory_or_comparison"],"uncertain":summary["uncertain"],
            "likely_irrelevant":summary["likely_irrelevant"],"unique_domains_in_database":len(domain_counts)}}
