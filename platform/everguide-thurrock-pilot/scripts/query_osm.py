from __future__ import annotations
import datetime as dt
import json
import re
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
INPUTS, OUTPUTS = ROOT / "inputs", ROOT / "outputs"
INPUTS.mkdir(exist_ok=True)
OUTPUTS.mkdir(exist_ok=True)

ONS_QUERY = "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/Local_Authority_Districts_DEC_2025_Boundaries_UK_BFE/FeatureServer/0/query"
OVERPASS = "https://overpass-api.de/api/interpreter"
LAD_CODE = "E06000034"
HEADERS = {"User-Agent": "Everguide-Thurrock-OSM-Validation/2.6.4 (read-only research)"}

CORE_TAG_QUERIES = {
    "funeral_directors_shop": 'nwr["shop"="funeral_directors"]({bbox});',
    "funeral_hall": 'nwr["amenity"="funeral_hall"]({bbox});',
    "mortuary": 'nwr["amenity"="mortuary"]({bbox});',
    "place_of_mourning": 'nwr["amenity"="place_of_mourning"]({bbox});',
    "craft_funeral_director": 'nwr["craft"="funeral_director"]({bbox});',
    "name_funeral": 'nwr["name"~"funeral|undertaker|undertaking",i]({bbox});',
    "operator_funeral": 'nwr["operator"~"funeral|undertaker",i]({bbox});',
    "brand_funeral": 'nwr["brand"~"funeral|undertaker",i]({bbox});',
}
ADJACENT_TAG_QUERIES = {
    "crematorium": 'nwr["amenity"="crematorium"]({bbox});',
    "cemetery": 'nwr["landuse"="cemetery"]({bbox});',
}

def request_json(url, params=None, data=None, timeout=(20, 180)):
    last = None
    for attempt in range(3):
        try:
            response = requests.post(url, data=data, params=params, headers=HEADERS, timeout=timeout) if data is not None else requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last = exc
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Request failed after 3 attempts: {last}") from last

def load_boundary():
    path = INPUTS / "thurrock_boundary.geojson"
    if not path.exists():
        params = {
            "where": f"LAD25CD='{LAD_CODE}'",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
        }
        data = request_json(ONS_QUERY, params=params)
        if not data.get("features"):
            raise RuntimeError(f"ONS boundary query returned no feature: {data}")
        path.write_text(json.dumps({"type":"FeatureCollection","features":[data["features"][0]]}), encoding="utf-8")
    try:
        from shapely.geometry import shape
        feature = json.loads(path.read_text(encoding="utf-8"))["features"][0]
        return shape(feature["geometry"]), feature.get("properties", {})
    except Exception as exc:
        raise RuntimeError(f"Could not read Thurrock boundary GeoJSON: {exc}") from exc

def build_query(bbox):
    bbox_text = ",".join(f"{v:.7f}" for v in bbox)  # south,west,north,east
    fragments = []
    for key, template in CORE_TAG_QUERIES.items():
        fragments.append(f"/*{key}*/" + template.format(bbox=bbox_text))
    for key, template in ADJACENT_TAG_QUERIES.items():
        fragments.append(f"/*adjacent:{key}*/" + template.format(bbox=bbox_text))
    return "[out:json][timeout:90];(" + "".join(fragments) + ");out center tags;"

def element_point(element):
    if "lat" in element and "lon" in element:
        return float(element["lon"]), float(element["lat"])
    center = element.get("center") or {}
    if "lat" in center and "lon" in center:
        return float(center["lon"]), float(center["lat"])
    return None

def classify(tags):
    shop = tags.get("shop", "")
    amenity = tags.get("amenity", "")
    if shop == "funeral_directors" or amenity in {"funeral_hall", "mortuary", "place_of_mourning"} or tags.get("craft") == "funeral_director":
        return "core_funeral_tag"
    if amenity == "crematorium" or tags.get("landuse") == "cemetery":
        return "adjacent_service"
    text = " ".join([tags.get("name",""), tags.get("operator",""), tags.get("brand","")])
    if re.search(r"funeral|undertaker|undertaking", text, re.I):
        return "name_or_operator_match"
    return "other"

def main():
    from shapely.geometry import Point
    started = dt.datetime.now(dt.timezone.utc)
    boundary, props = load_boundary()
    minx, miny, maxx, maxy = boundary.bounds
    bbox = (miny, minx, maxy, maxx)
    query = build_query(bbox)
    print("Querying Overpass directly for Thurrock...")
    data = request_json(OVERPASS, data={"data": query})
    (OUTPUTS / "osm_overpass_raw.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    elements = data.get("elements", [])
    all_rows, core_rows, adjacent_rows = [], [], []
    for element in elements:
        point = element_point(element)
        if not point:
            continue
        pt = Point(point)
        if not boundary.covers(pt):
            continue
        tags = element.get("tags", {})
        cls = classify(tags)
        row = {
            "osm_type": element.get("type"),
            "osm_id": element.get("id"),
            "name": tags.get("name",""),
            "classification": cls,
            "latitude": point[1],
            "longitude": point[0],
            "address": " ".join(x for x in [
                tags.get("addr:housenumber",""), tags.get("addr:street",""),
                tags.get("addr:city",""), tags.get("addr:postcode","")
            ] if x),
            "postcode": tags.get("addr:postcode",""),
            "phone": tags.get("phone") or tags.get("contact:phone",""),
            "website": tags.get("website") or tags.get("contact:website",""),
            "shop": tags.get("shop",""),
            "amenity": tags.get("amenity",""),
            "craft": tags.get("craft",""),
            "operator": tags.get("operator",""),
            "brand": tags.get("brand",""),
            "all_tags_json": json.dumps(tags, ensure_ascii=False),
            "osm_url": f"https://www.openstreetmap.org/{element.get('type')}/{element.get('id')}",
            "licence": "OpenStreetMap contributors; ODbL 1.0",
        }
        all_rows.append(row)
        if cls in {"core_funeral_tag", "name_or_operator_match"}:
            core_rows.append(row)
        elif cls == "adjacent_service":
            adjacent_rows.append(row)

    import csv
    fields = ["osm_type","osm_id","name","classification","latitude","longitude","address","postcode","phone","website","shop","amenity","craft","operator","brand","all_tags_json","osm_url","licence"]
    def write_csv(filename, rows):
        with (OUTPUTS / filename).open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    write_csv("osm_overpass_all_matches.csv", all_rows)
    write_csv("osm_overpass_candidates.csv", core_rows)
    write_csv("osm_overpass_adjacent.csv", adjacent_rows)

    counts = {}
    for row in all_rows:
        key = row["classification"] + "|" + (row["shop"] or row["amenity"] or row["craft"] or "name_only")
        counts[key] = counts.get(key, 0) + 1
    with (OUTPUTS / "osm_overpass_summary.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["classification_and_tag","record_count"])
        for key, count in sorted(counts.items()):
            writer.writerow([key, count])

    metadata = {
        "pilot": "Everguide Thurrock OSM Direct-Query Validation v2.6.4",
        "started_utc": started.isoformat(),
        "completed_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "boundary_code": LAD_CODE,
        "boundary_name": props.get("LAD25NM") or "Thurrock",
        "bbox_south_west_north_east": bbox,
        "overpass_endpoint": OVERPASS,
        "overpass_osm_base_timestamp": (data.get("osm3s") or {}).get("timestamp_osm_base"),
        "elements_returned_by_api": len(elements),
        "elements_inside_boundary": len(all_rows),
        "core_candidates": len(core_rows),
        "adjacent_services": len(adjacent_rows),
        "production_database_accessed": False,
    }
    (OUTPUTS / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print("Overpass query complete.")
    print(json.dumps(metadata, indent=2))
    print("Outputs written to", OUTPUTS)

if __name__ == "__main__":
    main()
