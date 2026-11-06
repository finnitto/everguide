import re
import html
from collections import Counter
from urllib.parse import urlsplit, urlunsplit
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.config import settings
from app.models import WebsiteDiscoveryResult, WebsiteVerification, Provider
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

@router.get("/status")
def status(db: Session = Depends(get_db)):
    configured = bool(settings.brave_search_api_key) if settings.search_provider == "brave" else False
    rows = db.query(WebsiteDiscoveryResult).all()
    verification_count = db.query(WebsiteVerification).count()
    domains = {x.result_domain for x in rows}
    return {
        "configured": configured,
        "provider": settings.search_provider,
        "candidates": len(rows),
        "unique_domains": len(domains),
        "verification_checks": verification_count,
        "message": "Search provider configured." if configured else "Configure credentials for the selected search provider."
    }

@router.post("/runs", status_code=202)
def start_run():
    if settings.search_provider == "brave" and not settings.brave_search_api_key:
        raise HTTPException(400, "The selected search provider is not configured. Check its credentials in .env and restart API and worker.")
    task = discover_provider_websites.delay()
    return {"status":"queued","task_id":task.id,"message":"Automatic England regional website search queued."}

@router.post("/verification-runs", status_code=202)
def start_verification_run():
    task = verify_website_candidates.delay(limit=50)
    return {"status": "queued", "task_id": task.id,
            "message": "A bounded batch of up to 50 likely provider websites has been queued for technical checks."}

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
                      "verification": ({"status":latest_verification[x.id].status, "checked_at":latest_verification[x.id].checked_at, "http_status":latest_verification[x.id].http_status, "page_title":latest_verification[x.id].page_title, "final_url":latest_verification[x.id].final_url, "robots_allowed":latest_verification[x.id].robots_allowed, "detail":latest_verification[x.id].detail} if x.id in latest_verification else None),
                      "possible_matches":possible_matches[:5],"created_at":x.created_at})
    summary = Counter(item["candidate_type"] for item in items)
    return {"items":items,"summary":{"shown":len(items),"provider_candidates":summary["provider_candidate"],
            "directories":summary["directory_or_comparison"],"uncertain":summary["uncertain"],
            "likely_irrelevant":summary["likely_irrelevant"],"unique_domains_in_database":len(domain_counts)}}
