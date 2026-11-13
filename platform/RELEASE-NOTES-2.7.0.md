# Everguide v2.7.0 — Scheduled England-wide Overture Places feed

## Included

- Daily Celery Beat check of the official Overture STAC catalogue.
- Automatic latest-release detection; unchanged releases are not rescanned.
- DuckDB 1.4.3 with HTTPFS and spatial extensions to query cloud-hosted Places GeoParquet in place.
- England bounding-box scan followed by official ONS county/unitary-authority point-in-polygon filtering.
- Funeral-related taxonomy/name candidate discovery and GERS-keyed upsert.
- Contributor-level source IDs, dataset/provider, licence, release and retrieval provenance.
- England-wide evidence assessment and automatic publication using first-party website evidence and existing safeguards.
- Bounded 20-record verification batches with continuation for unprocessed records without repeatedly cycling candidates awaiting more evidence.
- Admin feed monitoring replaces the routine CSV upload panel. Legacy CSV API retained for compatibility only.

## Normal operation

- Celery Beat checks STAC daily at 04:30 Europe/London by default.
- When a new release appears, Everguide queries only the Places feature type over an England bounding box, then filters exact candidate coordinates against ONS England polygons.
- New releases are ingested once and candidates are upserted by GERS ID.
- Overture confidence is retained only as place-existence provenance; it is never used as approval proof.
- First-party evidence, source licence, identity, address, phone, boundary and collision rules still gate publication.
- Admin users monitor releases, outcomes and exceptions. They do not need to upload a CSV.

## Configuration

```dotenv
OVERTURE_FEED_ENABLED=true
OVERTURE_FEED_DAILY_HOUR=4
OVERTURE_FEED_DAILY_MINUTE=30
OVERTURE_FEED_BATCH_SIZE=500
OVERTURE_AUTO_PROCESS=true
AUTO_APPROVE_PROVIDERS=true
AUTO_APPROVAL_MIN_CONFIDENCE=0.94
```

`BRAVE_SEARCH_API_KEY` remains optional but enables independent website discovery when Overture has no usable website.

## Database and deployment safety

- No new Alembic migration; existing migration `0020_overture_production_pipeline` is used.
- Back up PostgreSQL before deployment.
- Preserve `.env`, PostgreSQL data and Docker volumes.
- Extract the full ZIP over the project root and run `docker compose up -d --build`.
- Do not run `docker compose down -v`.
- The release package contains no `.env`, database, backup or volume files.

## Validation

- Full API test suite: 97 passed using SQLite and lightweight Celery/Redis test doubles. The environment did not contain the production database driver or Celery/Redis packages, and outbound package installation was unavailable.
- Overture feed tests cover STAC release validation, GERS/source provenance mapping and idempotent release checks.
- Python compilation and Docker Compose YAML parsing are run separately.
- Live DuckDB/S3 Parquet query, ONS service integration, actual PostgreSQL migration, Docker image builds and frontend production build were not run in this environment. Those runtime integrations must be confirmed after deployment before treating the scheduled feed as operational.

## Known limitations

- Discovery depends on Overture taxonomy/name signals and may miss a funeral director whose record has neither a relevant taxonomy nor name term.
- The broad bounding box is only a query optimisation; ONS geometry is required to confirm England scope.
- Absence from a later Overture release does not automatically close or delete a provider.
- The feed checks for new releases daily but scans England only when a new release is detected.
