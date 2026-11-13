# Everguide Thurrock OSM Direct-Query Validation v2.6.4

This is a separate, read-only validation tool. It does not change the Everguide application or production database.

## Purpose
The Geofabrik extract returned zero funeral keyword matches. This tool queries OpenStreetMap's Overpass API directly using:
- `shop=funeral_directors` (the established OSM funeral-director shop tag)
- related funeral facility tags (`amenity=funeral_hall`, `amenity=mortuary`, `amenity=place_of_mourning`)
- broad name/operator/brand text matches for funeral / undertaker
- adjacent-service tags for crematoria and cemeteries, kept separately

The query uses the Thurrock bounding box and then clips results against the official Thurrock boundary file from the previous pilot.

## Run
1. Extract this ZIP into a new folder, or into the existing `everguide-thurrock-pilot` folder.
2. Copy the existing `inputs/thurrock_boundary.geojson` into this package's `inputs` folder if it is not already present.
   - If absent, the script downloads the ONS Thurrock boundary.
3. Open PowerShell in this folder and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.un.ps1
```

## Outputs
- `outputs/osm_overpass_candidates.csv` — core likely funeral-director/service matches
- `outputs/osm_overpass_adjacent.csv` — crematoria/cemetery matches, not providers
- `outputs/osm_overpass_all_matches.csv` — all raw matching OSM elements with tags
- `outputs/osm_overpass_summary.csv` — counts by query class and tag combination
- `outputs/osm_overpass_raw.json` — original Overpass response for audit
- `outputs/run_metadata.json` — query timestamp, boundary and Overpass timestamp

## Interpretation and safeguards
- OSM tags are community-maintained and incomplete. A zero result does not prove no provider exists.
- A name match is a lead, not proof of a funeral-director business.
- Cemeteries and crematoria are kept in a separate adjacent-services file.
- The tool preserves OSM element IDs, tags and attribution.
- OSM data is available under ODbL 1.0; attribution is required and downstream database obligations need legal review before combining or redistributing.
- Respect the Overpass public service. The script makes one bounded query, retries only a small number of times, and stops on server errors.
