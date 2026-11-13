# Everguide v2.6.3 — Overture production verification and publication pipeline

## Included

- Durable Overture import runs and GERS-keyed candidate records.
- Source observations retain Overture release, contributor dataset/provider, contributor record IDs, licence metadata and retrieval dates.
- Celery-backed import and automatic evidence-processing pipeline.
- Official ONS Thurrock boundary (E06000034) point-in-polygon validation; fail closed if the official boundary cannot be retrieved or validated.
- Safe first-party HTTPS verification reusing Everguide's SSRF-aware website checker, robots.txt gate and transient page-body handling.
- Optional Brave Search discovery for candidates without a usable Overture website, when `BRAVE_SEARCH_API_KEY` is configured.
- Automatic provider and branch publication when every configured evidence gate passes.
- Existing provider/branch collision safeguards, with safe addition of separately verified branches under the same exact provider identity and website domain.
- API endpoints and admin UI for Overture import, processing, status, candidate outcomes and run history.
- Additive Alembic migration `0020_overture_production_pipeline`.

## Automatic approval requirements

Overture existence confidence is retained only as provenance. Publication requires an accepted contributor licence, candidate funeral-director classification, official point-in-Thurrock confirmation, independent first-party website access permitted by robots.txt, explicit funeral-sector evidence, a complete branch address, matching postcode and telephone, first-party confidence at or above the configured threshold (default 0.94), aligned business identity and no duplicate/provider/branch conflict.

Provider and branch creation, source observation acceptance and audit events are committed atomically. Existing provider or branch fields are not overwritten. Price publication remains separate.

## Import

Use the Overture Places section on `/admin` to select and import a CSV export, or run:

```powershell
python google_analysis/import_overture_to_everguide.py `
  --input google_analysis/overture_candidates.csv `
  --release 2026-10-15
```

The API accepts up to 5,000 rows per request; the UI batches larger files. Imported rows are automatically queued for processing.

## Known scope limitation

The live database, Celery and publication integration is implemented for Overture CSV exports. Direct downloading and spatial querying of the full Overture Places Parquet release is not yet implemented; this release must not be described as a continuously refreshed Overture feed. The optional search fallback requires `BRAVE_SEARCH_API_KEY`. Candidates without verified evidence remain in enrichment or exceptions; they are never published by default assumptions.

## Database and deployment safety

- New additive migration: `0020_overture_production_pipeline`.
- Back up PostgreSQL before deployment.
- Preserve `.env`, PostgreSQL data and Docker volumes.
- Extract the full ZIP over the project root and run `docker compose up -d --build`.
- Do not run `docker compose down -v`.
- No production database was accessed during package creation.

## Validation

- API test suite: 89 passed using SQLite and local Celery/Redis test doubles because the package environment did not contain `psycopg`, `celery` or `redis`.
- Overture approval and pipeline tests cover import provenance, automatic publication, boundary fail-closed behaviour, branch grouping and API import queuing.
- Python syntax compilation passed.
- CSV importer smoke test passed against a local HTTP test server; all 16 Thurrock rows were submitted and contributor JSON decoded.
- Docker Compose YAML parsing passed with PyYAML. Docker Compose configuration resolution, actual PostgreSQL/Alembic execution, Docker image builds and frontend production build were not run in this environment.
