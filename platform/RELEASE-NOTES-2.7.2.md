# Everguide v2.7.2 — Overture ingestion recovery and diagnostics

## Why this release

The v2.7.1 Overture feed could leave import runs marked `running` after worker interruption. Celery uses late acknowledgements, so a task can be redelivered with the same task ID; the feed did not persist that ID on scheduled import runs and could create another run instead of resuming the existing one. It also emitted too little progress information to distinguish a slow remote Parquet scan from a stalled task.

## Changes

- Scheduled feed runs now store the Celery task ID and reuse the matching run on redelivery/retry.
- When recovering v2.7.1 data, the feed adopts the newest unfinished scheduled run for the same release rather than creating another.
- Adds logs around STAC lookup, ONS boundary retrieval, DuckDB setup/query submission, each fetched batch and completion/failure.
- Stores batch counts, last-batch timestamp and England record count in run metadata.
- Avoids duplicate Overture source observations when a GERS record is re-read as part of the same resumed run.
- Keeps `ST_X(geometry)` / `ST_Y(geometry)` for DuckDB's native GEOMETRY type and does not call `to_json()` on the taxonomy struct.

## Upgrade

1. Preserve your existing `.env` file. Keep `AUTO_APPROVE_PROVIDERS=false` while the Overture pipeline is being validated.
2. Extract this complete replacement ZIP over the existing project root. Do not replace `.env`.
3. Run `docker compose up -d --build`.
4. Check `docker compose logs --since=10m --timestamps worker` and `http://localhost:8000/api/v1/overture/imports`.

No migration is added. Do not run `docker compose down -v`, delete volumes, reset PostgreSQL, or manually edit Alembic history. The package does not include `.env`, PostgreSQL data or Redis data.

## Validation and limitations

- Python source and tests are syntax-compiled.
- ZIP contents and release metadata are checked.
- Focused pytest execution was blocked because this offline packaging environment does not have Celery and psycopg installed; no claim of passing runtime tests is made.
- No live Overture S3/GeoParquet scan, ONS request, Docker build or frontend production build was run here.
- This release improves recovery and observability; it does not claim that the live Overture query has completed successfully.
