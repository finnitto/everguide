#!/usr/bin/env python3
"""
Thurrock Places Aggregate category-coverage test.

Uses the ONS December 2025 Thurrock boundary (E06000034) and count-only
Places Aggregate API requests. It does not request or save individual places.

The test compares:
  1. funeral_home (broad type match)
  2. funeral_home (primary type)
  3. cemetery (adjacent-service comparator, NOT a funeral-director count)

Google's supported place types are versioned and can change. This script uses
only the documented `funeral_home` and `cemetery` types. It deliberately does
not invent types such as "funeral_director" or "mortuary".

Install:
    python -m pip install requests shapely

PowerShell:
    $env:GOOGLE_MAPS_API_KEY = "YOUR_KEY"
    python .\\thurrock_places_aggregate_categories.py

Keep your key local. Do not commit it or paste it into chat.
"""

import os
import sys
import requests
from shapely.geometry import shape, Polygon, MultiPolygon
from shapely.geometry.polygon import orient

ONS_QUERY_URL = (
    "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
    "Counties_and_Unitary_Authorities_December_2025_Boundaries_UK_BFE/"
    "FeatureServer/0/query"
)
GOOGLE_URL = "https://areainsights.googleapis.com/v1:computeInsights"
BOUNDARY_CODE = "E06000034"
MAX_VERTICES = 7000
TIMEOUT_SECONDS = 60


def fetch_thurrock_polygons():
    params = {
        "where": f"CTYUA25CD='{BOUNDARY_CODE}'",
        "outFields": "CTYUA25CD,CTYUA25NM",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    }
    r = requests.get(ONS_QUERY_URL, params=params, timeout=TIMEOUT_SECONDS)
    r.raise_for_status()
    data = r.json()
    features = data.get("features", [])
    if len(features) != 1:
        raise RuntimeError(
            f"Expected one ONS feature for {BOUNDARY_CODE}; received {len(features)}."
        )

    feature = features[0]
    props = feature.get("properties", {})
    if props.get("CTYUA25CD") != BOUNDARY_CODE:
        raise RuntimeError(f"Unexpected boundary feature: {props}")

    geom = shape(feature["geometry"])
    if not geom.is_valid:
        raise RuntimeError("ONS boundary geometry is invalid; stopping.")

    if isinstance(geom, Polygon):
        polygons = [geom]
    elif isinstance(geom, MultiPolygon):
        polygons = list(geom.geoms)
    else:
        raise RuntimeError(f"Unsupported geometry type: {geom.geom_type}")

    for i, poly in enumerate(polygons, start=1):
        if poly.interiors:
            raise RuntimeError(
                f"Boundary component {i} contains holes. Stopping rather than "
                "silently filling them."
            )
        if len(poly.exterior.coords) > MAX_VERTICES:
            raise RuntimeError(
                f"Boundary component {i} exceeds Google's {MAX_VERTICES}-vertex "
                "limit. Use a documented generalized boundary, not silent simplification."
            )

    for i in range(len(polygons)):
        for j in range(i + 1, len(polygons)):
            if polygons[i].intersection(polygons[j]).area > 1e-12:
                raise RuntimeError("Overlapping polygon components; stopping.")

    return props.get("CTYUA25NM", "Thurrock"), polygons


def polygon_latlngs(poly):
    ring = list(orient(poly, sign=1.0).exterior.coords)
    return [
        {"latitude": float(lat), "longitude": float(lon)}
        for lon, lat in ring
    ]


def google_count(api_key, polygon_coords, type_field, place_type):
    body = {
        "insights": ["INSIGHT_COUNT"],
        "filter": {
            "locationFilter": {
                "customArea": {
                    "polygon": {"coordinates": polygon_coords}
                }
            },
            "typeFilter": {type_field: [place_type]},
            "operatingStatus": ["OPERATING_STATUS_OPERATIONAL"],
        },
    }
    r = requests.post(
        GOOGLE_URL,
        headers={
            "X-Goog-Api-Key": api_key,
            "Content-Type": "application/json",
        },
        json=body,
        timeout=TIMEOUT_SECONDS,
    )
    if not r.ok:
        raise RuntimeError(
            f"Google API HTTP {r.status_code} for {place_type}/{type_field}: "
            f"{r.text[:1500]}"
        )
    data = r.json()
    if "count" not in data:
        raise RuntimeError(f"Response has no count for {place_type}/{type_field}: {data}")
    return int(data["count"])


def run_sum(api_key, polygons, type_field, place_type):
    return sum(
        google_count(api_key, polygon_latlngs(poly), type_field, place_type)
        for poly in polygons
    )


def main():
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        print("Missing GOOGLE_MAPS_API_KEY environment variable.", file=sys.stderr)
        return 2

    name, polygons = fetch_thurrock_polygons()
    print(f"Boundary: {name} ({BOUNDARY_CODE})")
    print(f"ONS polygon components: {len(polygons)}")
    print("Filter: operational places only; INSIGHT_COUNT only.")
    print("No individual Google place records are requested or saved.")
    print()

    tests = [
        ("Funeral home — broad type match", "includedTypes", "funeral_home"),
        ("Funeral home — primary type only", "includedPrimaryTypes", "funeral_home"),
        ("Cemetery — adjacent-service comparator", "includedTypes", "cemetery"),
    ]

    for label, type_field, place_type in tests:
        count = run_sum(api_key, polygons, type_field, place_type)
        print(f"{label}: {count}")

    print()
    print("Interpretation:")
    print("- The two funeral_home counts are alternative category definitions.")
    print("- Cemetery is an adjacent-service comparator, not a funeral-director count.")
    print("- Do not add these counts together: categories may overlap.")
    print("- Counts are aggregate Google-derived outputs; handle under your Google agreement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
