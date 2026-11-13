#!/usr/bin/env python3
"""Review Overture Places candidates for Everguide without changing its database.

This is a local, count-only/source-local quality review. It does not call Google,
retrieve individual Google listings, or create/merge/delete/publish Everguide
records.

Install:
    python -m pip install -r google_analysis/requirements.txt

Run from the Everguide project root:
    python google_analysis/review_overture_candidates.py \
      --input google_analysis/overture_candidates.csv \
      --out google_analysis/quality_review

The script uses the ONS December 2025 Thurrock boundary (E06000034). It can
download the official GeoJSON boundary or accept a previously downloaded local
GeoJSON file with --boundary-file. If the boundary cannot be verified, it fails
closed unless --allow-no-boundary is explicitly supplied.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
from shapely.geometry import Point, shape
from shapely.ops import unary_union

# Reuse the exact same quality rules as the FastAPI application.
API_APP_PATH = Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(API_APP_PATH))

from app.candidate_quality import (
    THURROCK_OUTWARD_CODES,
    candidate_location_flags,
    classify_service,
    exact_branch_fingerprint,
    normalise_identity_name,
    normalise_phone,
    normalise_postcode,
    postcode_outward_code,
    provider_identity_key,
    website_domain,
)

ONS_QUERY_URL = (
    "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
    "Counties_and_Unitary_Authorities_December_2025_Boundaries_UK_BFE/"
    "FeatureServer/0/query"
)
BOUNDARY_CODE = "E06000034"


def fetch_boundary():
    params = {
        "where": f"CTYUA25CD='{BOUNDARY_CODE}'",
        "outFields": "CTYUA25CD,CTYUA25NM",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    }
    response = requests.get(ONS_QUERY_URL, params=params, timeout=60)
    response.raise_for_status()
    data = response.json()
    features = data.get("features", [])
    if len(features) != 1:
        raise RuntimeError(
            f"Expected one ONS feature for {BOUNDARY_CODE}; received {len(features)}"
        )
    feature = features[0]
    props = feature.get("properties", {})
    if props.get("CTYUA25CD") != BOUNDARY_CODE:
        raise RuntimeError(f"ONS returned unexpected boundary properties: {props}")
    geometry = shape(feature["geometry"])
    if not geometry.is_valid:
        raise RuntimeError("ONS boundary geometry is invalid")
    return geometry, props.get("CTYUA25NM", "Thurrock")


def load_boundary_file(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("type") == "FeatureCollection":
        features = data.get("features") or []
        matches = [
            f for f in features
            if (f.get("properties") or {}).get("CTYUA25CD") == BOUNDARY_CODE
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"Boundary GeoJSON must contain exactly one feature with "
                f"CTYUA25CD={BOUNDARY_CODE}; found {len(matches)}"
            )
        geom = shape(matches[0]["geometry"])
    elif data.get("type") == "Feature":
        props = data.get("properties") or {}
        if props.get("CTYUA25CD") != BOUNDARY_CODE:
            raise RuntimeError(f"Boundary feature is not {BOUNDARY_CODE}")
        geom = shape(data["geometry"])
    else:
        raise RuntimeError("Boundary file must be a GeoJSON Feature or FeatureCollection")
    if not geom.is_valid:
        raise RuntimeError("Boundary GeoJSON geometry is invalid")
    return geom, "Thurrock"


def haversine_m(lat1, lon1, lat2, lon2):
    radius = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise RuntimeError("Input CSV has no header row")
        rows = list(reader)
    if not rows:
        raise RuntimeError("Input CSV contains no candidate rows")
    required = {"name", "postcode", "latitude", "longitude"}
    missing = required - set(reader.fieldnames)
    if missing:
        raise RuntimeError(f"Input CSV is missing required columns: {', '.join(sorted(missing))}")
    return rows, reader.fieldnames


def review_row(row, boundary):
    name = row.get("name", "")
    service_class = classify_service(
        name=name,
        basic_category=row.get("basic_category", ""),
        taxonomy_primary=row.get("taxonomy_primary", ""),
        website=row.get("website", ""),
        description=row.get("description", ""),
    )

    point_status = "not_verified"
    point_in_boundary = None
    try:
        lat = float(row.get("latitude"))
        lon = float(row.get("longitude"))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("coordinate outside valid range")
        if boundary is not None:
            point_in_boundary = bool(boundary.covers(Point(lon, lat)))
            point_status = "inside" if point_in_boundary else "outside"
        else:
            point_status = "boundary_unavailable"
    except (TypeError, ValueError):
        lat = lon = None
        point_status = "missing_or_invalid"
    flags = candidate_location_flags(
        postcode=row.get("postcode", ""),
        latitude=row.get("latitude"),
        longitude=row.get("longitude"),
        point_in_boundary=point_in_boundary,
        expected_outward_codes=THURROCK_OUTWARD_CODES,
    )

    if point_status == "outside":
        flags.append("POINT_OUTSIDE_THURROCK_BOUNDARY")
    elif point_status in {"boundary_unavailable", "not_verified"}:
        flags.append("BOUNDARY_NOT_VERIFIED")
    if point_status == "missing_or_invalid" and "INVALID_COORDINATES" not in flags:
        flags.append("COORDINATES_MISSING_OR_INVALID")

    decision = "retain_candidate_pending_provider_verification"
    if service_class != "funeral_director_candidate":
        decision = "exclude_from_funeral_director_category"
    elif flags:
        decision = "hold_for_manual_location_review"

    result = {
        "source_record_id": row.get("gers_id", ""),
        "candidate_name": name,
        "service_class": service_class,
        "basic_category": row.get("basic_category", ""),
        "taxonomy_primary": row.get("taxonomy_primary", ""),
        "source_confidence": row.get("confidence", ""),
        "address": row.get("address", ""),
        "postcode": row.get("postcode", ""),
        "postcode_outward_code": postcode_outward_code(row.get("postcode", "")),
        "phone": row.get("phone", ""),
        "normalised_phone": normalise_phone(row.get("phone", "")),
        "website": row.get("website", ""),
        "website_domain": website_domain(row.get("website", "")),
        "latitude": row.get("latitude", ""),
        "longitude": row.get("longitude", ""),
        "point_in_thurrock": point_status,
        "location_flags": ";".join(sorted(set(flags))),
        "review_decision": decision,
        "possible_duplicate_source_flag": row.get("possible_duplicate", ""),
        "possible_duplicate_source_count": row.get("possible_duplicate_count", ""),
        "exact_branch_fingerprint": exact_branch_fingerprint(
            name=name, postcode=row.get("postcode", ""),
            phone=row.get("phone", ""), website=row.get("website", ""),
        ) or "",
        "provider_identity_key": provider_identity_key(
            name=name, website=row.get("website", ""), phone=row.get("phone", ""),
        ) or "",
        "provider_group_id": "",
        "possible_duplicate_group_id": "",
        "source": row.get("source", ""),
        "licence_note": row.get("licence_note", ""),
    }
    return result, (lat, lon) if lat is not None and lon is not None else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Overture Places candidate CSV")
    parser.add_argument("--out", default="google_analysis/quality_review")
    parser.add_argument("--boundary-file", help="Optional official Thurrock ONS GeoJSON")
    parser.add_argument(
        "--allow-no-boundary", action="store_true",
        help="Allow a report without point-in-polygon verification (all candidate rows held)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, _ = read_csv(input_path)

    try:
        if args.boundary_file:
            boundary, boundary_name = load_boundary_file(Path(args.boundary_file))
            boundary_source = str(Path(args.boundary_file))
        else:
            boundary, boundary_name = fetch_boundary()
            boundary_source = "ONS ArcGIS FeatureServer"
    except Exception as exc:
        if not args.allow_no_boundary:
            raise SystemExit(
                f"Could not verify the official ONS boundary: {exc}\n"
                "Supply --boundary-file or explicitly use --allow-no-boundary."
            )
        boundary, boundary_name = None, "Thurrock"
        boundary_source = f"not verified: {exc}"

    reviewed = []
    coordinates = []
    for row in rows:
        result, coord = review_row(row, boundary)
        reviewed.append(result)
        coordinates.append(coord)

    # Same-branch duplicates: same normalised name, postcode and phone (or
    # website domain where phone is absent). They are flagged, never deleted.
    duplicate_groups = defaultdict(list)
    for idx, item in enumerate(reviewed):
        key = item["exact_branch_fingerprint"]
        if key:
            duplicate_groups[key].append(idx)

    duplicate_group_no = 0
    for indices in duplicate_groups.values():
        if len(indices) < 2:
            continue
        duplicate_group_no += 1
        group_id = f"DG{duplicate_group_no:03d}"
        valid_coords = [coordinates[i] for i in indices if coordinates[i] is not None]
        max_separation = 0.0
        for a in range(len(valid_coords)):
            for b in range(a + 1, len(valid_coords)):
                max_separation = max(
                    max_separation,
                    haversine_m(*valid_coords[a], *valid_coords[b]),
                )
        for idx in indices:
            reviewed[idx]["possible_duplicate_group_id"] = group_id
            flags = [f for f in reviewed[idx]["location_flags"].split(";") if f]
            flags.append("POSSIBLE_DUPLICATE_SAME_BRANCH")
            if max_separation > 250:
                flags.append("DUPLICATE_COORDINATE_VARIANCE_OVER_250M")
            reviewed[idx]["location_flags"] = ";".join(sorted(set(flags)))
            if reviewed[idx]["review_decision"] == "retain_candidate_pending_provider_verification":
                reviewed[idx]["review_decision"] = "retain_but_review_possible_duplicate"

    # Same provider identity may legitimately have multiple branches. Group
    # conservatively by same normalised name plus a shared own domain OR phone.
    # Pairwise union also bridges records where one branch has no website.
    provider_indices = [
        i for i, item in enumerate(reviewed)
        if item["service_class"] == "funeral_director_candidate"
    ]
    parent = {i: i for i in provider_indices}

    def find_provider(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union_provider(a, b):
        ra, rb = find_provider(a), find_provider(b)
        if ra != rb:
            parent[rb] = ra

    for pos, i in enumerate(provider_indices):
        a = reviewed[i]
        a_name = normalise_identity_name(a["candidate_name"])
        a_domain = website_domain(a["website"])
        a_phone = normalise_phone(a["phone"])
        for j in provider_indices[pos + 1:]:
            b = reviewed[j]
            if not a_name or a_name != normalise_identity_name(b["candidate_name"]):
                continue
            b_domain = website_domain(b["website"])
            b_phone = normalise_phone(b["phone"])
            shared_domain = bool(a_domain and b_domain and a_domain == b_domain)
            shared_phone = bool(a_phone and b_phone and a_phone == b_phone)
            if shared_domain or shared_phone:
                union_provider(i, j)

    provider_members = defaultdict(list)
    for idx in provider_indices:
        provider_members[find_provider(idx)].append(idx)

    for group_no, indices in enumerate(provider_members.values(), start=1):
        group_id = f"PG{group_no:03d}"
        branch_keys = {
            reviewed[i]["exact_branch_fingerprint"] or f"row:{i + 1}"
            for i in indices
        }
        postcodes = {normalise_postcode(reviewed[i]["postcode"]) for i in indices}
        for idx in indices:
            reviewed[idx]["provider_group_id"] = group_id
            if len(branch_keys) > 1 and len(postcodes) > 1:
                flags = [f for f in reviewed[idx]["location_flags"].split(";") if f]
                flags.append("POSSIBLE_MULTI_BRANCH_PROVIDER")
                reviewed[idx]["location_flags"] = ";".join(sorted(set(flags)))

    # If the same provider name and phone appear at several postcodes, flag for
    # manual reconciliation even if the websites are absent or differ.
    name_phone_postcodes = defaultdict(set)
    for item in reviewed:
        name = normalise_identity_name(item["candidate_name"])
        phone = normalise_phone(item["phone"])
        postcode = normalise_postcode(item["postcode"])
        if name and phone and postcode:
            name_phone_postcodes[(name, phone)].add(postcode)
    for item in reviewed:
        key = (normalise_identity_name(item["candidate_name"]), normalise_phone(item["phone"]))
        if key[0] and key[1] and len(name_phone_postcodes[key]) > 1:
            flags = [f for f in item["location_flags"].split(";") if f]
            flags.append("SAME_NAME_PHONE_MULTIPLE_POSTCODES_REVIEW")
            item["location_flags"] = ";".join(sorted(set(flags)))
            if item["review_decision"] == "retain_candidate_pending_provider_verification":
                item["review_decision"] = "retain_but_review_address_relationship"

    # Without an authoritative boundary every otherwise eligible provider is
    # held, even when its postcode looks plausible.
    if boundary is None:
        for item in reviewed:
            if item["service_class"] == "funeral_director_candidate":
                item["review_decision"] = "hold_for_manual_location_review"

    out_csv = out_dir / "candidate_quality_review.csv"
    with out_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(reviewed[0].keys()))
        writer.writeheader()
        writer.writerows(reviewed)

    service_counts = Counter(x["service_class"] for x in reviewed)
    decision_counts = Counter(x["review_decision"] for x in reviewed)
    eligible = [
        x for x in reviewed
        if x["service_class"] == "funeral_director_candidate"
        and x["point_in_thurrock"] == "inside"
        and "POSTCODE_MISSING_OR_INVALID" not in x["location_flags"]
        and "POSTCODE_OUTSIDE_EXPECTED_AREA" not in x["location_flags"]
        and "POSTCODE_COORDINATE_CONFLICT" not in x["location_flags"]
    ]
    unique_branch_keys = {
        x["exact_branch_fingerprint"] for x in eligible if x["exact_branch_fingerprint"]
    }
    provider_ids = {x["provider_group_id"] for x in eligible if x["provider_group_id"]}
    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "boundary_name": boundary_name,
        "boundary_code": BOUNDARY_CODE,
        "boundary_source": boundary_source,
        "input_file": str(input_path),
        "records_reviewed": len(reviewed),
        "service_class_counts": dict(service_counts),
        "review_decision_counts": dict(decision_counts),
        "funeral_director_candidate_rows": sum(
            1 for x in reviewed if x["service_class"] == "funeral_director_candidate"
        ),
        "inside_boundary_funeral_director_rows": sum(
            1 for x in reviewed
            if x["service_class"] == "funeral_director_candidate"
            and x["point_in_thurrock"] == "inside"
        ),
        "geographically_eligible_rows_pending_provider_verification": len(eligible),
        "unique_branch_fingerprints_among_eligible_rows": len(unique_branch_keys),
        "suggested_provider_groups_among_eligible_rows": len(provider_ids),
        "possible_duplicate_groups": duplicate_group_no,
        "source_confidence_is_not_verification": True,
        "production_database_accessed": False,
        "google_places_data_used": False,
        "important_note": (
            "Review signals only. No records are created, merged, deleted, "
            "published or changed in Everguide."
        ),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    report_lines = [
        "# Thurrock Overture candidate quality review",
        "",
        f"- Boundary: {boundary_name} ({BOUNDARY_CODE})",
        f"- Boundary source: {boundary_source}",
        f"- Candidate rows reviewed: {len(reviewed)}",
        f"- Funeral-director candidate rows: {summary['funeral_director_candidate_rows']}",
        f"- Inside-boundary funeral-director rows: {summary['inside_boundary_funeral_director_rows']}",
        f"- Geographically eligible rows (still awaiting provider verification): {len(eligible)}",
        f"- Unique branch fingerprints among eligible rows: {len(unique_branch_keys)}",
        f"- Suggested provider groups among eligible rows: {len(provider_ids)}",
        f"- Possible duplicate groups: {duplicate_group_no}",
        "",
        "## Service classification",
        "",
    ]
    report_lines.extend(f"- {key}: {value}" for key, value in sorted(service_counts.items()))
    report_lines += ["", "## Review decisions", ""]
    report_lines.extend(f"- {key}: {value}" for key, value in sorted(decision_counts.items()))
    report_lines += [
        "",
        "## Interpretation guardrails",
        "",
        "- Overture confidence is source metadata, not proof of provider identity.",
        "- A postcode area is a screening rule; the ONS polygon is used for point containment.",
        "- A point inside Thurrock with a non-Thurrock postcode is held as a conflict.",
        "- A provider can have multiple genuine branches; branch records are not merged.",
        "- Possible duplicate observations are flagged, not deleted.",
        "- This report does not use Google Places content and does not change Everguide's database.",
        "- Check the licence note and upstream dataset terms before reusing candidate data.",
        "",
    ]
    (out_dir / "pilot_report.md").write_text("\n".join(report_lines), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"\nWrote: {out_csv}")
    print(f"Wrote: {out_dir / 'summary.json'}")
    print(f"Wrote: {out_dir / 'pilot_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
