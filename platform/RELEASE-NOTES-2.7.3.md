# Everguide v2.7.3 — Overture candidate batch query fix

## Fix

- Fixes scheduled Overture candidate processing by applying the import-run filter before SQLAlchemy `order_by()` and `limit()`. The previous ordering raised `Query.filter() being called on a Query which already has LIMIT or OFFSET applied`, causing imported releases to fail before processing the first candidate.
- Adds a regression test for the scheduled processing path where `run_id` is supplied.
- Keeps candidate processing bounded to 1–50 records per Celery task and preserves the existing GERS-keyed, idempotent ingestion behaviour.
- No database migration. No provider data, historical runs, PostgreSQL volumes or Redis data are deleted.
- Automatic publication remains controlled by `AUTO_APPROVE_PROVIDERS`; keep it set to `false` while validating the pipeline.

## Validation

- Python syntax compilation and focused pytest are run separately and reported with the package.
- Live Overture Parquet/ONS requests and Docker build are not run in the packaging environment.
