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

@celery_app.task(name="everguide.website.verify_candidates")
def verify_website_candidates(limit=50, run_id=None):
    """Run conservative robots-aware technical checks on a bounded candidate batch."""
    from app.models import WebsiteDiscoveryResult, WebsiteVerification
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
        pool = (db.query(WebsiteDiscoveryResult)
                .filter(WebsiteDiscoveryResult.status == "candidate")
                .order_by(WebsiteDiscoveryResult.id.asc()).limit(500).all())
        rows = [row for row in pool if _classify(row.result_title, row.result_snippet or "", row.result_domain) == "provider_candidate"][:max(1, min(int(limit), 50))]
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
            db.add(WebsiteVerification(candidate_id=candidate.id, **result))
            candidate.status = "verification_checked"
            outcomes[result["status"]] = outcomes.get(result["status"], 0) + 1
            checked += 1
            if run:
                run.checked = checked; run.outcomes = dict(outcomes)
            db.commit()
        if run:
            run.status = "completed"; run.completed_at = datetime.now(timezone.utc); run.checked = checked; run.outcomes = dict(outcomes); db.commit()
        db.add(AuditEvent(entity_type="website_verification", entity_id=0, action="batch_completed",
                          detail={"checked": checked, "outcomes": outcomes}))
        db.commit()
        return {"status": "completed", "checked": checked, "outcomes": outcomes}
    except Exception as exc:
        if run:
            run.status = "failed"; run.error_message = str(exc)[:1000]; run.completed_at = datetime.now(timezone.utc); db.commit()
        raise
    finally:
        db.close()
