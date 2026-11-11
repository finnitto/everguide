import json
import urllib.request
import urllib.error
import urllib.parse
import urllib.robotparser
import hashlib
import html
import re
from datetime import datetime, timezone
from app.celery_app import celery_app
from app.config import settings
from app.database import SessionLocal
from app.models import DiscoveryRun, SourceObservation, AuditEvent, SourcePermission, WebsiteEvidenceCheck, Provider

# Regional discovery anchors. These are a starter coverage plan, not a boundary-
# validated exhaustive England grid. Coverage is intentionally explicit in the UI.
ENGLAND_DISCOVERY_ANCHORS = [
    ("London", 51.5072, -0.1276), ("Birmingham", 52.4862, -1.8904),
    ("Manchester", 53.4808, -2.2426), ("Liverpool", 53.4084, -2.9916),
    ("Leeds", 53.8008, -1.5491), ("Sheffield", 53.3811, -1.4701),
    ("Newcastle", 54.9783, -1.6178), ("Sunderland", 54.9069, -1.3838),
    ("Nottingham", 52.9548, -1.1581), ("Leicester", 52.6369, -1.1398),
    ("Coventry", 52.4068, -1.5197), ("Worcester", 52.1936, -2.2216),
    ("Bristol", 51.4545, -2.5879), ("Bath", 51.3758, -2.3599),
    ("Exeter", 50.7184, -3.5339), ("Plymouth", 50.3755, -4.1427),
    ("Southampton", 50.9097, -1.4044), ("Portsmouth", 50.8198, -1.0880),
    ("Brighton", 50.8225, -0.1372), ("Canterbury", 51.2802, 1.0789),
    ("Oxford", 51.7520, -1.2577), ("Cambridge", 52.2053, 0.1218),
    ("Norwich", 52.6309, 1.2974), ("Peterborough", 52.5695, -0.2405),
    ("Milton Keynes", 52.0406, -0.7594), ("Chelmsford", 51.7356, 0.4685),
    ("Ipswich", 52.0567, 1.1482), ("Carlisle", 54.8925, -2.9329),
    ("Lancaster", 54.0466, -2.8007), ("Blackpool", 53.8175, -3.0357),
    ("York", 53.9590, -1.0815), ("Kingston upon Hull", 53.7676, -0.3274),
    ("Stoke-on-Trent", 53.0027, -2.1794), ("Chester", 53.1934, -2.8931),
    ("Gloucester", 51.8642, -2.2382), ("Hereford", 52.0567, -2.7160),
    ("Truro", 50.2632, -5.0510), ("Torquay", 50.4619, -3.5253),
    ("Dover", 51.1279, 1.3134), ("Eastbourne", 50.7680, 0.2905),
]

def _places_search(api_key, location):
    url = "https://places.googleapis.com/v1/places:searchText"
    body = {
        "textQuery": "funeral director",
        "pageSize": 20,
        "locationBias": {"circle": {
            "center": {"latitude": location[1], "longitude": location[2]},
            "radius": 30000
        }},
        "languageCode": "en-GB",
        "regionCode": "GB"
    }
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.nationalPhoneNumber,places.websiteUri,places.googleMapsUri,places.location,places.primaryType"
        }
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.loads(response.read().decode("utf-8")).get("places", [])
    except urllib.error.HTTPError as exc:
        # Preserve Google's structured error response without exposing the API key.
        try:
            raw_error = exc.read().decode("utf-8", errors="replace")
            payload = json.loads(raw_error) if raw_error else {}
            google_error = payload.get("error", {})
            message = google_error.get("message") or raw_error or exc.reason
            status = google_error.get("status")
            code = google_error.get("code") or exc.code
            detail = f"Google Places API HTTP {code}"
            if status:
                detail += f" ({status})"
            detail += f": {message}"
        except Exception:
            detail = f"Google Places API HTTP {exc.code}: {exc.reason}"
        raise RuntimeError(detail) from exc

@celery_app.task(name="everguide.discovery.run", bind=True)
def run_provider_discovery(self, run_id: int):
    db = SessionLocal()
    run = db.get(DiscoveryRun, run_id)
    if not run:
        db.close()
        return {"status": "missing", "run_id": run_id}
    run.status = "running"
    run.started_at = datetime.now(timezone.utc)
    db.commit()
    try:
        if not settings.google_places_api_key:
            raise RuntimeError("Google Places API key is not configured. Add GOOGLE_PLACES_API_KEY to .env and restart the services.")
        seen = set()
        for location in ENGLAND_DISCOVERY_ANCHORS:
            run.locations_attempted += 1
            places = _places_search(settings.google_places_api_key, location)
            for place in places:
                place_id = place.get("id")
                if not place_id or place_id in seen:
                    continue
                seen.add(place_id)
                run.places_found += 1

                # Google Place IDs may be retained; other Google Places content
                # is deliberately not persisted pending a formal terms review.
                prior = db.query(SourceObservation).filter(
                    SourceObservation.source_type == "google_places",
                    SourceObservation.observed_data["google_place_id"].as_string() == place_id
                ).first()
                if prior:
                    prior.observed_data = {
                        "google_place_id": place_id,
                        "discovery_anchor": location[0],
                        "data_policy": "place_id_only"
                    }
                    prior.retrieved_at = datetime.now(timezone.utc)
                    prior.review_status = "pending"
                else:
                    db.add(SourceObservation(
                        source_type="google_places",
                        source_name="Google Places (Place ID reference)",
                        source_url=None,
                        confidence=None,
                        observed_data={
                            "google_place_id": place_id,
                            "discovery_anchor": location[0],
                            "data_policy": "place_id_only"
                        },
                        review_status="pending",
                        notes="Place ID reference only. Business details are not retained from Google pending terms, attribution and retention review."
                    ))
                    run.observations_created += 1
            db.commit()
        run.status = "completed"
        run.completed_at = datetime.now(timezone.utc)
        db.add(AuditEvent(entity_type="discovery_run", entity_id=run.id, action="completed",
                          detail={"places_found": run.places_found, "observations_created": run.observations_created}))
        db.commit()
        return {"status": run.status, "run_id": run.id, "places_found": run.places_found}
    except Exception as exc:
        db.rollback()
        run = db.get(DiscoveryRun, run_id)
        run.status = "failed"
        run.error_message = str(exc)[:2000]
        run.completed_at = datetime.now(timezone.utc)
        db.add(AuditEvent(entity_type="discovery_run", entity_id=run.id, action="failed",
                          detail={"error": run.error_message}))
        db.commit()
        raise
    finally:
        db.close()

@celery_app.task(name="everguide.system.ping")
def ping():
    return {"status": "ok", "task": "everguide.system.ping"}


def _fetch_permitted_homepage(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise RuntimeError("Only HTTPS source URLs are eligible for automated checks.")
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    robot = urllib.robotparser.RobotFileParser()
    robot.set_url(robots_url)
    try:
        robot.read()
    except Exception:
        raise RuntimeError("Could not verify robots.txt; source was not fetched.")
    agent = "EverguideEvidenceBot"
    if not robot.can_fetch(agent, url):
        raise RuntimeError("robots.txt does not permit this fetch.")
    request = urllib.request.Request(url, headers={"User-Agent": agent + "/0.5 (+https://everguide.example/contact)"})
    with urllib.request.urlopen(request, timeout=15) as response:
        content_type = response.headers.get("Content-Type", "").lower()
        if "text/html" not in content_type:
            raise RuntimeError("Source did not return HTML; no content was retained.")
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise RuntimeError("Homepage exceeded the 2 MB safety limit.")
        text = raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
        title = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", title_match.group(1))).strip())[:500] if title_match else None
        return response.status, title, hashlib.sha256(raw).hexdigest()

# Automated technical eligibility checks. robots.txt is a crawl instruction only; it does not grant copyright/database rights or permission to republish.\n@celery_app.task(name="everguide.enrichment.check_approved_sources")
def check_approved_sources():
    db = SessionLocal()
    checked = 0
    try:
        sources = db.query(SourcePermission).filter(SourcePermission.permission_status.in_(["automated_check", "approved"])).all()
        for source in sources:
            status, http_status, title, digest, detail = "checked", None, None, None, None
            try:
                http_status, title, digest = _fetch_permitted_homepage(source.source_url)
            except Exception as exc:
                status, detail = "blocked_or_failed", str(exc)[:1000]
            db.add(WebsiteEvidenceCheck(source_permission_id=source.id, provider_id=source.provider_id, status=status, http_status=http_status, page_title=title, content_sha256=digest, detail=detail))
            checked += 1
            db.commit()
        return {"status":"completed", "sources_checked":checked}
    finally:
        db.close()


@celery_app.task(name="everguide.enrichment.discover_provider_websites")
def discover_provider_websites():
    """Search independently for provider-owned website candidates by England region."""
    from urllib.parse import urlparse
    from app.models import WebsiteDiscoveryResult
    from app.search_providers import search_web, SearchProviderError
    db = SessionLocal()
    searches = 0
    saved = 0
    excluded_domains = {"nafd.org.uk", "funeral-directory.co.uk", "saif.org.uk"}
    try:
        for region, lat, lon in ENGLAND_DISCOVERY_ANCHORS:
            query = f"funeral directors {region} England official website"
            try:
                results = search_web(query, provider=settings.search_provider,
                                     brave_api_key=settings.brave_search_api_key, count=10)
            except SearchProviderError as exc:
                raise RuntimeError(str(exc)) from exc
            searches += 1
            for item in results:
                url = item.get("url")
                title = (item.get("title") or "").strip()
                if not url or not title:
                    continue
                parsed = urlparse(url)
                if parsed.scheme != "https" or not parsed.hostname:
                    continue
                domain = parsed.hostname.lower().removeprefix("www.")
                if domain in excluded_domains or any(domain.endswith("." + x) for x in excluded_domains):
                    continue
                existing = db.query(WebsiteDiscoveryResult).filter(WebsiteDiscoveryResult.result_url == url).first()
                if existing:
                    continue
                db.add(WebsiteDiscoveryResult(query_region=region, query_text=query, result_title=title[:500],
                    result_url=url[:1000], result_domain=domain[:255],
                    result_snippet=(item.get("description") or "")[:4000], source_provider=item.get("provider", settings.search_provider), status="candidate"))
                saved += 1
            db.commit()
        db.add(AuditEvent(entity_type="website_discovery", entity_id=0, action="completed",
                          detail={"regional_searches": searches, "candidates_saved": saved}))
        db.commit()
        return {"status":"completed", "regional_searches":searches, "candidates_saved":saved}
    finally:
        db.close()

@celery_app.task(name="everguide.automation.weekly_discovery_cycle")
def weekly_discovery_cycle():
    """Run regional web discovery, then queue one bounded verification batch."""
    from celery import chain
    return chain(discover_provider_websites.s(), enqueue_scheduled_verification.s()).apply_async().id


@celery_app.task(name="everguide.automation.enqueue_scheduled_verification")
def enqueue_scheduled_verification(discovery_result):
    from app.models import WebsiteVerificationRun
    db = SessionLocal()
    try:
        active = db.query(WebsiteVerificationRun).filter(WebsiteVerificationRun.status.in_(["queued", "running"])).first()
        if active:
            return {"status": "skipped_active_verification", "run_id": active.id, "discovery": discovery_result}
        run = WebsiteVerificationRun(status="queued", requested_limit=250, total=0, checked=0, outcomes={})
        db.add(run); db.commit(); db.refresh(run)
        task = verify_website_candidates.delay(limit=250, run_id=run.id)
        run.celery_task_id = task.id; db.commit()
        return {"status": "verification_queued", "run_id": run.id, "task_id": task.id, "discovery": discovery_result}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(name="everguide.website.verify_candidates")
def verify_website_candidates(limit=50, run_id=None):
    """Run conservative robots-aware technical checks on a bounded candidate batch."""
    from app.models import WebsiteDiscoveryResult, WebsiteVerification, Provider, Branch, SourceObservation, AuditEvent
    from app.website_checks import verify_candidate
    from app.routers.website_discovery import _classify
    db = SessionLocal()
    checked = 0
    outcomes = {}
    run = None
    try:
        if run_id is not None:
            from app.models import WebsiteVerificationRun
            run = db.query(WebsiteVerificationRun).filter(WebsiteVerificationRun.id == run_id).first()
            if run:
                run.status = "running"; run.started_at = datetime.now(timezone.utc); db.commit()
        # Include both never-checked candidates and candidates checked by earlier
        # releases. v1.1 broadens extraction, so the existing backlog must be
        # reassessed under the new rules rather than silently skipped.
        pool = (db.query(WebsiteDiscoveryResult)
                .filter(WebsiteDiscoveryResult.status.in_(["candidate", "verification_checked"]))
                .order_by(WebsiteDiscoveryResult.id.asc()).limit(1000).all())
        rows = [row for row in pool if _classify(row.result_title, row.result_snippet or "", row.result_domain) == "provider_candidate"][:max(1, min(int(limit), 250))]
        if run:
            run.total = len(rows); db.commit()
        for candidate in rows:
            try:
                result = verify_candidate(candidate.result_url)
            except Exception as exc:
                result = {"status": "check_blocked_or_failed", "final_url": None,
                          "http_status": None, "content_type": None, "page_title": None,
                          "robots_allowed": None, "content_sha256": None,
                          "detail": str(exc)[:1000]}
            verification = WebsiteVerification(candidate_id=candidate.id, **result)
            db.add(verification)
            db.flush()
            candidate.status = "verification_checked"
            approval_state = "not_eligible"
            extracted = result.get("extracted_data")
            if result.get("status") == "reachable" and extracted:
                # Conservative duplicate gate: exact normalized business name or postcode collision
                # sends the candidate to exception review; existing records are never overwritten.
                norm = re.sub(r"[^a-z0-9]", "", extracted["name"].lower())
                providers = db.query(Provider).all()
                name_collision = any(re.sub(r"[^a-z0-9]", "", p.trading_name.lower()) == norm for p in providers)
                postcode_collision = bool(extracted.get("postcode") and db.query(Branch).filter(Branch.postcode == extracted["postcode"]).first())
                domain_collision = db.query(Provider).filter(Provider.website.ilike(f"%{candidate.result_domain}%")).first() is not None
                if name_collision or postcode_collision or domain_collision:
                    candidate.status = "auto_approval_held_possible_duplicate"
                    approval_state = "held_possible_duplicate"
                else:
                    candidate.status = "held_quality_review"
                    approval_state = "held_quality_review"
                    db.add(AuditEvent(entity_type="website_candidate", entity_id=candidate.id, action="publication_held_for_human_approval",
                        detail={"verification_id": verification.id, "source_url": candidate.result_url,
                            "extracted_name": extracted.get("name"), "confidence": extracted.get("confidence"),
                            "reason": "Everguide publication requires explicit human approval; automated checks only create review evidence."}))
            # A candidate that did not qualify under the expanded rules is marked
            # as reassessed so future batches do not loop over the same negative
            # result. Duplicate holds and published providers retain their explicit
            # terminal statuses. Verification evidence remains in its own table.
            if approval_state == "not_eligible":
                candidate.status = "reassessed_not_eligible"
                db.add(AuditEvent(entity_type="website_candidate", entity_id=candidate.id,
                    action="candidate_reassessed_not_eligible",
                    detail={"verification_id": verification.id, "source_url": candidate.result_url,
                            "reason": "no_sufficient_provider_identity_evidence_under_v1_1_rules"}))
            outcomes[approval_state] = outcomes.get(approval_state, 0) + 1
            outcomes[result["status"]] = outcomes.get(result["status"], 0) + 1
            checked += 1
            if run:
                run.checked = checked; run.outcomes = dict(outcomes)
            db.commit()
        if run:
            run.status = "completed"; run.completed_at = datetime.now(timezone.utc); run.checked = checked; run.outcomes = dict(outcomes); db.commit()
        db.add(AuditEvent(entity_type="website_verification", entity_id=run.id if run else 0, action="batch_completed",
                          detail={"checked": checked, "outcomes": outcomes}))
        db.commit()

        # Automatically continue through the backlog in bounded batches. Each batch
        # is independently tracked, committed and recoverable; no unbounded task is run.
        if run_id is not None and checked > 0:
            from app.models import WebsiteVerificationRun
            from app.routers.website_discovery import _classify
            remaining_pool = (db.query(WebsiteDiscoveryResult)
                .filter(WebsiteDiscoveryResult.status.in_(["candidate", "verification_checked"]))
                .order_by(WebsiteDiscoveryResult.id.asc()).limit(5000).all())
            has_remaining = any(
                _classify(row.result_title, row.result_snippet or "", row.result_domain) == "provider_candidate"
                for row in remaining_pool
            )
            if has_remaining:
                next_run = WebsiteVerificationRun(status="queued", requested_limit=250, total=0, checked=0, outcomes={})
                db.add(next_run); db.commit(); db.refresh(next_run)
                try:
                    next_task = verify_website_candidates.delay(limit=250, run_id=next_run.id)
                    next_run.celery_task_id = next_task.id; db.commit()
                except Exception as queue_exc:
                    db.rollback()
                    failed_next = db.query(WebsiteVerificationRun).filter(WebsiteVerificationRun.id == next_run.id).first()
                    if failed_next:
                        failed_next.status = "failed"
                        failed_next.error_message = ("Automatic continuation could not be queued: " + str(queue_exc))[:1000]
                        failed_next.completed_at = datetime.now(timezone.utc)
                        db.commit()
        return {"status": "completed", "checked": checked, "outcomes": outcomes}
    except Exception as exc:
        # A failed flush/commit leaves the SQLAlchemy session unusable until rollback.
        # Roll back first, then reload the batch row in a clean transaction so the
        # dashboard can reliably show the failure instead of masking it with
        # PendingRollbackError. Previously committed candidate checks remain intact.
        db.rollback()
        if run_id is not None:
            try:
                from app.models import WebsiteVerificationRun
                failed_run = db.query(WebsiteVerificationRun).filter(WebsiteVerificationRun.id == run_id).first()
                if failed_run:
                    failed_run.status = "failed"
                    failed_run.error_message = str(exc)[:1000]
                    failed_run.completed_at = datetime.now(timezone.utc)
                    db.commit()
            except Exception:
                db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(name="everguide.companies_house.discover_websites")
def discover_company_websites(run_id: int):
    """Search and cautiously verify official-site leads linked to Companies House candidates.

    Work is committed in small batches. A provider/search outage pauses the run; it
    never converts the current legal-entity candidate into a permanent failure.
    No Provider, Branch or publication rows are created.
    """
    import time
    import ipaddress
    from urllib.parse import urlsplit
    from sqlalchemy import or_
    from app.models import CompaniesHouseCandidate, CompanyWebsiteCandidate, CompanyWebsiteDiscoveryRun, AuditEvent
    from app.search_providers import search_web, SearchProviderError
    from app.website_checks import verify_candidate
    db=SessionLocal()
    run=db.get(CompanyWebsiteDiscoveryRun,run_id)
    if not run: db.close(); return {"status":"missing","run_id":run_id}
    run.status="running"; run.started_at=run.started_at or datetime.now(timezone.utc); db.commit()
    batch_size=max(1,min(int(run.batch_size or 25),50))
    try:
        query=(db.query(CompaniesHouseCandidate).filter(CompaniesHouseCandidate.company_status=="active",
            CompaniesHouseCandidate.profile_status=="completed", CompaniesHouseCandidate.classification.in_(["likely_funeral_director","uncertain"]),
            CompaniesHouseCandidate.website_discovery_status.in_(["not_requested","search_failed"])).order_by(
            (CompaniesHouseCandidate.classification=="likely_funeral_director").desc(),CompaniesHouseCandidate.id.asc()).limit(batch_size))
        companies=query.all()
        if not companies:
            run.status="completed"; run.completed_at=datetime.now(timezone.utc); db.commit()
            return {"status":"completed","run_id":run_id,"processed":run.processed_candidates}
        excluded={"nafd.org.uk","funeral-directory.co.uk","saif.org.uk","yell.com","facebook.com","instagram.com","linkedin.com","trustpilot.com"}
        for company in companies:
            address=company.registered_office_address or {}
            town=(address.get("locality") or address.get("postal_town") or address.get("town") or "").strip()
            q=f'"{company.company_name}" funeral director {town} England official website'.strip()
            try:
                results=search_web(q,provider=settings.search_provider,brave_api_key=settings.brave_search_api_key,count=5)
            except SearchProviderError as exc:
                run.status="paused"; run.error_message=str(exc)[:1200]; run.completed_at=datetime.now(timezone.utc)
                db.add(AuditEvent(entity_type="company_website_discovery",entity_id=run.id,action="paused_search_provider_error",detail={"company_number":company.company_number,"error":run.error_message,"processed":run.processed_candidates}))
                db.commit(); return {"status":"paused","run_id":run_id,"reason":run.error_message}
            accepted=[]
            for rank,item in enumerate(results,1):
                url=(item.get("url") or "").strip(); title=(item.get("title") or "").strip()
                if not url or not title: continue
                parsed=urlsplit(url)
                if parsed.scheme.lower()!="https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443): continue
                domain=parsed.hostname.lower().removeprefix("www.")
                if domain in excluded or any(domain.endswith("."+x) for x in excluded): continue
                if any(x in domain for x in ("gov.uk","council","directory","compare")): continue
                tokens={x for x in re.findall(r"[a-z0-9]+",company.company_name.lower()) if len(x)>2 and x not in {"limited","ltd","plc","the","and","funeral","directors","director","services"}}
                hay=" ".join([title,item.get("description") or "",domain]).lower()
                hits=sum(1 for token in tokens if token in hay)
                score=min(1.0,hits/max(1,min(len(tokens),4)))
                accepted.append((score,rank,item,domain))
            accepted.sort(key=lambda x:(x[0],-x[1]),reverse=True)
            if not accepted:
                company.website_discovery_status="no_results"; company.website_discovery_checked_at=datetime.now(timezone.utc); company.website_discovery_error=None
                run.no_results+=1
            else:
                for result_index,(score,rank,item,domain) in enumerate(accepted[:3],1):
                    url=item["url"][:1000]
                    exists=db.query(CompanyWebsiteCandidate).filter(CompanyWebsiteCandidate.companies_house_candidate_id==company.id,CompanyWebsiteCandidate.result_url==url).first()
                    if exists: continue
                    row=CompanyWebsiteCandidate(companies_house_candidate_id=company.id,discovery_run_id=run.id,
                        result_title=(item.get("title") or "")[:500],result_url=url,result_domain=domain[:255],
                        result_snippet=(item.get("description") or "")[:1500],search_provider=item.get("provider") or settings.search_provider,match_score=score)
                    db.add(row); db.flush(); run.results_found+=1
                    # Verify only the strongest two leads per company; all extracted fields remain proposals.
                    if result_index<=2:
                        try:
                            verified=verify_candidate(url)
                            row.verification_status="identity_signals_found" if verified.get("status")=="reachable" and verified.get("extracted_data") else verified.get("status","checked")
                            row.final_url=verified.get("final_url"); row.http_status=verified.get("http_status")
                            row.robots_allowed=verified.get("robots_allowed"); row.page_title=verified.get("page_title")
                            row.content_sha256=verified.get("content_sha256"); row.extracted_data={k:v for k,v in (verified.get("extracted_data") or {}).items() if k in {"name","street","town","postcode","telephone","website","source_type","country","confidence","funeral_signals","has_complete_branch_address"}} or None
                            row.detail=verified.get("detail"); row.checked_at=datetime.now(timezone.utc); run.websites_checked+=1
                            if row.verification_status=="identity_signals_found": run.identity_signals+=1
                        except Exception as exc:
                            row.verification_status="check_blocked_or_failed"; row.detail=str(exc)[:1000]; row.checked_at=datetime.now(timezone.utc); run.websites_checked+=1
                company.website_discovery_status="searched"; company.website_discovery_checked_at=datetime.now(timezone.utc); company.website_discovery_error=None
            run.processed_candidates+=1
            db.commit()
            time.sleep(1.1)
        # Queue the next bounded batch. This is a single tracked run, not an unbounded worker loop.
        remaining=db.query(CompaniesHouseCandidate.id).filter(CompaniesHouseCandidate.company_status=="active",
            CompaniesHouseCandidate.profile_status=="completed",CompaniesHouseCandidate.classification.in_(["likely_funeral_director","uncertain"]),
            CompaniesHouseCandidate.website_discovery_status.in_(["not_requested","search_failed"])).first()
        if remaining:
            next_task=discover_company_websites.delay(run.id); run.celery_task_id=next_task.id; db.commit()
            return {"status":"running","run_id":run.id,"processed":run.processed_candidates,"next_task_id":next_task.id}
        run.status="completed"; run.completed_at=datetime.now(timezone.utc); run.error_message=None
        db.add(AuditEvent(entity_type="company_website_discovery",entity_id=run.id,action="completed",detail={"processed":run.processed_candidates,"results_found":run.results_found,"websites_checked":run.websites_checked,"identity_signals":run.identity_signals,"no_results":run.no_results,"publication_changes":0}))
        db.commit()
        return {"status":"completed","run_id":run.id,"processed":run.processed_candidates,"results_found":run.results_found,"identity_signals":run.identity_signals}
    except Exception as exc:
        db.rollback(); run=db.get(CompanyWebsiteDiscoveryRun,run_id)
        if run:
            run.status="paused"; run.error_message=f"Discovery paused safely: {type(exc).__name__}: {exc}"[:1200]; run.completed_at=datetime.now(timezone.utc)
            db.add(AuditEvent(entity_type="company_website_discovery",entity_id=run.id,action="paused_unexpected_error",detail={"error":run.error_message,"processed":run.processed_candidates}))
            db.commit()
        return {"status":"paused","run_id":run_id,"reason":str(exc)[:1000]}
    finally:
        db.close()
