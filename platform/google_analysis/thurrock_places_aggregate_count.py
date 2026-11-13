#!/usr/bin/env python3
"""
One-shot Thurrock funeral-home aggregate count using Google Places Aggregate API.

- Fetches the ONS December 2025 full-resolution Thurrock boundary (E06000034).
- Sends count-only requests; it does not request names, addresses, Place IDs, or coordinates.
- Does not write Google responses to disk.
- Runs both a broad type match (includedTypes) and a stricter primary-type match
  (includedPrimaryTypes), so their definitions are explicit.

Install:
    python -m pip install requests shapely

PowerShell:
    $env:GOOGLE_MAPS_API_KEY = "YOUR_KEY"
    python .\\thurrock_places_aggregate_count.py

Do not commit your key or paste it into chat.
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
    response = requests.get(ONS_QUERY_URL, params=params, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    data = response.json()

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
        raise RuntimeError("ONS boundary geometry is invalid; stopping rather than altering it.")

    if isinstance(geom, Polygon):
        polygons = [geom]
    elif isinstance(geom, MultiPolygon):
        polygons = list(geom.geoms)
    else:
        raise RuntimeError(f"Unsupported ONS geometry type: {geom.geom_type}")

    # Aggregate API accepts one exterior ring per custom polygon and no holes.
    # For disjoint components, query each component separately and sum the counts.
    for i, poly in enumerate(polygons, start=1):
        if len(poly.interiors):
            raise RuntimeError(
                f"Boundary component {i} contains interior rings (holes). "
                "Google's custom polygon supports one exterior ring only; "
                "do not silently fill holes."
            )
        if poly.area <= 0:
            raise RuntimeError(f"Boundary component {i} has zero area.")

    # Disjoint components should not overlap; avoid double-counting if they do.
    for i in range(len(polygons)):
        for j in range(i + 1, len(polygons)):
            if polygons[i].intersection(polygons[j]).area > 1e-12:
                raise RuntimeError("ONS multipart components overlap; stopping to avoid double-counting.")

    return props.get("CTYUA25NM", "Thurrock"), polygons


def polygon_latlngs(poly):
    # Google requires a closed, counter-clockwise exterior ring.
    ccw = orient(poly, sign=1.0)
    ring = list(ccw.exterior.coords)
    if len(ring) > MAX_VERTICES:
        raise RuntimeError(
            f"Boundary ring has {len(ring)} vertices; Google allows at most "
            f"{MAX_VERTICES}. Use a matching, documented generalized boundary "
            "rather than silently simplifying this geometry."
        )

    # Shapely coordinates are (longitude, latitude); Google expects named fields.
    return [
        {"latitude": float(lat), "longitude": float(lon)}
        for lon, lat in ring
    ]


def google_count(api_key, polygon_coords, type_field):
    body = {
        "insights": ["INSIGHT_COUNT"],
        "filter": {
            "locationFilter": {
                "customArea": {
                    "polygon": {
                        "coordinates": polygon_coords
                    }
                }
            },
            "typeFilter": {
                type_field: ["funeral_home"]
            },
            "operatingStatus": ["OPERATING_STATUS_OPERATIONAL"],
        },
    }
    response = requests.post(
        GOOGLE_URL,
        headers={
            "X-Goog-Api-Key": api_key,
            "Content-Type": "application/json",
        },
        json=body,
        timeout=TIMEOUT_SECONDS,
    )
    if not response.ok:
        # Do not print request headers or the API key.
        raise RuntimeError(
            f"Google Aggregate API returned HTTP {response.status_code}: "
            f"{response.text[:1500]}"
        )
    result = response.json()
    if "count" not in result:
        raise RuntimeError(f"Google response did not contain a count: {result}")
    return int(result["count"])


def main():
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        print("Missing GOOGLE_MAPS_API_KEY environment variable.", file=sys.stderr)
        return 2

    boundary_name, polygons = fetch_thurrock_polygons()
    print(f"Boundary: {boundary_name} ({BOUNDARY_CODE})")
    print(f"ONS polygon components: {len(polygons)}")
    print("Google filter: operational places only; count insight only.")
    print("No individual Google place records are requested or saved.")

    # Broad: funeral_home may be either a primary or secondary place type.
    broad_total = 0
    # Strict: funeral_home must be the primary place type.
    primary_total = 0

    for idx, poly in enumerate(polygons, start=1):
        coords = polygon_latlngs(poly)
        broad_total += google_count(api_key, coords, "includedTypes")
        primary_total += google_count(api_key, coords, "includedPrimaryTypes")

    print()
    print(f"Broad funeral_home type count (includedTypes): {broad_total}")
    print(f"Primary funeral_home type count (includedPrimaryTypes): {primary_total}")
    print()
    print("These are different category definitions, not verified provider counts.")
    print("Do not persist the raw Google counts beyond the applicable terms.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
