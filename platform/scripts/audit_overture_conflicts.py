"""Read-only audit of same-name/postcode Overture funeral-director conflicts."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from sqlalchemy import text

from app.candidate_quality import (
    classify_service,
    normalise_identity_name,
    normalise_phone,
    normalise_postcode,
    website_domain,
)
from app.config import settings
from app.database import SessionLocal
from app.models import Branch, OvertureCandidate, OvertureCompanyLink, Provider
from app.overture_approval import RULESET_VERSION, assess_overture_candidate
from app.overture_tasks import (
    OVERTURE_LOCATION_CONFLICT_DISTANCE_METRES,
    _normalised_assessment_row,
    _existing_provider_match,
    _read_boundary_cache,
    _verified_companies_house_conflicts,
    _overture_coordinate,
    _overture_coordinate_distance_metres,
)


def _candidate_record(candidate: OvertureCandidate) -> dict:
    raw = dict(candidate.raw_data or {})
    row = _normalised_assessment_row(raw)
    name = candidate.candidate_name or row.get("name") or ""
    return {
        "id": candidate.id,
        "gers_id": candidate.gers_id,
        "name": name,
        "postcode": candidate.postcode or row.get("postcode") or "",
        "postcode_key": normalise_postcode(candidate.postcode or row.get("postcode")),
        "name_key": normalise_identity_name(name),
        "service_class": classify_service(
            name=name,
            basic_category=row.get("basic_category"),
            taxonomy_primary=row.get("taxonomy_primary"),
            website="",
            description=row.get("description", ""),
        ),
        "street": str(row.get("address_line_1") or row.get("address") or "").strip(),
        "street_key": normalise_identity_name(row.get("address_line_1") or row.get("address")),
        "town": str(row.get("town_city") or row.get("town") or row.get("locality") or "").strip(),
        "phone": normalise_phone(row.get("phone") or raw.get("phone")),
        "domain": website_domain(row.get("website")),
        "coordinate": _overture_coordinate(raw),
        "stored_outcome": candidate.outcome,
        "stored_status": candidate.status,
    }


def build_report(db, *, reassess: bool = False) -> dict:
    # SET TRANSACTION READ ONLY is the first database statement in this session.
    db.execute(text("SET TRANSACTION READ ONLY"))
    candidates = db.query(OvertureCandidate).order_by(OvertureCandidate.id).all()
    provider_count = db.query(Provider).count()
    branch_count = db.query(Branch).count()
    verified_link_count = db.query(OvertureCompanyLink).filter(
        OvertureCompanyLink.status == "verified",
        OvertureCompanyLink.reviewed_at.is_not(None),
    ).count()
    service_counts = Counter()
    groups = defaultdict(list)
    for candidate in candidates:
        item = _candidate_record(candidate)
        service_counts[item["service_class"]] += 1
        if (item["service_class"] == "funeral_director_candidate"
                and item["postcode_key"] and item["name_key"]):
            groups[(item["postcode_key"], item["name_key"])].append(item)

    group_results = []
    duplicate_candidate_ids = set()
    coordinate_candidate_ids = set()
    groups_with_duplicates = set()
    groups_with_coordinate_conflicts = set()
    distance_bands = Counter()
    pair_count = 0
    for key, members in groups.items():
        if len(members) < 2:
            continue
        pairs = []
        duplicate_group = False
        coordinate_group = False
        for first, second in combinations(members, 2):
            matched_signals = []
            if first["street_key"] and first["street_key"] == second["street_key"]:
                matched_signals.append("street")
            if first["phone"] and first["phone"] == second["phone"]:
                matched_signals.append("phone")
            if first["domain"] and first["domain"] == second["domain"]:
                matched_signals.append("website_domain")
            distance = _overture_coordinate_distance_metres(
                first["coordinate"], second["coordinate"]
            )
            if distance is not None and distance > OVERTURE_LOCATION_CONFLICT_DISTANCE_METRES and matched_signals:
                conflict_type = "coordinate_conflict"
                coordinate_group = True
                coordinate_candidate_ids.update((first["id"], second["id"]))
            else:
                conflict_type = "possible_same_location_duplicate"
                duplicate_group = True
                duplicate_candidate_ids.update((first["id"], second["id"]))
            if distance is None:
                band = "missing_coordinate"
            elif distance <= 25:
                band = "0_to_25m"
            elif distance <= 100:
                band = "25_to_100m"
            elif distance <= 500:
                band = "100_to_500m"
            elif distance <= 2000:
                band = "500m_to_2km"
            else:
                band = "over_2km"
            distance_bands[band] += 1
            pair_count += 1
            pairs.append({
                "first_candidate_id": first["id"],
                "first_gers_id": first["gers_id"],
                "second_candidate_id": second["id"],
                "second_gers_id": second["gers_id"],
                "conflict_type": conflict_type,
                "distance_metres": round(distance, 1) if distance is not None else None,
                "matched_identity_signals": matched_signals,
                "first_coordinate": first["coordinate"],
                "second_coordinate": second["coordinate"],
            })
        if duplicate_group:
            groups_with_duplicates.add(key)
        if coordinate_group:
            groups_with_coordinate_conflicts.add(key)
        group_results.append({
            "postcode_key": key[0],
            "normalized_name": key[1],
            "candidate_count": len(members),
            "has_duplicate_hold": duplicate_group,
            "has_coordinate_conflict": coordinate_group,
            "candidates": members,
            "pairs": pairs,
        })

    hypothetical_outcomes = Counter()
    geography_counts = Counter()
    boundary_polygon_count = None
    if reassess:
        # Never fetch an ONS boundary here. Require the validated local cache.
        geometry = _read_boundary_cache("england")
        if geometry is None:
            raise RuntimeError(
                "A valid cached England boundary is required; the reassessment makes no ONS network requests."
            )
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        boundary_polygon_count = len(polygons)
        geometry_json = json.dumps({"type": geometry["type"], "coordinates": geometry["coordinates"]})
        spatial_rows = db.execute(text("""
            WITH boundary AS MATERIALIZED (
                SELECT ST_SetSRID(ST_GeomFromGeoJSON(:geometry_json), 4326) AS geom
            )
            SELECT candidate.id,
                CASE
                    WHEN candidate.raw_data->>'longitude' ~ '^[+-]?[0-9]+([.][0-9]+)?$'
                     AND candidate.raw_data->>'latitude' ~ '^[+-]?[0-9]+([.][0-9]+)?$'
                     AND (candidate.raw_data->>'longitude')::double precision BETWEEN -180 AND 180
                     AND (candidate.raw_data->>'latitude')::double precision BETWEEN -90 AND 90
                    THEN ST_Covers(
                        boundary.geom,
                        ST_SetSRID(
                            ST_MakePoint(
                                (candidate.raw_data->>'longitude')::double precision,
                                (candidate.raw_data->>'latitude')::double precision
                            ),
                            4326
                        )
                    )
                    ELSE NULL
                END AS inside_england
            FROM overture_candidates AS candidate
            CROSS JOIN boundary
        """), {"geometry_json": geometry_json}).all()
        inside_by_id = {int(row[0]): row[1] for row in spatial_rows}

        for candidate in candidates:
            raw = dict(candidate.raw_data or {})
            row = _normalised_assessment_row(raw)
            inside_england = inside_by_id.get(candidate.id)
            geography_counts[str(inside_england).lower()] += 1

            provider_conflict = False
            if provider_count or branch_count:
                provider_conflict, _ = _existing_provider_match(db, row)
            evidence = dict(candidate.first_party_evidence or {})
            if verified_link_count:
                codes = _verified_companies_house_conflicts(db, candidate)
                if codes:
                    evidence["conflict_codes"] = list(dict.fromkeys(
                        list(evidence.get("conflict_codes") or []) + codes
                    ))
            assessment = assess_overture_candidate(
                row,
                first_party_evidence=evidence,
                point_in_england=inside_england,
                geography_scope="england",
                duplicate_conflict=candidate.id in duplicate_candidate_ids,
                location_conflict=candidate.id in coordinate_candidate_ids,
                existing_provider_conflict=provider_conflict,
                auto_approval_enabled=True,
            )
            hypothetical_outcomes[assessment["outcome"]] += 1

    group_results.sort(key=lambda group: (
        not group["has_coordinate_conflict"],
        -max((pair["distance_metres"] or 0) for pair in group["pairs"]),
        group["postcode_key"],
        group["normalized_name"],
    ))
    return {
        "report_type": "read_only_overture_identity_conflict_audit",
        "read_only": True,
        "assessment_ruleset": RULESET_VERSION,
        "assessment_mode": (
                "read-only hypothetical; automatic approval assumed enabled"
                if reassess else "conflict grouping only; no candidate outcomes recomputed"
            ),
        "runtime_switches": {
            "auto_approve_providers": settings.auto_approve_providers,
            "overture_auto_process": settings.overture_auto_process,
            "overture_feed_enabled": settings.overture_feed_enabled,
            "overture_scheduled_tasks_enabled": settings.overture_scheduled_tasks_enabled,
            "price_enrichment_enabled": settings.price_enrichment_enabled,
        },
        "existing_provider_count": db.query(Provider).count(),
        "existing_branch_count": db.query(Branch).count(),
        "verified_company_link_count": db.query(OvertureCompanyLink).filter(
            OvertureCompanyLink.status == "verified",
            OvertureCompanyLink.reviewed_at.is_not(None),
            OvertureCompanyLink.reviewed_by.is_not(None),
            OvertureCompanyLink.evidence_json.is_not(None),
        ).count(),
        "candidate_count": len(candidates),
        "hypothetical_outcome_counts": dict(sorted(hypothetical_outcomes.items())) if reassess else None,
        "geography_point_counts": dict(sorted(geography_counts.items())) if reassess else None,
        "boundary_polygon_count": boundary_polygon_count,
        "boundary_evaluation_method": "PostGIS ST_Covers with cached England geometry" if reassess else None,
        "service_class_counts": dict(sorted(service_counts.items())),
        "funeral_director_duplicate_groups": len(group_results),
        "candidate_pair_count": pair_count,
        "groups_with_possible_duplicate_holds": len(groups_with_duplicates),
        "groups_with_coordinate_conflicts": len(groups_with_coordinate_conflicts),
        "candidate_records_with_possible_duplicate_holds": len(duplicate_candidate_ids),
        "candidate_records_with_coordinate_conflicts": len(coordinate_candidate_ids),
        "candidate_records_with_any_conflict": len(duplicate_candidate_ids | coordinate_candidate_ids),
        "pair_distance_bands": dict(sorted(distance_bands.items())),
        "groups": group_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="Write JSON report to this path; defaults to stdout.")
    parser.add_argument(
        "--reassess",
        action="store_true",
        help="Recompute hypothetical outcomes using only the cached England boundary; makes no writes or network requests.",
    )
    args = parser.parse_args()
    db = SessionLocal()
    try:
        report = build_report(db, reassess=args.reassess)
    finally:
        db.rollback()
        db.close()
    serialized = json.dumps(report, ensure_ascii=False, indent=2, default=list)
    if args.output:
        Path(args.output).write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)


if __name__ == "__main__":
    main()

