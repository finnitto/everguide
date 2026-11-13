"""Persist and process Overture Places observations through the evidence-led pipeline.

The worker never treats Overture existence confidence as field verification.
Only first-party website evidence, source-level licence metadata, an official
ONS boundary check and collision checks can permit automatic publication.
"""
from __future__ import annotations

import json
import math
import re
import urllib.parse
import urllib.request
from collections import Counter
from difflib import SequenceMatcher
from datetime import datetime, timezone, timedelta

from app.celery_app import celery_app
from app.config import settings
from app.database import SessionLocal
from app.models import (
    AuditEvent, Branch, OvertureCandidate, OvertureImportRun, Provider,
    SourceObservation,
)
from app.overture_approval import assess_overture_candidate
from app.candidate_quality import DIRECTORY_DOMAINS, normalise_identity_name, normalise_phone, normalise_postcode
from app.website_checks import verify_candidate
from app.search_providers import search_web, SearchProviderError

ONS_QUERY_URL = (
    "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
    "Counties_and_Unitary_Authorities_December_2025_Boundaries_UK_BFE/"
    "FeatureServer/0/query"
)
ONS_BOUNDARY_CODE = "E06000034"


def _now():
    return datetime.now(timezone.utc)


def _float_or_none(value):
    try:
        parsed = float(value) if value not in (None, "") else None
        return parsed if parsed is None or math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def _as_sources(value):
    if isinstance(value, str):
        try:
            return json.loads(value or "[]")
        except ValueError:
            return []
    return value if isinstance(value, list) else []


def _point_in_ring(lon, lat, ring):
    inside = False
    if not ring or len(ring) < 4:
        return False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-30) + xi):
            inside = not inside
        j = i
    return inside


def _point_in_polygon(lon, lat, polygon):
    if not polygon or not _point_in_ring(lon, lat, polygon[0]):
        return False
    return not any(_point_in_ring(lon, lat, ring) for ring in polygon[1:])


def _fetch_ons_geometry():
    params = urllib.parse.urlencode({
        "where": f"CTYUA25CD='{ONS_BOUNDARY_CODE}'",
        "outFields": "CTYUA25CD,CTYUA25NM",
        "returnGeometry": "true", "outSR": "4326", "f": "geojson",
    })
    request = urllib.request.Request(ONS_QUERY_URL + "?" + params,
        headers={"User-Agent": "EverguideBoundaryCheck/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    features = payload.get("features") or []
    if len(features) != 1 or (features[0].get("properties") or {}).get("CTYUA25CD") != ONS_BOUNDARY_CODE:
        raise RuntimeError("ONS did not return exactly the expected Thurrock boundary E06000034.")
    geometry = features[0].get("geometry") or {}
    if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        raise RuntimeError("ONS Thurrock boundary geometry has an unsupported type.")
    coords = geometry.get("coordinates")
    polygons = [coords] if geometry.get("type") == "Polygon" else coords
    if not isinstance(polygons, list) or not polygons:
        raise RuntimeError("ONS Thurrock boundary geometry contains no polygon coordinates.")
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise RuntimeError("ONS Thurrock boundary contains an invalid polygon.")
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                raise RuntimeError("ONS Thurrock boundary contains an invalid or unclosed ring.")
            for coordinate in ring:
                if not isinstance(coordinate, (list, tuple)) or len(coordinate) < 2:
                    raise RuntimeError("ONS Thurrock boundary contains an invalid coordinate.")
                lon, lat = float(coordinate[0]), float(coordinate[1])
                if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
                    raise RuntimeError("ONS Thurrock boundary contains an out-of-range coordinate.")
    return geometry



def _fetch_ons_england_geometry():
    """Fetch and validate England county/unitary-authority polygons from ONS."""
    params = urllib.parse.urlencode({
        "where": "CTYUA25CD LIKE 'E%'", "outFields": "CTYUA25CD,CTYUA25NM",
        "returnGeometry": "true", "outSR": "4326", "f": "geojson", "resultRecordCount": 1000,
    })
    request = urllib.request.Request(ONS_QUERY_URL + "?" + params,
        headers={"User-Agent": "EverguideBoundaryCheck/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))
    features = payload.get("features") or []
    if len(features) < 100:
        raise RuntimeError("ONS did not return the expected England-wide county/unitary-authority boundary set.")
    polygons = []
    for feature in features:
        properties = feature.get("properties") or {}
        code = str(properties.get("CTYUA25CD") or "")
        geometry = feature.get("geometry") or {}
        if not code.startswith("E") or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise RuntimeError("ONS England boundary response contains an unexpected feature.")
        coordinates = geometry.get("coordinates") or []
        feature_polygons = [coordinates] if geometry.get("type") == "Polygon" else coordinates
        for polygon in feature_polygons:
            if not isinstance(polygon, list) or not polygon:
                raise RuntimeError("ONS England boundary contains an invalid polygon.")
            for ring in polygon:
                if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                    raise RuntimeError("ONS England boundary contains an invalid or unclosed ring.")
                for coordinate in ring:
                    if not isinstance(coordinate, (list, tuple)) or len(coordinate) < 2:
                        raise RuntimeError("ONS England boundary contains an invalid coordinate.")
                    lon, lat = float(coordinate[0]), float(coordinate[1])
                    if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
                        raise RuntimeError("ONS England boundary contains an out-of-range coordinate.")
        polygons.extend(feature_polygons)
    if len(polygons) < 100:
        raise RuntimeError("ONS England boundary geometry is incomplete.")
    return {"type": "MultiPolygon", "coordinates": polygons}

def _inside_boundary(geometry, lon, lat):
    if lon is None or lat is None:
        return None
    try:
        lon, lat = float(lon), float(lat)
    except (TypeError, ValueError):
        return None
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    kind, coords = geometry["type"], geometry["coordinates"]
    polygons = [coords] if kind == "Polygon" else coords
    return any(_point_in_polygon(lon, lat, polygon) for polygon in polygons)


def _https_website(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = urllib.parse.urlsplit(raw if "://" in raw else "https://" + raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return None
    return urllib.parse.urlunsplit(("https", parsed.netloc, parsed.path or "/", parsed.query, ""))


def _existing_provider_match(db, row):
    """Return (conflict, safe_parent_provider) without merging or overwriting."""
    name_key = normalise_identity_name(row.get("name"))
    postcode_key = normalise_postcode(row.get("postcode"))
    phone_key = normalise_phone(row.get("phone"))
    website = _https_website(row.get("website")) or ""
    domain = (urllib.parse.urlsplit(website).hostname or "").lower().removeprefix("www.")
    for provider in db.query(Provider).all():
        provider_name_key = normalise_identity_name(provider.trading_name)
        purl = _https_website(provider.website) or ""
        pdomain = (urllib.parse.urlsplit(purl).hostname or "").lower().removeprefix("www.")
        same_name = bool(name_key and provider_name_key == name_key)
        same_domain = bool(domain and pdomain and (domain == pdomain or domain.endswith("." + pdomain) or pdomain.endswith("." + domain)))
        if same_name or same_domain:
            if not (same_name and same_domain):
                return True, None
            # Same provider identity and official domain: a distinct verified
            # postcode can be added as a new branch. Existing branch locations
            # are never overwritten or merged.
            for branch in provider.branches:
                if postcode_key and normalise_postcode(branch.postcode) == postcode_key:
                    return True, None
            return False, provider
    for branch in db.query(Branch).all():
        if postcode_key and normalise_postcode(branch.postcode) == postcode_key:
            if phone_key and normalise_phone(branch.telephone) == phone_key:
                return True, None
    return False, None


def _overture_duplicate_conflict(db, candidate):
    name_key = normalise_identity_name(candidate.candidate_name)
    postcode_key = normalise_postcode(candidate.postcode)
    if not name_key or not postcode_key:
        return False
    peers = db.query(OvertureCandidate).filter(
        OvertureCandidate.id != candidate.id,
        OvertureCandidate.postcode == candidate.postcode,
    ).all()
    return any(normalise_identity_name(peer.candidate_name) == name_key for peer in peers)


def _normalised_assessment_row(raw):
    row = dict(raw)
    row["sources_json"] = _as_sources(row.get("sources_json"))
    row["website"] = _https_website(row.get("website"))
    if not row["website"]:
        websites = _as_sources(raw.get("websites_json"))
        if websites and isinstance(websites[0], str):
            row["website"] = _https_website(websites[0])
    return row


def _candidate_evidence_matches(raw, extracted):
    if not extracted:
        return False
    candidate_raw = str(raw.get("name") or "").lower()
    evidence_raw = str(extracted.get("name") or "").lower()
    candidate_name = normalise_identity_name(candidate_raw)
    evidence_name = normalise_identity_name(evidence_raw)
    stop = {"the", "and", "funeral", "funerals", "director", "directors", "service", "services", "limited", "ltd", "plc"}
    candidate_tokens = {token for token in re.findall(r"[a-z0-9]+", candidate_raw) if token not in stop}
    evidence_tokens = {token for token in re.findall(r"[a-z0-9]+", evidence_raw) if token not in stop}
    token_match = (len(candidate_tokens & evidence_tokens) / max(1, min(len(candidate_tokens), len(evidence_tokens)))) >= 0.8
    name_match = bool(candidate_name and evidence_name and (SequenceMatcher(None, candidate_name, evidence_name).ratio() >= 0.72 or token_match))
    postcode_match = normalise_postcode(raw.get("postcode")) == normalise_postcode(extracted.get("postcode"))
    phone_match = normalise_phone(raw.get("phone")) == normalise_phone(extracted.get("telephone"))
    return name_match and postcode_match and phone_match


def _verify_overture_website(raw, initial_url):
    """Try the Overture website, then permitted web-search leads if needed."""
    candidates = []
    if initial_url:
        candidates.append((initial_url, "overture_website"))
    query = f'"{raw.get("name", "")}" funeral directors {raw.get("postcode", "")} official website UK'
    search_error = None
    if settings.brave_search_api_key:
        try:
            results = search_web(query, provider=settings.search_provider,
                brave_api_key=settings.brave_search_api_key, count=8)
            seen = {url for url, _ in candidates}
            for item in results:
                url = _https_website(item.get("url"))
                if not url or url in seen:
                    continue
                domain = (urllib.parse.urlsplit(url).hostname or "").lower().removeprefix("www.")
                if any(domain == blocked or domain.endswith("." + blocked) for blocked in DIRECTORY_DOMAINS):
                    continue
                candidates.append((url, "brave_search"))
                seen.add(url)
        except SearchProviderError as exc:
            search_error = str(exc)[:500]
    best_mismatch = None
    last_verification = None
    for url, discovery_source in candidates[:4]:
        try:
            verification = verify_candidate(url)
        except Exception as exc:
            last_verification = {"status": "check_blocked_or_failed", "detail": str(exc)[:800], "robots_allowed": None, "final_url": url}
            continue
        last_verification = verification
        extracted = verification.get("extracted_data") if verification else None
        if extracted and _candidate_evidence_matches(raw, extracted):
            verification["discovery_source"] = discovery_source
            verification["search_query"] = query if discovery_source == "brave_search" else None
            return url, verification
        if extracted and best_mismatch is None:
            best_mismatch = (url, verification)
    if best_mismatch:
        url, verification = best_mismatch
        verification["discovery_source"] = "identity_or_branch_mismatch"
        verification["search_error"] = search_error
        return url, verification
    if last_verification:
        last_verification["search_error"] = search_error
        return initial_url, last_verification
    return initial_url, {"status": "website_missing", "final_url": initial_url,
        "robots_allowed": None, "detail": search_error or "No first-party website candidate could be verified."}


@celery_app.task(name="everguide.overture.import_records", bind=True)
def import_overture_records(self, run_id: int, records: list[dict], source_release: str | None = None, finalize: bool = True):
    db = SessionLocal()
    run = db.get(OvertureImportRun, run_id)
    if not run:
        db.close()
        return {"status": "missing", "run_id": run_id}
    run.status = "running"
    run.started_at = _now()
    ingestion_method = ((run.outcomes or {}).get("_meta", {}) or {}).get("ingestion_method", "manual_csv")
    if ingestion_method == "scheduled_parquet":
        run.records_received = (run.records_received or 0) + len(records)
    else:
        run.records_received = max(run.records_received or 0, len(records))
    db.commit()
    imported = updated = 0
    try:
        for raw in records:
            gers_id = str(raw.get("gers_id") or raw.get("id") or "").strip()
            name = str(raw.get("name") or "").strip()
            if not gers_id or not name:
                continue
            candidate = db.query(OvertureCandidate).filter(OvertureCandidate.gers_id == gers_id).first()
            if candidate is None:
                candidate = OvertureCandidate(gers_id=gers_id, candidate_name=name[:240], postcode=str(raw.get("postcode") or "")[:12])
                db.add(candidate)
                db.flush()
                imported += 1
            else:
                updated += 1
                candidate.candidate_name = name[:240]
                candidate.postcode = str(raw.get("postcode") or "")[:12]
            candidate.source_release = str(source_release or raw.get("version") or "")[:80] or None
            candidate.raw_data = dict(raw)
            candidate.last_import_run_id = run.id
            # Keep prior approved/published outcome stable; new source versions
            # create new observations but never rewrite verified provider fields.
            if candidate.outcome != "auto_approved_published":
                candidate.status = "awaiting_enrichment"
                candidate.outcome = "awaiting_enrichment"
                candidate.last_checked_at = None
            observation = SourceObservation(
                source_type="overture_places", source_name="Overture Places",
                source_url="https://docs.overturemaps.org/guides/places/",
                confidence=_float_or_none(raw.get("confidence")),
                observed_data={"gers_id": gers_id, "source_release": candidate.source_release,
                    "sources": _as_sources(raw.get("sources_json")), "record": dict(raw),
                    "confidence_semantics": "place_existence_confidence_not_field_or_service_confidence"},
                review_status="pending",
                notes="Overture discovery observation. Contributor source/licence lineage retained; not proof of service type or field accuracy.",
            )
            db.add(observation)
            db.flush()
            candidate.source_observation_id = observation.id
            db.add(AuditEvent(entity_type="overture_candidate", entity_id=candidate.id,
                action="source_observation_imported", detail={"gers_id": gers_id,
                "source_release": candidate.source_release, "source_observation_id": observation.id,
                "import_run_id": run.id}))
            db.commit()
        run.records_imported = (run.records_imported or 0) + imported
        run.records_updated = (run.records_updated or 0) + updated
        run.status = "imported" if finalize else "running"
        if finalize:
            run.completed_at = _now()
            db.add(AuditEvent(entity_type="overture_import_run", entity_id=run.id,
                action="import_completed", detail={"received": run.records_received,
                "imported": run.records_imported, "updated": run.records_updated, "source_release": source_release}))
        db.commit()
        if finalize and settings.overture_auto_process:
            process_overture_candidates.delay(run.id, 20)
        return {"status": run.status, "run_id": run.id, "imported": imported, "updated": updated}
    except Exception as exc:
        db.rollback()
        run = db.get(OvertureImportRun, run_id)
        run.status = "failed"
        run.error_message = str(exc)[:2000]
        run.completed_at = _now()
        db.add(AuditEvent(entity_type="overture_import_run", entity_id=run.id,
            action="import_failed", detail={"error": run.error_message}))
        db.commit()
        raise
    finally:
        db.close()


@celery_app.task(name="everguide.overture.process_candidates", bind=True)
def process_overture_candidates(self, run_id: int | None = None, limit: int = 20):
    db = SessionLocal()
    run = db.get(OvertureImportRun, run_id) if run_id else None
    counts = Counter()
    checked = 0
    claimed_ids = []
    try:
        # Recover claims left behind by a terminated worker, then atomically
        # claim this batch so concurrent Celery workers cannot publish the same
        # candidate twice.
        stale_before = _now() - timedelta(minutes=45)
        db.query(OvertureCandidate).filter(
            OvertureCandidate.status == "processing",
            OvertureCandidate.updated_at < stale_before,
        ).update({"status": "awaiting_enrichment", "updated_at": _now()}, synchronize_session=False)
        db.commit()
        if run:
            run.status = "processing"
            run.started_at = run.started_at or _now()
            db.commit()
        query = db.query(OvertureCandidate).filter(
            OvertureCandidate.outcome == "awaiting_enrichment",
            OvertureCandidate.status == "awaiting_enrichment",
        ).order_by(OvertureCandidate.id.asc()).limit(max(1, min(int(limit), 50)))
        if run_id:
            query = query.filter(OvertureCandidate.last_import_run_id == run_id,
                OvertureCandidate.last_checked_at.is_(None))
        candidates = query.with_for_update(skip_locked=True).all()
        claimed_ids = [candidate.id for candidate in candidates]
        for candidate in candidates:
            candidate.status = "processing"
            candidate.updated_at = _now()
        db.commit()
        boundary_cache = {}
        boundary_errors = {}
        boundary_error = None
        boundary = None

        for candidate in candidates:
            raw = dict(candidate.raw_data or {})
            geography_scope = str(raw.get("geography_scope") or "thurrock").lower()
            if geography_scope not in boundary_cache and geography_scope not in boundary_errors:
                try:
                    boundary_cache[geography_scope] = _fetch_ons_england_geometry() if geography_scope == "england" else _fetch_ons_geometry()
                except Exception as exc:
                    boundary_errors[geography_scope] = str(exc)[:500]
            boundary = boundary_cache.get(geography_scope)
            boundary_error = boundary_errors.get(geography_scope)
            row = _normalised_assessment_row(raw)
            classification = assess_overture_candidate(
                row, point_in_thurrock=None, point_in_england=None,
                geography_scope=geography_scope, auto_approval_enabled=False,
                minimum_confidence=settings.auto_approval_min_confidence,
            )
            if classification["outcome"] == "excluded":
                assessment = classification
                outcome = "excluded"
                evidence = {"boundary_error": boundary_error} if boundary_error else {}
            elif classification["outcome"] == "exception_review":
                assessment = classification
                outcome = "exception_review"
                evidence = {"boundary_error": boundary_error} if boundary_error else {}
            else:
                point = _inside_boundary(boundary, raw.get("longitude"), raw.get("latitude")) if boundary else None
                website = row.get("website")
                verified_url, verification = _verify_overture_website(raw, website)
                extracted = verification.get("extracted_data") if verification else None
                if verified_url:
                    row["website"] = verified_url
                evidence = {
                    "source_type": "first_party_website" if verification and extracted else None,
                    "business_name": extracted.get("name") if extracted else None,
                    "reachable": bool(verification and verification.get("status") == "reachable"),
                    "robots_allowed": verification.get("robots_allowed") if verification else None,
                    "explicit_funeral_director_service": bool(extracted and extracted.get("funeral_signals")),
                    "website_url": verification.get("final_url") if verification else verified_url or website,
                    "website_discovery_source": verification.get("discovery_source") if verification else None,
                    "website_search_query": verification.get("search_query") if verification else None,
                    "website_search_error": verification.get("search_error") if verification else None,
                    "complete_branch_address": bool(extracted and extracted.get("has_complete_branch_address")),
                    "postcode": extracted.get("postcode") if extracted else None,
                    "telephone": extracted.get("telephone") if extracted else None,
                    "confidence": extracted.get("confidence", 0) if extracted else 0,
                    "conflicting_identity_or_branch_evidence": False,
                    "page_title": verification.get("page_title") if verification else None,
                    "content_sha256": verification.get("content_sha256") if verification else None,
                    "verification_status": verification.get("status") if verification else "website_missing",
                    "verification_detail": verification.get("detail") if verification else "No official HTTPS website supplied by Overture.",
                    "ons_boundary_code": "CTYUA25CD:E*" if geography_scope == "england" and boundary else ONS_BOUNDARY_CODE if boundary else None,
                    "geography_scope": geography_scope,
                    "point_in_scope": point,
                }
                if extracted:
                    evidence["telephone_match"] = normalise_phone(extracted.get("telephone")) == normalise_phone(raw.get("phone"))
                    evidence["postcode_match"] = normalise_postcode(extracted.get("postcode")) == normalise_postcode(raw.get("postcode"))
                duplicate = (str(raw.get("possible_duplicate", "")).lower() in {"true", "1", "yes"}
                    or _overture_duplicate_conflict(db, candidate))
                existing_conflict, parent_provider = _existing_provider_match(db, row)
                assessment = assess_overture_candidate(
                    row, first_party_evidence=evidence, point_in_thurrock=point if geography_scope != "england" else None,
                    point_in_england=point if geography_scope == "england" else None,
                    geography_scope=geography_scope,
                    duplicate_conflict=duplicate, existing_provider_conflict=existing_conflict,
                    auto_approval_enabled=settings.auto_approve_providers,
                    minimum_confidence=settings.auto_approval_min_confidence,
                )
                outcome = assessment["outcome"]
                if boundary_error:
                    assessment["reasons"] = ";".join(filter(None, [assessment.get("reasons", ""), "official_ons_boundary_unavailable"]))
                    if outcome == "auto_approved_eligible":
                        outcome = "awaiting_enrichment"
                        assessment["outcome"] = outcome
                if outcome == "auto_approved_eligible":
                    # Re-check conflicts immediately before the write. Provider,
                    # branch, source observations and audit events commit atomically.
                    conflict_now, parent_provider = _existing_provider_match(db, row)
                    if conflict_now:
                        outcome = "exception_review"
                        assessment["outcome"] = outcome
                        assessment["reasons"] = ";".join(filter(None, [assessment.get("reasons", ""), "existing_provider_or_branch_conflict"]))
                    else:
                        verified_site = urllib.parse.urlsplit(evidence["website_url"])
                        provider_website = urllib.parse.urlunsplit(("https", verified_site.netloc, "/", "", ""))
                        provider = parent_provider
                        created_provider = provider is None
                        if created_provider:
                            provider = Provider(
                                trading_name=extracted["name"], display_name=extracted["name"],
                                website=provider_website, provider_type="funeral_director",
                                status="published", verification_status="approved", quality_status="confirmed",
                                notes="Automatically approved from Overture discovery and independently verified first-party branch evidence under " + assessment["ruleset_version"],
                            )
                            db.add(provider)
                        branch = Branch(
                            branch_name=extracted["name"], address_line_1=extracted["street"],
                            town_city=extracted["town"], county=None,
                            postcode=extracted["postcode"], telephone=extracted["telephone"],
                            email=extracted.get("email"), website=provider_website,
                            # Overture point coordinates are used for the official
                            # boundary check only; do not publish them as a verified
                            # branch pin without independent geocoding.
                            latitude=None,
                            longitude=None,
                            status="published", services=[],
                        )
                        provider.branches.append(branch)
                        db.flush()
                        candidate.provider_id = provider.id
                        candidate.branch_id = branch.id
                        outcome = "auto_approved_published"
                        assessment["outcome"] = outcome
                        candidate.status = candidate.outcome = outcome
                        if candidate.source_observation_id:
                            source_obs = db.get(SourceObservation, candidate.source_observation_id)
                            if source_obs:
                                source_obs.provider_id = provider.id
                                source_obs.branch_id = branch.id
                                source_obs.review_status = "accepted"
                        first_party_obs = SourceObservation(
                            provider_id=provider.id, branch_id=branch.id,
                            source_type="provider_owned_website_structured_data",
                            source_name="Provider-owned website (independent first-party evidence)",
                            source_url=evidence["website_url"], confidence=float(evidence["confidence"]),
                            observed_data={k: extracted.get(k) for k in (
                                "name", "street", "town", "postcode", "telephone", "email", "website",
                                "source_type", "country", "confidence", "funeral_signals", "has_complete_branch_address")},
                            review_status="accepted",
                            notes="Accepted after robots permission, reachability, explicit funeral-service and branch identity checks. Page body was discarded.",
                        )
                        db.add(first_party_obs)
                        db.flush()
                        db.add(AuditEvent(entity_type="provider", entity_id=provider.id,
                            action="auto_approved_published" if created_provider else "auto_approved_branch_added", detail={
                                "overture_candidate_id": candidate.id, "gers_id": candidate.gers_id,
                                "branch_id": branch.id, "overture_observation_id": candidate.source_observation_id,
                                "first_party_observation_id": first_party_obs.id,
                                "confidence": assessment.get("confidence"),
                                "minimum_confidence": settings.auto_approval_min_confidence,
                                "ruleset_version": assessment.get("ruleset_version"),
                                "source_licences": assessment.get("source_licences"),
                                "ons_boundary_code": "CTYUA25CD:E*" if geography_scope == "england" else ONS_BOUNDARY_CODE,
                                "geography_scope": geography_scope,
                                "existing_parent_provider_reused": not created_provider,
                            }))
                        db.add(AuditEvent(entity_type="overture_candidate", entity_id=candidate.id,
                            action="auto_approved_published", detail={"provider_id": provider.id, "branch_id": branch.id}))
            candidate.assessment = assessment
            candidate.first_party_evidence = evidence
            candidate.outcome = outcome
            if outcome != "auto_approved_published":
                candidate.status = outcome
                if outcome == "excluded" and candidate.source_observation_id:
                    source_obs = db.get(SourceObservation, candidate.source_observation_id)
                    if source_obs:
                        source_obs.review_status = "rejected"
            candidate.last_checked_at = _now()
            counts[outcome] += 1
            checked += 1
            db.add(AuditEvent(entity_type="overture_candidate", entity_id=candidate.id,
                action="automated_assessment_completed", detail={"outcome": outcome,
                "reasons": assessment.get("reasons", ""), "ruleset_version": assessment.get("ruleset_version")}))
            db.commit()

        if run:
            run.records_processed = (run.records_processed or 0) + checked
            previous = {k: int(v) for k, v in (run.outcomes or {}).items() if k != "_meta"}
            for key, value in counts.items():
                previous[key] = previous.get(key, 0) + int(value)
            run.outcomes = {**previous, "_meta": (run.outcomes or {}).get("_meta", {})}
            unclaimed = db.query(OvertureCandidate).filter(
                OvertureCandidate.last_import_run_id == run.id,
                OvertureCandidate.outcome == "awaiting_enrichment",
                OvertureCandidate.status == "awaiting_enrichment",
                OvertureCandidate.last_checked_at.is_(None)).count()
            in_progress = db.query(OvertureCandidate).filter(
                OvertureCandidate.last_import_run_id == run.id,
                OvertureCandidate.outcome == "awaiting_enrichment",
                OvertureCandidate.status == "processing").count()
            run.status = "processing" if (unclaimed or in_progress) else "completed"
            if not (unclaimed or in_progress):
                run.completed_at = _now()
            db.add(AuditEvent(entity_type="overture_import_run", entity_id=run.id,
                action="processing_batch_completed", detail={"records_processed_this_batch": checked,
                "records_processed_total": run.records_processed, "unclaimed": unclaimed,
                "in_progress": in_progress, "outcomes_this_batch": dict(counts),
                "boundary_errors": boundary_errors}))
            db.commit()
            if unclaimed and not in_progress:
                process_overture_candidates.delay(run.id, 20)
        return {"status": "completed", "run_id": run_id, "records_processed": checked,
            "outcomes": dict(counts), "boundary_verified": bool(boundary_cache) and not bool(boundary_errors)}
    except Exception as exc:
        db.rollback()
        if claimed_ids:
            db.query(OvertureCandidate).filter(
                OvertureCandidate.id.in_(claimed_ids),
                OvertureCandidate.status == "processing").update(
                    {"status": "awaiting_enrichment", "updated_at": _now()}, synchronize_session=False)
            db.commit()
        if run_id:
            run = db.get(OvertureImportRun, run_id)
            if run:
                run.status = "failed"
                run.error_message = str(exc)[:2000]
                run.completed_at = _now()
                db.add(AuditEvent(entity_type="overture_import_run", entity_id=run.id,
                    action="processing_failed", detail={"error": run.error_message}))
                db.commit()
        raise
    finally:
        db.close()
