#!/usr/bin/env python3
"""One-off Thurrock Google Places Aggregate vs Overture count comparison.

Google API response is kept in memory only. The output stores the aggregate
count, timestamp, attribution, and comparison methodology; never a Places
listing, Place ID, coordinate, API key, or raw response.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)

ONS_QUERY = (
    "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
    "Local_Authority_Districts_DEC_2025_Boundaries_UK_BFE/FeatureServer/0/query"
)
ONS_PARAMS = {
    "where": "LAD25CD='E06000034'",
    "outFields": "LAD25CD,LAD25NM",
    "returnGeometry": "true",
    "outSR": "4326",
    "f": "geojson",
}
GOOGLE_ENDPOINT = "https://areainsights.googleapis.com/v1:computeInsights"
GOOGLE_ATTRIBUTION = "Google Maps Platform – Places Aggregate API"


def get_boundary():
    response = requests.get(ONS_QUERY, params=ONS_PARAMS, timeout=90)
    response.raise_for_status()
    payload = response.json()
    features = payload.get("features") or []
    if not features:
        raise RuntimeError(
            "ONS boundary query returned no Thurrock feature. "
            "Check the boundary service or try again."
        )
    feature = features[0]
    props = feature.get("properties") or {}
    if props.get("LAD25CD") not in (None, "E06000034"):
        raise RuntimeError(f"Unexpected boundary code: {props.get('LAD25CD')}")
    geometry = feature.get("geometry") or {}
    if geometry.get("type") not in ("Polygon", "MultiPolygon"):
        raise RuntimeError(f"Unsupported boundary geometry: {geometry.get('type')}")
    return geometry


def signed_area(ring):
    area = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[i + 1][0], ring[i + 1][1]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def outer_rings(geometry):
    if geometry["type"] == "Polygon":
        polygons = [geometry["coordinates"]]
    else:
        polygons = geometry["coordinates"]
    rings = []
    for polygon in polygons:
        if not polygon:
            continue
        if len(polygon) > 1:
            raise RuntimeError(
                "ONS boundary contains interior rings. The Aggregate API custom "
                "polygon format supports one exterior ring; refusing to silently "
                "change the boundary."
            )
        ring = polygon[0]
        if len(ring) < 4:
            raise RuntimeError("Boundary polygon ring has fewer than four vertices.")
        # Google requires counter-clockwise vertex order.
        if signed_area(ring) < 0:
            ring = list(reversed(ring))
        # Close ring explicitly.
        if ring[0] != ring[-1]:
            ring = list(ring) + [ring[0]]
        rings.append(ring)
    if not rings:
        raise RuntimeError("No exterior boundary rings found.")
    return rings


def call_count(api_key, ring, statuses):
    # The API accepts a single exterior polygon per request. Thurrock's
    # MultiPolygon components are queried independently and summed.
    polygon = {
        "coordinates": [
            {"latitude": float(lat), "longitude": float(lon)}
            for lon, lat in ring
        ]
    }
    body = {
        "insights": ["INSIGHT_COUNT"],
        "filter": {
            "locationFilter": {"customArea": {"polygon": polygon}},
            "typeFilter": {"includedTypes": ["funeral_home"]},
            "operatingStatus": statuses,
        },
    }
    response = requests.post(
        GOOGLE_ENDPOINT,
        headers={
            "X-Goog-Api-Key": api_key,
            "Content-Type": "application/json",
        },
        json=body,
        timeout=90,
    )
    if not response.ok:
        # Avoid writing the request or key to disk; show only Google's error body.
        raise RuntimeError(
            f"Google Places Aggregate API returned HTTP {response.status_code}: "
            f"{response.text[:1500]}"
        )
    data = response.json()
    if "count" not in data:
        raise RuntimeError(f"Google response did not contain a count: {data}")
    return int(data["count"])


def google_counts(api_key, geometry):
    rings = outer_rings(geometry)
    operational = 0
    all_statuses = 0
    for ring in rings:
        operational += call_count(
            api_key, ring, ["OPERATING_STATUS_OPERATIONAL"]
        )
        all_statuses += call_count(
            api_key,
            ring,
            [
                "OPERATING_STATUS_OPERATIONAL",
                "OPERATING_STATUS_TEMPORARILY_CLOSED",
                "OPERATING_STATUS_PERMANENTLY_CLOSED",
            ],
        )
        time.sleep(0.25)
    return operational, all_statuses, len(rings)


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main():
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(
            "GOOGLE_MAPS_API_KEY is not set. Set it in this PowerShell session "
            "before running run.ps1."
        )

    print("Fetching the official Thurrock local-authority boundary from ONS...")
    geometry = get_boundary()
    print("Querying Google Places Aggregate API for funeral_home counts...")
    operational, all_statuses, polygon_count = google_counts(api_key, geometry)

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    stamp = now.isoformat().replace("+00:00", "Z")

    # The benchmark comes from the previously completed Overture Thurrock pilot
    # and its manual reconciliation. It is not a Google-derived figure.
    overture_rows = [
        {
            "measure": "Overture raw records in pilot",
            "count": 16,
            "interpretation": "Raw candidate rows; includes adjacent services, geographic false match and duplicates.",
        },
        {
            "measure": "Overture likely Thurrock funeral-provider observations",
            "count": 12,
            "interpretation": "Manual screening after excluding four adjacent/out-of-area observations; some branch rows may duplicate.",
        },
        {
            "measure": "Overture likely distinct provider identities",
            "count": 8,
            "interpretation": "Heuristic reconciliation; not eight independently approved providers.",
        },
    ]

    rows = [
        {
            "source": "Google Places Aggregate API",
            "measure": "Operational funeral_home places",
            "count": operational,
            "attribution": GOOGLE_ATTRIBUTION,
            "as_of_utc": stamp,
            "method": "INSIGHT_COUNT; includedTypes=funeral_home; operational status; official ONS Thurrock LAD boundary.",
        },
        {
            "source": "Google Places Aggregate API",
            "measure": "Funeral_home places, all operating statuses",
            "count": all_statuses,
            "attribution": GOOGLE_ATTRIBUTION,
            "as_of_utc": stamp,
            "method": "INSIGHT_COUNT; includedTypes=funeral_home; operational + temporarily closed + permanently closed; official ONS Thurrock LAD boundary.",
        },
    ]
    for item in overture_rows:
        rows.append(
            {
                "source": "Overture Places",
                "measure": item["measure"],
                "count": item["count"],
                "attribution": "Overture Maps Foundation; see source dataset licence and source lineage.",
                "as_of_utc": "Previous Thurrock pilot",
                "method": item["interpretation"],
            }
        )

    write_csv(OUT / "thurrock_aggregate_comparison.csv", rows)

    report = f"""# Thurrock funeral-home coverage comparison

**Run time:** {stamp}  
**Boundary:** Thurrock local authority, ONS LAD code E06000034, December 2025 boundary  
**Google source:** {GOOGLE_ATTRIBUTION}  
**Google query:** Places Aggregate API `INSIGHT_COUNT`, type `funeral_home`  
**Boundary components queried:** {polygon_count}

## Results

| Source / measure | Count |
|---|---:|
| Google — operational `funeral_home` places | {operational} |
| Google — all listed operating statuses | {all_statuses} |
| Overture — raw pilot records | 16 |
| Overture — likely local funeral-provider observations | 12 |
| Overture — likely distinct provider identities | 8 |

## Interpretation

Google's count is a category-based aggregate, not a verified count of funeral-director businesses. A business may be missing, miscategorised, or represented differently in Google's place model. Overture's figures are from the earlier Thurrock pilot and manual reconciliation; the 12 observations and 8 identities are screening estimates, not approved provider records.

The comparison is therefore a coverage indicator, not proof that either source is complete or that the counts are directly equivalent.

## Data handling

This tool requested aggregate counts only. It did not request or save Google business names, addresses, Place IDs, coordinates, or raw API responses. The API key was read from the `GOOGLE_MAPS_API_KEY` environment variable and was not written to disk.

Google attribution: **{GOOGLE_ATTRIBUTION}**.

The Google count is a Places Aggregate API result. Google's policies require attribution when using a Places Aggregate API count as a standalone metric. The current Google service-specific terms also limit use of POI counts in derived customer values and specify a 30-day temporary caching limit for counts used for that purpose. Review the agreement governing your Google Cloud billing account before using this result beyond this one-off research comparison.

## Method and limitations

- The official ONS Thurrock polygon was used, not a broad postcode or town search.
- If the local-authority geometry contains multiple disconnected polygon components, each component was queried separately and the aggregate counts summed.
- The `funeral_home` Place Type is Google's category, not a bespoke funeral-director taxonomy.
- "All listed operating statuses" includes operational, temporarily closed and permanently closed places.
- Overture comparison figures were manually reconciled in the earlier pilot and are not a new Overture refresh.
"""
    (OUT / "thurrock_aggregate_comparison.md").write_text(report, encoding="utf-8")

    metadata = {
        "tool_version": "2.7.0",
        "run_at_utc": stamp,
        "boundary": "ONS Local Authority Districts December 2025",
        "lad_code": "E06000034",
        "google_service": "Places Aggregate API",
        "google_insight": "INSIGHT_COUNT",
        "google_place_type": "funeral_home",
        "google_operational_count": operational,
        "google_all_statuses_count": all_statuses,
        "boundary_polygon_components": polygon_count,
        "google_attribution": GOOGLE_ATTRIBUTION,
        "raw_google_response_saved": False,
        "google_place_details_requested": False,
        "api_key_saved": False,
    }
    (OUT / "run_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    print("\nCompleted.")
    print(f"Google operational funeral_home count: {operational}")
    print(f"Google all-status funeral_home count: {all_statuses}")
    print("Overture benchmark: 16 raw / 12 likely local observations / 8 likely identities")
    print(f"Report: {OUT / 'thurrock_aggregate_comparison.md'}")
    print(f"CSV:    {OUT / 'thurrock_aggregate_comparison.csv'}")


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as exc:
        raise SystemExit(f"Network/API request failed: {exc}")
