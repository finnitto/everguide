# Everguide Thurrock Geographic Discovery Pilot v2.6.3

Completed: 2026-11-13T08:43:03.574466+00:00
Boundary: Thurrock (E06000034), ONS December 2025 full-resolution local-authority boundary.

## Results

| source          |   candidate_records |   address_coverage_pct |   postcode_coverage_pct |   phone_coverage_pct |   website_coverage_pct |   postcode_review_count |   possible_duplicate_rows |
|:----------------|--------------------:|-----------------------:|------------------------:|---------------------:|-----------------------:|------------------------:|--------------------------:|
| OpenStreetMap   |                   0 |                      0 |                       0 |                    0 |                    0   |                       0 |                         0 |
| Overture Places |                  16 |                    100 |                     100 |                  100 |                   93.8 |                       2 |                         2 |

## OSM diagnostics

Per-layer counts are provided in osm_layer_diagnostics.csv, including read, geographic, named, keyword and exported counts.

## Candidate classification

candidate_class_summary.csv groups exported candidates into likely funeral director candidates and adjacent-service review records. These remain unverified.

## Quality controls

- Overture nested properties are serialized as valid JSON and flattened into address, postcode, phone and website columns.
- All records are retained; possible duplicates are flagged, not silently deleted.
- Postcode prefixes outside the common Thurrock RM15–RM20 and SS17 range are flagged for manual coordinate/postcode review. This is a screening heuristic, not definitive geocoding.
- OSM filtering normalizes underscores/hyphens and inspects both regular fields and parsed hstore tags.

## Interpretation

- Candidate records are not verified providers or branches.
- OSM and Overture remain separate source datasets.
- OSM-derived data remains subject to ODbL attribution/share-alike obligations.
- Overture upstream source licences must be checked per record using sources_json.
- No Google Places data is queried, stored or used.
- No Everguide production database is accessed or changed.

## Limitations

- Name/category rules can miss unusual records or include false positives.
- Postcode-area checks identify obvious anomalies but cannot validate a precise address.
- Review official provider websites and independent evidence before any provider/branch creation.
