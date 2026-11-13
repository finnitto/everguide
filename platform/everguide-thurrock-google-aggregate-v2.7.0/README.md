# Everguide Thurrock Google Aggregate Comparison v2.7.0

A separate, one-off research utility. It does **not** connect to Everguide, Docker, or its production database.

## What it does

- Downloads the official ONS December 2025 local-authority boundary for Thurrock (E06000034).
- Calls Google's **Places Aggregate API** `INSIGHT_COUNT` for the `funeral_home` Place Type.
- Runs two aggregate counts: operational only, and all three operating statuses.
- If the ONS boundary is a MultiPolygon, queries each exterior component separately and sums the aggregate counts.
- Compares the Google counts with the previously reconciled Overture pilot benchmark: 16 raw records, 12 likely local provider observations, and 8 likely distinct provider identities.
- Saves only aggregate counts, methodology, attribution and run metadata.

## Google setup

Your existing Places API key may not be authorised for Places Aggregate API yet.

1. In Google Cloud Console, enable **Places Aggregate API** (`areainsights.googleapis.com`) in the same project.
2. Under Google Maps Platform > Keys & Credentials, ensure the key is API-restricted to Places Aggregate API. If it is already restricted to Places API (New), add Places Aggregate API without removing the existing restriction.
3. Confirm billing is enabled.

Google's official setup guide: https://developers.google.com/maps/documentation/places-aggregate/get-api-key

## Run (Windows PowerShell)

Open PowerShell in the extracted folder:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
$env:GOOGLE_MAPS_API_KEY = "YOUR_API_KEY"
.un.ps1
```

The key exists only in the current PowerShell process environment. It is not saved to a file, ZIP, log, or output.

## Outputs

- `outputs/thurrock_aggregate_comparison.md`
- `outputs/thurrock_aggregate_comparison.csv`
- `outputs/run_metadata.json`

The script does not save the raw Google response, Place IDs, business names, addresses, coordinates, or API key. It makes four count requests if Thurrock has two polygon components (two status queries per component); otherwise two. Google billing applies. Check the current pricing before running.

## Important interpretation and terms notes

- Google `funeral_home` is a Place Type category. It is not a verified count of funeral-director businesses.
- Overture baseline counts were manually reconciled in the earlier pilot; they are screening estimates, not approved providers.
- Google attribution is included in the report.
- Google's Places Aggregate API policies require attribution when a count is used as a standalone metric. The current service-specific terms limit use of POI counts in derived Customer Values and specify a 30-day temporary caching limit for counts used for that purpose. This utility is configured for one-off research only; it does not create an Everguide directory or provider records. Review the agreement attached to your billing account before using the results for any other purpose.

Official documentation:
- Overview: https://developers.google.com/maps/documentation/places-aggregate/overview
- Request parameters: https://developers.google.com/maps/documentation/places-aggregate/request-parameters
- Policies: https://developers.google.com/maps/documentation/places-aggregate/policies
- Usage and billing: https://developers.google.com/maps/documentation/places-aggregate/usage-and-billing
- ONS boundary service: https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/Local_Authority_Districts_DEC_2025_Boundaries_UK_BFE/FeatureServer

No Everguide files are changed. No `.env`, local database, or user data are included.
