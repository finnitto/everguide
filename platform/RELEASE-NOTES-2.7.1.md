# Everguide v2.7.1 — PostgreSQL migration startup fix

## Problem fixed

Everguide v2.7.0 used the Alembic revision identifier `0020_overture_production_pipeline` (33 characters). PostgreSQL's default `alembic_version.version_num` column is `VARCHAR(32)`, so Alembic could not write the new revision after running migration 0020. The API startup command consequently exited before Uvicorn started and Docker marked the API unhealthy.

## Change

- Changes the revision identifier to `0020_overture_feed` (18 characters).
- Preserves the migration's parent (`0019_identity_assessment_runs`), filename, upgrade operations, downgrade operations, tables and indexes.
- Keeps the migration additive; no database reset or manual SQL is needed.
- Updates application, web and Compose version metadata to 2.7.1.

## Upgrade

1. Back up PostgreSQL as usual.
2. Extract this full replacement ZIP over the existing project root. Preserve `.env`.
3. Run `docker compose up -d --build`.
4. Check `docker compose logs --tail=100 api` and `docker compose ps`.

Do not run `docker compose down -v`, delete volumes, or manually alter `alembic_version`. The failed migration shown in the v2.7.0 logs is a PostgreSQL transactional DDL failure; the migration transaction should have rolled back, leaving the database at revision `0019_identity_assessment_runs`. The corrected revision will be applied by the normal startup command. If startup still fails, stop and share the new API logs before attempting any manual database operation.

## Validation

- Migration revision length asserted to be at most 32 characters.
- Alembic migration graph checked for a single head and correct parent link.
- Python compile and focused Overture migration/API tests run where dependencies are available.
- No live production database was accessed during packaging.
