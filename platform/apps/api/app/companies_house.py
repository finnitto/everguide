import base64, json, time, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from sqlalchemy import select
from app.celery_app import celery_app
from app.config import settings
from app.database import SessionLocal
from app.models import CompaniesHouseRun, CompaniesHouseCandidate, AuditEvent

BASE = "https://api.company-information.service.gov.uk/advanced-search/companies"
PAGE_SIZE = 5000

def _request_page(api_key: str, start_index: int, sic_codes: list[str]):
    params = {
        "company_status": "active",
        "sic_codes": ",".join(sic_codes),
        "size": PAGE_SIZE,
        "start_index": start_index,
    }
    url = BASE + "?" + urllib.parse.urlencode(params)
    token = base64.b64encode((api_key + ":").encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": "Basic " + token, "Accept": "application/json", "User-Agent": "Everguide/2.0 provider discovery"})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        if exc.code == 429:
            raise RuntimeError("Companies House API rate limit reached. The import can be retried later.") from exc
        raise RuntimeError(f"Companies House API returned HTTP {exc.code}: {detail}") from exc

@celery_app.task(name="everguide.companies_house.import_sic_companies", bind=True)
def import_companies_house_sic(self, run_id: int):
    return {"status": "disabled", "reason": "overture_first_source_policy", "run_id": run_id}
    db = SessionLocal()
    run = db.get(CompaniesHouseRun, run_id)
    if not run:
        db.close(); return {"status": "missing", "run_id": run_id}
    try:
        if not settings.companies_house_api_key:
            raise RuntimeError("Companies House API key is not configured. Add COMPANIES_HOUSE_API_KEY to .env and restart the services.")
        run.status = "running"; run.started_at = datetime.now(timezone.utc); db.commit()
        sic_codes = run.sic_codes or ["96030"]
        start = 0; total = None
        while total is None or start < total:
            payload = _request_page(settings.companies_house_api_key, start, sic_codes)
            items = payload.get("items", [])
            total = int(payload.get("total_results", len(items)))
            run.total_results = total; run.pages_fetched += 1
            run.api_items_per_page = int(payload.get("items_per_page", len(items)))
            for item in items:
                number = item.get("company_number")
                title = item.get("company_name") or item.get("title")
                if not number or not title:
                    continue
                address = item.get("registered_office_address") or {}
                # Companies House is the legal-entity discovery source. Do not
                # create a branch from its registered office address.
                candidate = db.scalar(select(CompaniesHouseCandidate).where(CompaniesHouseCandidate.company_number == number))
                if candidate is None:
                    candidate = CompaniesHouseCandidate(company_number=number, company_name=title)
                    db.add(candidate)
                run.imported += 1
                candidate.company_name = title
                candidate.company_status = item.get("company_status", "active")
                candidate.company_type = item.get("company_type")
                candidate.sic_codes = item.get("sic_codes") or []
                candidate.registered_office_address = address
                candidate.date_of_creation = item.get("date_of_creation")
                candidate.company_profile_url = item.get("links", {}).get("self")
                candidate.source_run_id = run.id
                candidate.classification = "funeral_related_unclassified"
                candidate.review_status = "candidate"
                candidate.raw_company_record = {k: item.get(k) for k in ("company_number", "company_name", "company_status", "company_type", "sic_codes", "date_of_creation", "registered_office_address", "links")}
                candidate.last_seen_at = datetime.now(timezone.utc)
            db.commit()
            if not items: break
            start += len(items)
            if start < total: time.sleep(0.65)
        run.unique_companies_seen = db.query(CompaniesHouseCandidate).count()
        run.status = "completed"; run.completed_at = datetime.now(timezone.utc)
        db.add(AuditEvent(entity_type="companies_house_run", entity_id=run.id, action="completed", detail={"sic_codes": sic_codes, "total_results": total, "imported_or_updated": run.imported, "pages_fetched": run.pages_fetched}))
        db.commit()
        return {"status": run.status, "run_id": run.id, "total_results": total, "imported": run.imported}
    except Exception as exc:
        db.rollback(); run = db.get(CompaniesHouseRun, run_id)
        run.status = "failed"; run.error_message = str(exc)[:2000]; run.completed_at = datetime.now(timezone.utc)
        db.add(AuditEvent(entity_type="companies_house_run", entity_id=run.id, action="failed", detail={"error": run.error_message}))
        db.commit(); raise
    finally:
        db.close()


class CompaniesHousePause(Exception):
    """A transient API condition that should pause the whole batch, not fail each candidate."""


def _rate_limit_resume_hint(headers):
    """Return a human-readable reset hint from standard or observed CH headers."""
    if not headers:
        return "Wait for the Companies House five-minute rate-limit window to reset before retrying."
    retry_after = headers.get("Retry-After")
    if retry_after:
        try:
            seconds = max(0, int(float(retry_after)))
            return f"Retry after approximately {seconds} seconds."
        except (TypeError, ValueError):
            try:
                reset_at = parsedate_to_datetime(retry_after)
                return f"Retry after {reset_at.astimezone(timezone.utc).isoformat()}."
            except (TypeError, ValueError, OverflowError):
                pass
    reset_epoch = headers.get("X-Ratelimit-Reset") or headers.get("X-RateLimit-Reset")
    if reset_epoch:
        try:
            reset_at = datetime.fromtimestamp(float(reset_epoch), tz=timezone.utc)
            return f"The reported rate-limit reset is {reset_at.isoformat()}."
        except (TypeError, ValueError, OverflowError):
            pass
    return "Wait for the Companies House five-minute rate-limit window to reset before retrying."


def _get_company_resource(api_key: str, path: str):
    """Fetch one profile. A 429/transient service error pauses the batch immediately."""
    url = "https://api.company-information.service.gov.uk" + path
    token = base64.b64encode((api_key + ":").encode()).decode()
    req = urllib.request.Request(url, headers={
        "Authorization": "Basic " + token,
        "Accept": "application/json",
        "User-Agent": "Everguide/2.4.0 company enrichment",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        # 1.1 seconds between all successful requests keeps a single worker well
        # below the documented 600 requests / 5 minute application limit.
        time.sleep(1.1)
        return payload
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        if exc.code == 404:
            time.sleep(1.1)
            return {}
        if exc.code == 429:
            hint = _rate_limit_resume_hint(exc.headers)
            raise CompaniesHousePause(
                "Companies House rate limit reached (HTTP 429). The enrichment batch has been paused "
                f"without changing the current candidate. {hint}"
            ) from exc
        if 500 <= exc.code <= 599 or exc.code in (401, 403):
            reason = "authentication/permission was rejected" if exc.code in (401, 403) else "the service returned a temporary server error"
            raise CompaniesHousePause(
                f"Companies House HTTP {exc.code}: {reason}. The batch has been paused "
                "without changing the current candidate; check the API key or retry later."
            ) from exc
        raise RuntimeError(f"Companies House profile API returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise CompaniesHousePause(
            f"Companies House connection failed ({str(exc)[:250]}). The batch has been paused "
            "without changing the current candidate; retry later."
        ) from exc

@celery_app.task(name="everguide.companies_house.enrich_profiles", bind=True)
def enrich_company_profiles(self, run_id: int):
    """Enrich active legal entities using the official company profile resource."""
    return {"status": "disabled", "reason": "overture_first_source_policy", "run_id": run_id}
    db = SessionLocal()
    run = db.get(CompaniesHouseRun, run_id)
    if not run:
        db.close(); return {"status": "missing", "run_id": run_id}
    try:
        if not settings.companies_house_api_key:
            raise RuntimeError("Companies House API key is not configured.")
        run.status = "enriching"; run.started_at = datetime.now(timezone.utc); run.completed_at = None
        run.error_message = None
        db.commit()
        candidates = db.query(CompaniesHouseCandidate).filter(
            CompaniesHouseCandidate.company_status == "active",
            CompaniesHouseCandidate.profile_status.in_(["not_requested", "failed"])
        ).order_by(CompaniesHouseCandidate.id.asc()).all()
        run.total_results = len(candidates); run.imported = 0; run.pages_fetched = 0; db.commit()
        for candidate in candidates:
            try:
                number = urllib.parse.quote(candidate.company_number, safe="")
                profile = _get_company_resource(settings.companies_house_api_key, f"/company/{number}")
                if not profile:
                    candidate.profile_status = "not_found"
                    candidate.company_profile = {}
                    candidate.profile_error = None
                else:
                    candidate.company_profile = {k: profile.get(k) for k in ("company_name", "company_number", "company_status", "type", "jurisdiction", "date_of_creation", "date_of_cessation", "sic_codes", "accounts", "confirmation_statement", "registered_office_address", "links") if profile.get(k) is not None}
                    candidate.profile_status = "completed"
                    candidate.profile_error = None
                # Previous-name history is deliberately not requested: the endpoint
                # returned HTTP 500 for valid company numbers in the observed run.
                candidate.previous_company_names = candidate.previous_company_names or []
            except CompaniesHousePause as exc:
                # Do not convert rate limits, outages or timeouts into candidate failures.
                # Leave the current candidate exactly as it was so the next run can resume it.
                run.status = "interrupted"
                run.error_message = str(exc)[:2000]
                run.completed_at = datetime.now(timezone.utc)
                db.add(AuditEvent(
                    entity_type="companies_house_run", entity_id=run.id,
                    action="profile_enrichment_paused",
                    detail={"processed": run.imported, "deferred_company_number": candidate.company_number,
                            "reason": run.error_message, "providers_created": 0, "branches_created": 0,
                            "published": 0}, actor="system-enrichment"
                ))
                db.commit()
                return {"status": "interrupted", "run_id": run.id, "processed": run.imported,
                        "deferred_company_number": candidate.company_number, "reason": run.error_message}
            except Exception as exc:
                candidate.profile_status = "failed"
                candidate.profile_error = str(exc)[:1000]
            candidate.profile_checked_at = datetime.now(timezone.utc)
            run.imported += 1
            db.commit()
        run.status = "completed"; run.completed_at = datetime.now(timezone.utc)
        run.unique_companies_seen = db.query(CompaniesHouseCandidate).filter(CompaniesHouseCandidate.profile_status == "completed").count()
        db.add(AuditEvent(entity_type="companies_house_run", entity_id=run.id, action="profile_enrichment_completed", detail={"processed": run.imported, "completed_profiles": run.unique_companies_seen, "failed": db.query(CompaniesHouseCandidate).filter(CompaniesHouseCandidate.profile_status == "failed").count(), "providers_created": 0, "branches_created": 0, "published": 0}, actor="system-enrichment"))
        db.commit()
        return {"status": "completed", "run_id": run.id, "processed": run.imported, "completed_profiles": run.unique_companies_seen}
    except Exception as exc:
        db.rollback(); run = db.get(CompaniesHouseRun, run_id)
        run.status = "failed"; run.error_message = str(exc)[:2000]; run.completed_at = datetime.now(timezone.utc)
        db.add(AuditEvent(entity_type="companies_house_run", entity_id=run.id, action="profile_enrichment_failed", detail={"error": run.error_message}, actor="system-enrichment"))
        db.commit(); raise
    finally:
        db.close()
