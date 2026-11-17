"""Persist and process Overture Places observations through the evidence-led pipeline.

The worker never treats Overture existence confidence as field verification.
Only first-party website evidence, source-level licence metadata, an official
ONS boundary check and collision checks can permit automatic publication.
"""
from __future__ import annotations

import json
import math
import os
import re
import ssl
import tempfile
import time
import hashlib
import urllib.error
import urllib.parse
import urllib.request
from http.client import IncompleteRead
from pathlib import Path
from collections import Counter
from difflib import SequenceMatcher
from datetime import datetime, timezone, timedelta

from app.celery_app import celery_app
from app.config import settings
from app.database import SessionLocal
from app.models import (
    AuditEvent, Branch, OvertureCandidate, OvertureImportRun, Provider,
    SourceObservation, OvertureCompanyLink, CompaniesHouseCandidate,
)
from app.overture_approval import assess_overture_candidate
from app.candidate_quality import DIRECTORY_DOMAINS, normalise_identity_name, normalise_phone, normalise_postcode, website_domain
from app.website_checks import verify_candidate
from app.search_providers import search_web, SearchProviderError

ONS_QUERY_URL = (
    "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
    "Counties_and_Unitary_Authorities_December_2025_Boundaries_UK_BFE/"
    "FeatureServer/0/query"
)
ONS_BOUNDARY_CODE = "E06000034"
MAX_ENRICHMENT_ATTEMPTS = 4  # first assessment plus at most three scheduled retries
ENRICHMENT_RETRY_DELAYS_DAYS = (2, 7, 21)


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


def _enforce_publication_safety_gate(assessment: dict, *, auto_approval_enabled: bool) -> str:
    """Defence-in-depth guard immediately before any provider/branch writes."""
    outcome = assessment.get("outcome")
    if outcome == "auto_approved_eligible" and not auto_approval_enabled:
        reasons = [item for item in str(assessment.get("reasons") or "").split(";") if item]
        if "automatic_approval_disabled" not in reasons:
            reasons.append("automatic_approval_disabled")
        assessment["reasons"] = ";".join(reasons)
        assessment["outcome"] = "awaiting_enrichment"
        return "awaiting_enrichment"
    return outcome


def _point_on_segment(lon, lat, a, b, *, epsilon=1e-10):
    """Return True when a point lies on a segment, within coordinate tolerance."""
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    cross = (lon - ax) * (by - ay) - (lat - ay) * (bx - ax)
    scale = max(1.0, abs(bx - ax), abs(by - ay))
    if abs(cross) > epsilon * scale:
        return False
    return (min(ax, bx) - epsilon <= lon <= max(ax, bx) + epsilon
            and min(ay, by) - epsilon <= lat <= max(ay, by) + epsilon)


def _point_in_ring(lon, lat, ring):
    """Ray casting with explicit boundary inclusion (OGC covers semantics)."""
    inside = False
    if not ring or len(ring) < 4:
        return False
    j = len(ring) - 1
    for i in range(len(ring)):
        current, previous = ring[i], ring[j]
        xi, yi = float(current[0]), float(current[1])
        xj, yj = float(previous[0]), float(previous[1])
        if _point_on_segment(lon, lat, current, previous):
            return True
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _point_on_ring(lon, lat, ring):
    if not ring or len(ring) < 4:
        return False
    return any(_point_on_segment(lon, lat, ring[index], ring[index - 1]) for index in range(len(ring)))


def _point_in_polygon(lon, lat, polygon):
    if not polygon or not _point_in_ring(lon, lat, polygon[0]):
        return False
    for hole in polygon[1:]:
        # A hole's interior is excluded, but its boundary belongs to the polygon.
        if _point_on_ring(lon, lat, hole):
            return True
        if _point_in_ring(lon, lat, hole):
            return False
    return True


# ONS boundary cache is stored on a dedicated Docker named volume and read once
# per 20-record task batch. Expired/corrupt data is never trusted.
ONS_BOUNDARY_CACHE_TTL_HOURS = int(os.getenv("ONS_BOUNDARY_CACHE_TTL_HOURS", "720"))
ONS_BOUNDARY_CACHE_DIR = Path(os.getenv("ONS_BOUNDARY_CACHE_DIR", "/var/lib/everguide/cache"))


def _validate_boundary_geometry(geometry: dict, *, minimum_polygons: int = 1) -> None:
    if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        raise RuntimeError("ONS boundary cache has an unsupported geometry type.")
    coords = geometry.get("coordinates")
    polygons = [coords] if geometry["type"] == "Polygon" else coords
    if not isinstance(polygons, list) or len(polygons) < minimum_polygons:
        raise RuntimeError("ONS boundary cache geometry is incomplete.")
    authority_codes = geometry.get("authority_codes")
    authority_names = geometry.get("authority_names")
    if authority_codes is not None and (not isinstance(authority_codes, list) or len(authority_codes) != len(polygons)
            or any(not isinstance(code, str) or not code.startswith("E") for code in authority_codes)):
        raise RuntimeError("ONS authority-code provenance does not match the boundary polygons.")
    if authority_names is not None and (not isinstance(authority_names, list) or len(authority_names) != len(polygons)
            or any(not isinstance(name, str) for name in authority_names)):
        raise RuntimeError("ONS authority-name provenance does not match the boundary polygons.")
    if authority_codes is not None:
        try:
            feature_count = int(geometry.get("ons_feature_count"))
        except (TypeError, ValueError):
            raise RuntimeError("ONS authority feature count is missing or invalid.")
        if feature_count != len(set(authority_codes)) or feature_count < minimum_polygons:
            raise RuntimeError("ONS authority feature count does not match the cached provenance.")
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise RuntimeError("ONS boundary contains an invalid polygon.")
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                raise RuntimeError("ONS boundary contains an invalid or unclosed ring.")
            for coordinate in ring:
                if not isinstance(coordinate, (list, tuple)) or len(coordinate) < 2:
                    raise RuntimeError("ONS boundary contains an invalid coordinate.")
                lon, lat = float(coordinate[0]), float(coordinate[1])
                if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
                    raise RuntimeError("ONS boundary contains an out-of-range coordinate.")


def _boundary_cache_path(scope: str) -> Path:
    safe_scope = "england" if scope == "england" else "thurrock"
    return ONS_BOUNDARY_CACHE_DIR / f"ons-{safe_scope}-boundary-v2.json"


def _read_boundary_cache(scope: str):
    path = _boundary_cache_path(scope)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 2 or payload.get("scope") != scope or payload.get("source") != ONS_QUERY_URL:
            return None
        geometry = payload["geometry"]
        fetched_at = datetime.fromisoformat(payload["retrieved_at"].replace("Z", "+00:00"))
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        age = (_now() - fetched_at).total_seconds()
        digest = hashlib.sha256(json.dumps(geometry, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if payload.get("sha256") != digest or age < 0 or age > ONS_BOUNDARY_CACHE_TTL_HOURS * 3600:
            return None
        _validate_boundary_geometry(geometry, minimum_polygons=100 if scope == "england" else 1)
        return geometry
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return None


def _write_boundary_cache(scope: str, geometry: dict) -> None:
    _validate_boundary_geometry(geometry, minimum_polygons=100 if scope == "england" else 1)
    ONS_BOUNDARY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _boundary_cache_path(scope)
    encoded_geometry = json.dumps(geometry, sort_keys=True, separators=(",", ":"))
    payload = {
        "schema_version": 2, "scope": scope, "source": ONS_QUERY_URL,
        "retrieved_at": _now().isoformat(), "sha256": hashlib.sha256(encoded_geometry.encode()).hexdigest(),
        "geometry": geometry,
    }
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _get_ons_boundary(scope: str):
    scope = "england" if scope == "england" else "thurrock"
    cached = _read_boundary_cache(scope)
    if cached is not None:
        return cached
    fetcher = _fetch_ons_england_geometry if scope == "england" else _fetch_ons_geometry
    geometry = fetcher()
    _validate_boundary_geometry(geometry, minimum_polygons=100 if scope == "england" else 1)
    _write_boundary_cache(scope, geometry)
    return geometry


def _fetch_ons_json(url: str, *, timeout: int, attempts: int = 3) -> dict:
    """Fetch ONS JSON with verified TLS and bounded retries for transient failures."""
    last_error = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": "EverguideBoundaryCheck/2.0", "Accept": "application/geo+json,application/json"})
        try:
            # urllib's default SSL context verifies the certificate chain and hostname.
            with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict) or payload.get("error"):
                raise RuntimeError("ONS returned an error or malformed JSON response.")
            return payload
        except (IncompleteRead, urllib.error.URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"ONS boundary request failed after {attempts} verified-TLS attempts: {last_error}") from last_error


def _fetch_ons_geometry():
    params = urllib.parse.urlencode({
        "where": f"CTYUA25CD='{ONS_BOUNDARY_CODE}'",
        "outFields": "CTYUA25CD,CTYUA25NM",
        "returnGeometry": "true", "outSR": "4326", "f": "geojson",
    })
    payload = _fetch_ons_json(ONS_QUERY_URL + "?" + params, timeout=30)
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
    """Fetch every England authority polygon and retain its ONS identity.

    A count-only request establishes the expected feature total. Stable,
    ordered offset pagination then retrieves every feature; any short page,
    duplicate code, missing feature, or transfer-limit inconsistency fails closed.
    """
    base = {
        "where": "CTYUA25CD LIKE 'E%'", "outFields": "CTYUA25CD,CTYUA25NM",
        "returnGeometry": "true", "outSR": "4326", "f": "geojson",
        "orderByFields": "CTYUA25CD",
    }
    count_params = urllib.parse.urlencode({**base, "f": "json", "returnCountOnly": "true", "returnGeometry": "false"})
    count_payload = _fetch_ons_json(ONS_QUERY_URL + "?" + count_params, timeout=45)
    try:
        expected_count = int(count_payload.get("count"))
    except (TypeError, ValueError):
        raise RuntimeError("ONS England boundary count response was missing or invalid.")
    if expected_count < 100:
        raise RuntimeError("ONS England boundary count was below the expected authority minimum.")

    page_size = 500
    offset = 0
    features = []
    seen_codes = set()
    while offset < expected_count:
        params = urllib.parse.urlencode({**base, "resultRecordCount": page_size, "resultOffset": offset})
        payload = _fetch_ons_json(ONS_QUERY_URL + "?" + params, timeout=45)
        page = payload.get("features")
        if not isinstance(page, list) or not page:
            raise RuntimeError("ONS England boundary pagination ended before the expected feature count.")
        if payload.get("exceededTransferLimit") is True and len(page) < page_size:
            raise RuntimeError("ONS England boundary page was truncated by the transfer limit.")
        for feature in page:
            properties = feature.get("properties") or {}
            code = str(properties.get("CTYUA25CD") or "")
            if not code.startswith("E") or code in seen_codes:
                raise RuntimeError("ONS England boundary response contains an invalid or repeated authority code.")
            seen_codes.add(code)
            features.append(feature)
        offset += len(page)
        if len(page) > page_size or offset > expected_count:
            raise RuntimeError("ONS England boundary pagination returned an inconsistent feature count.")
    if len(features) != expected_count or len(seen_codes) != expected_count:
        raise RuntimeError("ONS England boundary response did not match the authoritative feature count.")

    polygons, authority_codes, authority_names = [], [], []
    for feature in features:
        properties = feature.get("properties") or {}
        code = str(properties.get("CTYUA25CD") or "")
        name = str(properties.get("CTYUA25NM") or "").strip()
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise RuntimeError("ONS England boundary response contains an unsupported feature geometry.")
        coordinates = geometry.get("coordinates") or []
        feature_polygons = [coordinates] if geometry.get("type") == "Polygon" else coordinates
        if not feature_polygons:
            raise RuntimeError("ONS England boundary contains an empty authority geometry.")
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
            polygons.append(polygon)
            authority_codes.append(code)
            authority_names.append(name)
    result = {"type": "MultiPolygon", "coordinates": polygons,
              "authority_codes": authority_codes, "authority_names": authority_names,
              "ons_feature_count": expected_count}
    _validate_boundary_geometry(result, minimum_polygons=100)
    return result


def _authority_codes_for_point(geometry, lon, lat):
    """Return all ONS authorities whose polygons cover the supplied point."""
    if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        return []
    coords = geometry.get("coordinates")
    polygons = [coords] if geometry["type"] == "Polygon" else coords
    codes = geometry.get("authority_codes") or []
    matches = []
    for index, polygon in enumerate(polygons):
        if _point_in_polygon(lon, lat, polygon):
            code = codes[index] if index < len(codes) else None
            if code and code not in matches:
                matches.append(code)
    return matches

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


def _verified_companies_house_conflicts(db, candidate):
    """Return conflicts only from an explicitly reviewed Overture↔CH identity link."""
    links = db.query(OvertureCompanyLink).filter(
        OvertureCompanyLink.overture_candidate_id == candidate.id,
        OvertureCompanyLink.status == "verified",
        OvertureCompanyLink.reviewed_at.is_not(None),
        OvertureCompanyLink.reviewed_by.is_not(None),
        OvertureCompanyLink.evidence_json.is_not(None),
    ).all()
    conflicts = []
    for link in links:
        company = db.get(CompaniesHouseCandidate, link.companies_house_candidate_id)
        if company and str(company.company_status or "").strip().lower() == "dissolved":
            conflicts.append("verified_companies_house_entity_dissolved")
    return sorted(set(conflicts))


def _overture_duplicate_conflict(db, candidate):
    name_key = normalise_identity_name(candidate.candidate_name)
    postcode_key = normalise_postcode(candidate.postcode)
    if not name_key or not postcode_key:
        return False
    peers = db.query(OvertureCandidate).filter(
        OvertureCandidate.id != candidate.id,
        OvertureCandidate.postcode == candidate.postcode,
    ).all()
    # This deliberately identifies only a possible same-name/same-postcode
    # observation. It is not proof of a duplicate business or branch.
    return any(normalise_identity_name(peer.candidate_name) == name_key for peer in peers)


def _normalised_assessment_row(raw):
    """Normalise Overture fields without replacing them with website data."""
    row = dict(raw)
    row["sources_json"] = _as_sources(row.get("sources_json"))
    row["website"] = _https_website(row.get("website"))
    if not row["website"]:
        websites = _as_sources(raw.get("websites_json"))
        if websites and isinstance(websites[0], str):
            row["website"] = _https_website(websites[0])
    addresses = _as_sources(raw.get("addresses_json"))
    address = addresses[0] if isinstance(addresses, list) and addresses and isinstance(addresses[0], dict) else {}
    street = (address.get("street") or address.get("street_address") or address.get("address_line_1")
              or row.get("address_line_1"))
    town = (address.get("locality") or address.get("town") or address.get("city")
            or row.get("town_city") or row.get("town") or row.get("locality"))
    freeform = str(address.get("freeform") or row.get("address") or "").strip()
    if not street and freeform:
        parts = [part.strip() for part in freeform.split(",") if part.strip()]
        if len(parts) >= 2:
            street = parts[0]
            if not town:
                town = parts[-1]
        else:
            street = freeform
    row["address_line_1"] = str(street or "").strip()
    row["town_city"] = str(town or "").strip()
    return row


def _same_asserted_branch_location(raw, extracted):
    """Whether website structured data identifies the same street and locality."""
    if not isinstance(extracted, dict) or extracted.get("has_complete_branch_address") is not True:
        return False
    asserted_street = normalise_identity_name(raw.get("address_line_1") or raw.get("address"))
    observed_street = normalise_identity_name(extracted.get("street"))
    asserted_town = normalise_identity_name(raw.get("town_city") or raw.get("town") or raw.get("locality"))
    observed_town = normalise_identity_name(extracted.get("town"))
    # A provider's other branch may legitimately have a different address.
    return bool(
        asserted_street and observed_street and asserted_street == observed_street
        and asserted_town and observed_town and asserted_town == observed_town
    )


def _same_asserted_branch_postcode_conflict(raw, extracted):
    """A different postcode is material only for the exact same street/locality."""
    if not _same_asserted_branch_location(raw, extracted):
        return False
    observed_postcode = normalise_postcode(extracted.get("postcode"))
    asserted_postcode = normalise_postcode(raw.get("postcode"))
    return bool(observed_postcode and asserted_postcode and observed_postcode != asserted_postcode)


def _first_party_website_conflicts(raw, extracted, *, verified_first_party):
    """Return only explicit conflicts supported by verified first-party evidence."""
    if not verified_first_party or not isinstance(extracted, dict):
        return []
    conflicts = []
    branch_status = str(extracted.get("branch_status") or extracted.get("business_status") or "").strip().lower()
    if (branch_status in {"closed", "permanently_closed", "permanently closed",
                          "temporarily_closed", "temporarily closed"}
            and _same_asserted_branch_location(raw, extracted)):
        conflicts.append("official_site_branch_closed")
    if _same_asserted_branch_postcode_conflict(raw, extracted):
        conflicts.append("official_site_branch_postcode_mismatch")
    return conflicts


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
    return name_match and postcode_match


def _is_non_first_party_url(url: str | None) -> bool:
    """Reject obvious intermediaries and non-provider pages as identity sources.

    These URLs may still be useful discovery leads, but must never be treated as
    provider-owned websites for automatic approval.
    """
    domain = website_domain(url)
    if not domain:
        return True
    blocked = set(DIRECTORY_DOMAINS) | {
        "yell.com", "cylex-uk.co.uk", "cylex-uk.com", "thomsonlocal.com",
        "scoot.co.uk", "freeindex.co.uk", "hotfrog.co.uk", "yellowtom.co.uk",
        "mylocalservices.co.uk", "approvedbusiness.co.uk", "allinlondon.co.uk",
        "thefarewellguide.co.uk", "companieshouse.gov.uk",
        "find-and-update.company-information.service.gov.uk", "facebook.com",
        "instagram.com", "linkedin.com", "m.facebook.com", "wikipedia.org",
        "wikidata.org", "bristol247.com", "rossgazette.com", "funeral-notices.co.uk",
        "death-notices.co.uk", "muchloved.org", "findglocal.com", "endole.co.uk",
        "beyond.life", "funeralrelated.co.uk", "arrangingafuneral.co.uk",
        "uk-funerals.co.uk", "nextdoor.co.uk",
    }
    if any(domain == item or domain.endswith("." + item) for item in blocked):
        return True
    # Inspect the full hostname as website_domain() intentionally reduces it
    # to a registrable domain for identity comparison.
    parsed = urllib.parse.urlsplit(url if "://" in url else "https://" + url)
    hostname = (parsed.hostname or "").lower()
    host_parts = hostname.split(".")
    if host_parts and host_parts[0] in {"jobs", "careers", "recruitment", "news", "blog"}:
        return True
    if any(token in host_parts for token in ("directory", "listings", "classifieds", "jobs", "careers")):
        return True
    path = parsed.path.lower()
    if any(token in path for token in ("/search/", "/directory/", "/listing/", "/businesses/", "/jobs/", "/careers/", "/officers/", "/wiki/", "/news/", "/features/", "/articles/")):
        return True
    if parsed.path.lower().endswith((".pdf", ".doc", ".docx")):
        return True
    return False


def _verification_attempt(url, discovery_source, verification, search_query=None):
    """Build a compact, body-free audit record for one attempted website."""
    extracted = (verification or {}).get("extracted_data") or {}
    return {
        "url": url,
        "discovery_source": discovery_source,
        "search_query": search_query,
        "status": (verification or {}).get("status"),
        "final_url": (verification or {}).get("final_url"),
        "page_title": (verification or {}).get("page_title"),
        "content_sha256": (verification or {}).get("content_sha256"),
        "robots_allowed": (verification or {}).get("robots_allowed"),
        "extracted_identity": ({
            key: extracted.get(key) for key in (
                "name", "street", "town", "postcode", "telephone", "email", "website",
                "source_type", "country", "confidence", "funeral_signals", "has_complete_branch_address",
            )
        } if extracted else None),
        "detail": (verification or {}).get("detail"),
    }


def _verify_overture_website(raw, initial_url):
    """Try Overture first, then search; preserve provenance without promoting mismatches."""
    candidates = []
    initial_is_directory = _is_non_first_party_url(initial_url) if initial_url else False
    if initial_url and not initial_is_directory:
        candidates.append((initial_url, "overture_website", None))
    query = f'"{raw.get("name", "")}" funeral directors {raw.get("postcode", "")} official website UK'
    search_error = None
    if settings.brave_search_api_key:
        try:
            results = search_web(query, provider=settings.search_provider,
                brave_api_key=settings.brave_search_api_key, count=8)
            seen = {url for url, _, _ in candidates}
            for item in results:
                url = _https_website(item.get("url"))
                if not url or url in seen or _is_non_first_party_url(url):
                    continue
                candidates.append((url, "brave_search", query))
                seen.add(url)
        except SearchProviderError as exc:
            search_error = str(exc)[:500]
    attempts = []
    initial_mismatch = None
    last_verification = None
    for url, discovery_source, search_query in candidates[:6]:
        try:
            verification = verify_candidate(url)
        except Exception as exc:
            verification = {"status": "check_blocked_or_failed", "detail": str(exc)[:800],
                "robots_allowed": None, "final_url": url}
        last_verification = verification
        attempts.append(_verification_attempt(url, discovery_source, verification, search_query))
        extracted = verification.get("extracted_data") if verification else None
        if extracted and _candidate_evidence_matches(raw, extracted):
            verification["discovery_source"] = discovery_source
            verification["search_query"] = search_query
            verification["search_error"] = search_error
            verification["attempts"] = attempts
            return url, verification
        # Preserve a mismatched original Overture URL for human review. A
        # mismatched search result is only an attempted lead, never a replacement.
        if extracted and discovery_source == "overture_website" and initial_mismatch is None:
            initial_mismatch = (url, verification)
    if initial_mismatch:
        url, verification = initial_mismatch
        verification["discovery_source"] = "identity_or_branch_mismatch"
        verification["search_query"] = None
        verification["search_error"] = search_error
        verification["attempts"] = attempts
        return url, verification
    return None, {"status": "website_missing", "final_url": initial_url,
        "robots_allowed": None, "discovery_source": "third_party_discovery_lead" if initial_is_directory else None,
        "search_error": search_error, "search_query": query if candidates else None,
        "attempts": attempts,
        "detail": "No matching provider-owned HTTPS website could be verified. Original discovery URL is retained as source evidence; attempted alternatives are recorded separately."}


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
            incoming_release = str(source_release or raw.get("version") or "")[:80] or None
            candidate = db.query(OvertureCandidate).filter(OvertureCandidate.gers_id == gers_id).first()
            if candidate is None:
                candidate = OvertureCandidate(gers_id=gers_id, candidate_name=name[:240], postcode=str(raw.get("postcode") or "")[:12])
                db.add(candidate)
                db.flush()
                imported += 1
                previous_run_id = None
                previous_release = None
            else:
                previous_run_id = candidate.last_import_run_id
                previous_release = candidate.source_release
                candidate.candidate_name = name[:240]
                candidate.postcode = str(raw.get("postcode") or "")[:12]
                if not (previous_run_id == run.id and previous_release == incoming_release):
                    updated += 1
            candidate.source_release = incoming_release
            candidate.raw_data = dict(raw)
            candidate.last_import_run_id = run.id
            # Keep prior approved/published outcome stable; a resumed delivery
            # must not append duplicate observations for the same GERS id/run.
            if candidate.outcome != "auto_approved_published":
                candidate.status = "awaiting_enrichment"
                candidate.outcome = "awaiting_enrichment"
                candidate.last_checked_at = None
            same_run_observation_exists = (
                previous_run_id == run.id and previous_release == candidate.source_release
                and candidate.source_observation_id is not None
            )
            if not same_run_observation_exists:
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
                action="source_observation_reused" if same_run_observation_exists else "source_observation_imported",
                detail={"gers_id": gers_id, "source_release": candidate.source_release,
                "source_observation_id": candidate.source_observation_id, "import_run_id": run.id}))
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
            OvertureCandidate.last_checked_at.is_(None),
        )
        # SQLAlchemy does not allow filter() after limit()/offset(). Apply the
        # import-run scope first, then order and cap the batch. This is the
        # normal scheduled-feed path (run_id is supplied by the importer).
        if run_id:
            query = query.filter(OvertureCandidate.last_import_run_id == run_id)
        query = query.order_by(OvertureCandidate.id.asc()).limit(max(1, min(int(limit), 50)))
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
            previous_evidence = dict(candidate.first_party_evidence or {})
            raw = dict(candidate.raw_data or {})
            geography_scope = str(raw.get("geography_scope") or "thurrock").lower()
            if geography_scope not in boundary_cache and geography_scope not in boundary_errors:
                try:
                    boundary_cache[geography_scope] = _get_ons_boundary(geography_scope)
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
                authority_codes = (_authority_codes_for_point(boundary, float(raw.get("longitude")), float(raw.get("latitude")))
                    if boundary and geography_scope == "england" and point is True else [])
                discovery_url = row.get("website")
                verification = None
                verified_url = None
                extracted = None
                # Website corroboration is optional and never supplies published branch fields.
                if discovery_url and not _is_non_first_party_url(discovery_url):
                    try:
                        verification = verify_candidate(discovery_url)
                    except Exception as exc:
                        verification = {"status": "check_blocked_or_failed", "detail": str(exc)[:800],
                            "robots_allowed": None, "final_url": discovery_url}
                    extracted = (verification or {}).get("extracted_data") or None
                    verified_url = (verification or {}).get("final_url") or discovery_url
                verified_first_party = bool(verified_url and extracted and verification.get("status") == "reachable"
                    and verification.get("robots_allowed") is True)
                conflict_codes = _verified_companies_house_conflicts(db, candidate)
                conflict_codes.extend(_first_party_website_conflicts(
                    row, extracted, verified_first_party=verified_first_party
                ))
                if not discovery_url or _is_non_first_party_url(discovery_url):
                    row["website"] = None
                evidence = {
                    "source_type": "first_party_website" if verified_first_party else None,
                    "discovery_url": discovery_url,
                    "discovery_url_class": "third_party_lead" if discovery_url and _is_non_first_party_url(discovery_url) else "overture_website",
                    "website_url": verified_url if verified_first_party else None,
                    "verification_status": (verification or {}).get("status", "not_checked"),
                    "verification_detail": (verification or {}).get("detail"),
                    "robots_allowed": (verification or {}).get("robots_allowed"),
                    "page_title": (verification or {}).get("page_title"),
                    "content_sha256": (verification or {}).get("content_sha256"),
                    "extracted_identity_evidence": ({k: extracted.get(k) for k in (
                        "name", "street", "town", "postcode", "telephone", "email", "website",
                        "source_type", "country", "confidence", "funeral_signals", "branch_status", "has_complete_branch_address")}
                        if extracted else None),
                    "conflicting_identity_or_branch_evidence": bool(conflict_codes),
                    "conflict_codes": sorted(set(conflict_codes)),
                    "ons_boundary_code": (authority_codes[0] if len(authority_codes) == 1 else None)
                        if geography_scope == "england" else ONS_BOUNDARY_CODE if boundary else None,
                    "ons_boundary_codes": authority_codes if geography_scope == "england" else ([ONS_BOUNDARY_CODE] if boundary else []),
                    "geography_scope": geography_scope,
                    "point_in_scope": point,
                }
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
                # Defence in depth: re-check the live setting at the exact write
                # boundary, even if an assessor or future adapter regresses.
                outcome = _enforce_publication_safety_gate(
                    assessment, auto_approval_enabled=settings.auto_approve_providers,
                )
                if outcome == "auto_approved_eligible":
                    # Re-check conflicts immediately before the write. Provider,
                    # branch, source observations and audit events commit atomically.
                    conflict_now, parent_provider = _existing_provider_match(db, row)
                    if conflict_now:
                        outcome = "exception_review"
                        assessment["outcome"] = outcome
                        assessment["reasons"] = ";".join(filter(None, [assessment.get("reasons", ""), "existing_provider_or_branch_conflict"]))
                    else:
                        provider_website = row.get("website")
                        provider = parent_provider
                        created_provider = provider is None
                        if created_provider:
                            provider = Provider(
                                trading_name=row["name"], display_name=row["name"],
                                website=provider_website, provider_type="funeral_director",
                                status="published", verification_status="approved", quality_status="confirmed",
                                notes="Automatically approved from Overture Places location data under " + assessment["ruleset_version"],
                            )
                            db.add(provider)
                        branch = Branch(
                            branch_name=row["name"], address_line_1=row["address_line_1"],
                            town_city=row["town_city"], county=None,
                            postcode=row["postcode"], telephone=(str(row.get("phone"))[:40] if row.get("phone") else None),
                            email=None, website=provider_website,
                            latitude=_float_or_none(raw.get("latitude")),
                            longitude=_float_or_none(raw.get("longitude")),
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
                        first_party_obs = None
                        if verified_first_party and extracted:
                            first_party_obs = SourceObservation(
                                provider_id=provider.id, branch_id=branch.id,
                                source_type="provider_owned_website_structured_data",
                                source_name="Provider-owned website (optional corroborating evidence)",
                                source_url=evidence["website_url"],
                                confidence=_float_or_none(extracted.get("confidence")),
                                observed_data={k: extracted.get(k) for k in (
                                    "name", "street", "town", "postcode", "telephone", "email", "website",
                                    "source_type", "country", "confidence", "funeral_signals", "has_complete_branch_address")},
                                review_status="accepted",
                                notes="Optional corroborating evidence. Overture remains the published source for the branch record.",
                            )
                            db.add(first_party_obs)
                            db.flush()
                        db.add(AuditEvent(entity_type="provider", entity_id=provider.id,
                            action="auto_approved_published" if created_provider else "auto_approved_branch_added", detail={
                                "overture_candidate_id": candidate.id, "gers_id": candidate.gers_id,
                                "branch_id": branch.id, "overture_observation_id": candidate.source_observation_id,
                                "first_party_observation_id": first_party_obs.id if first_party_obs else None,
                                "overture_source_confidence": assessment.get("source_confidence"),
                                "ruleset_version": assessment.get("ruleset_version"),
                                "source_licences": assessment.get("source_licences"),
                                "ons_boundary_code": evidence.get("ons_boundary_code"),
                                "ons_boundary_codes": evidence.get("ons_boundary_codes", []),
                                "geography_scope": geography_scope,
                                "existing_parent_provider_reused": not created_provider,
                            }))
                        db.add(AuditEvent(entity_type="overture_candidate", entity_id=candidate.id,
                            action="auto_approved_published", detail={"provider_id": provider.id, "branch_id": branch.id}))
            if outcome == "awaiting_enrichment":
                attempt_count = int(previous_evidence.get("enrichment_attempt_count") or 0) + 1
                evidence["enrichment_attempt_count"] = attempt_count
                if attempt_count < MAX_ENRICHMENT_ATTEMPTS:
                    delay_days = ENRICHMENT_RETRY_DELAYS_DAYS[min(attempt_count - 1, len(ENRICHMENT_RETRY_DELAYS_DAYS) - 1)]
                    evidence["next_retry_at"] = (_now() + timedelta(days=delay_days)).isoformat()
                else:
                    evidence["next_retry_at"] = None
                    evidence["retry_limit_reached"] = True
            else:
                evidence["enrichment_attempt_count"] = int(previous_evidence.get("enrichment_attempt_count") or 0)
                evidence["next_retry_at"] = None
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
        elif checked:
            unprocessed = db.query(OvertureCandidate).filter(
                OvertureCandidate.outcome == "awaiting_enrichment",
                OvertureCandidate.status == "awaiting_enrichment",
                OvertureCandidate.last_checked_at.is_(None),
            ).count()
            if unprocessed:
                process_overture_candidates.delay(None, 20)
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


@celery_app.task(name="everguide.overture.retry_awaiting_enrichment", bind=True)
def retry_awaiting_enrichment(self):
    """Requeue due enrichment-only candidates only when scheduled processing is enabled."""
    if not settings.overture_scheduled_tasks_enabled:
        return {"status": "disabled", "requeued": 0, "retry_limits_reached": 0}
    db = SessionLocal()
    now = _now()
    requeued = 0
    exhausted = 0
    try:
        candidates = db.query(OvertureCandidate).filter(
            OvertureCandidate.outcome == "awaiting_enrichment",
            OvertureCandidate.status == "awaiting_enrichment",
            OvertureCandidate.last_checked_at.is_not(None),
        ).order_by(OvertureCandidate.last_checked_at.asc()).all()
        for candidate in candidates:
            evidence = dict(candidate.first_party_evidence or {})
            attempts = int(evidence.get("enrichment_attempt_count") or 1)
            if attempts >= MAX_ENRICHMENT_ATTEMPTS:
                if not evidence.get("retry_limit_reached"):
                    evidence["retry_limit_reached"] = True
                    evidence["next_retry_at"] = None
                    candidate.first_party_evidence = evidence
                    db.add(AuditEvent(entity_type="overture_candidate", entity_id=candidate.id,
                        action="enrichment_retry_limit_reached", detail={"attempt_count": attempts}))
                    exhausted += 1
                continue
            retry_at = evidence.get("next_retry_at")
            if retry_at:
                try:
                    due = datetime.fromisoformat(str(retry_at).replace("Z", "+00:00"))
                    if due.tzinfo is None:
                        due = due.replace(tzinfo=timezone.utc)
                except ValueError:
                    # Invalid retry metadata is not treated as permission to retry.
                    continue
            else:
                # Legacy candidates processed before retry metadata: wait at least
                # two days after their last assessment before the first retry.
                last_checked = candidate.last_checked_at
                if last_checked.tzinfo is None:
                    last_checked = last_checked.replace(tzinfo=timezone.utc)
                due = last_checked + timedelta(days=2)
            if due > now:
                continue
            candidate.last_checked_at = None
            candidate.updated_at = now
            evidence["retry_queued_at"] = now.isoformat()
            candidate.first_party_evidence = evidence
            db.add(AuditEvent(entity_type="overture_candidate", entity_id=candidate.id,
                action="enrichment_retry_queued", detail={"attempt_count": attempts, "retry_due_at": due.isoformat()}))
            requeued += 1
        db.commit()
        if requeued:
            process_overture_candidates.delay(None, 20)
        return {"status": "completed", "requeued": requeued, "retry_limits_reached": exhausted}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(name="everguide.overture.reconcile_stale_import_runs", bind=True)
def reconcile_stale_overture_import_runs(self):
    """Recover stale batches only when scheduled processing is enabled."""
    if not settings.overture_scheduled_tasks_enabled:
        return {"status": "disabled", "resumed_runs": [], "completed_runs": [], "failed_runs": []}
    db = SessionLocal()
    now = _now()
    stale_run_before = now - timedelta(hours=24)
    stale_claim_before = now - timedelta(minutes=45)
    resumed_runs = []
    completed_runs = []
    failed_runs = []
    try:
        runs = db.query(OvertureImportRun).filter(
            OvertureImportRun.status.in_(["running", "processing"]),
        ).order_by(OvertureImportRun.id.asc()).all()
        for run in runs:
            started = run.started_at or run.created_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if started > stale_run_before:
                continue
            candidate_query = db.query(OvertureCandidate).filter(OvertureCandidate.last_import_run_id == run.id)
            candidate_count = candidate_query.count()
            stale_claims = candidate_query.filter(
                OvertureCandidate.status == "processing",
                OvertureCandidate.updated_at < stale_claim_before,
            ).update({
                "status": "awaiting_enrichment", "last_checked_at": None, "updated_at": now,
            }, synchronize_session=False)
            active_claims = candidate_query.filter(OvertureCandidate.status == "processing").count()
            unprocessed = candidate_query.filter(
                OvertureCandidate.outcome == "awaiting_enrichment",
                OvertureCandidate.status == "awaiting_enrichment",
                OvertureCandidate.last_checked_at.is_(None),
            ).count()
            if active_claims:
                continue
            linked_candidates = candidate_query.all()
            processed_candidates = [item for item in linked_candidates if item.last_checked_at is not None]
            outcome_counts = Counter(item.outcome for item in processed_candidates if item.outcome)
            run.records_processed = len(processed_candidates)
            metadata = (run.outcomes or {}).get("_meta", {}) if isinstance(run.outcomes, dict) else {}
            run.outcomes = {**dict(outcome_counts), "_meta": metadata}
            if unprocessed:
                run.status = "processing"
                run.error_message = None
                resumed_runs.append(run.id)
                action = "stale_import_run_resumed"
            elif candidate_count == 0:
                run.status = "failed"
                run.error_message = "Stale import run had no linked candidate records; closed by automated recovery."
                run.completed_at = now
                failed_runs.append(run.id)
                action = "stale_import_run_closed_without_candidates"
            else:
                run.status = "completed"
                run.completed_at = now
                run.error_message = None
                completed_runs.append(run.id)
                action = "stale_import_run_completed_after_reconciliation"
            db.add(AuditEvent(entity_type="overture_import_run", entity_id=run.id, action=action, detail={
                "candidate_count": candidate_count, "stale_claims_recovered": stale_claims,
                "unprocessed_candidates": unprocessed, "reconciled_at": now.isoformat(),
                "reason": "run exceeded 24-hour recovery threshold and had no active candidate claims",
            }))
        db.commit()
        for run_id in resumed_runs:
            process_overture_candidates.delay(run_id, 20)
        return {"status": "completed", "resumed_runs": resumed_runs,
            "completed_runs": completed_runs, "failed_orphaned_runs": failed_runs}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
