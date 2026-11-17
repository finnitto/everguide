# Thurrock Overture candidate quality review

## Purpose

The tool reviews an Overture Places candidate CSV for service classification,
geographic consistency, possible same-branch duplicates and suggested
provider/branch relationships. It is a local analysis tool; it does not call
Google Places and does not read or write the Everguide database.

## Run

```powershell
python -m pip install -r google_analysis/requirements.txt
python google_analysis/review_overture_candidates.py `
  --input google_analysis/overture_candidates.csv `
  --out google_analysis/quality_review
```

The script retrieves the official ONS December 2025 Thurrock boundary
(`CTYUA25CD=E06000034`) and checks each coordinate against the polygon.
Alternatively, pass a previously downloaded matching GeoJSON with
`--boundary-file path\to\thurrock.geojson`.

If boundary retrieval fails, the script stops. `--allow-no-boundary` is an
explicit diagnostic override; all funeral-director candidates are held for
location review when the authoritative boundary is unavailable.

## Outputs

- `candidate_quality_review.csv`: row-level classification, location flags,
  branch duplicate fingerprint, suggested provider group and review decision.
- `summary.json`: counts and boundary/source metadata.
- `pilot_report.md`: human-readable summary and interpretation guardrails.

## Review logic

- Explicit cemetery, crematorium, celebrant, memorial/masonry, civic and
  directory signals override broad source taxonomy labels.
- A provider identity can have multiple branches. Different postcodes remain
  separate branch candidates.
- Same-branch fingerprints use normalised name, postcode and phone (or domain
  when phone is unavailable).
- International UK telephone formats are normalised for duplicate comparison.
- A postcode outside Thurrock's expected outward-code set is flagged. A point
  inside the ONS boundary with a non-Thurrock postcode is flagged as a conflict.
- Overture confidence is retained as source metadata, not treated as proof.
- No row is automatically merged, deleted, published or imported.

## Data licence

The CSV may contain Overture and upstream contributor content. The output
retains a source licence note for review. Confirm the applicable Overture and
upstream contributor terms before using or republishing any candidate data.
