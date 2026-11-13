# Everguide v2.5.1 release notes

This is a full source release intended to be extracted directly over an existing
Everguide project directory.

## Included

- Full current Everguide application source and configuration templates.
- Conservative candidate-quality classification and review-only helpers.
- Thurrock Overture review script and the 16-row Overture candidate input export.
- Existing count-only Google Places Aggregate scripts.
- Updated documentation, changelog and release version.

## Not included

- `.env` and other secret-bearing environment files (only `.env.example` is included).
- PostgreSQL data directories, database dumps, SQLite databases and Docker volumes.
- Git metadata, Python bytecode/caches, pytest caches, Node dependencies and build outputs.
- Generated `google_analysis/quality_review` outputs.

## Database and deployment

- No new Alembic migration is introduced by v2.5.1.
- The existing API startup command still runs `alembic upgrade head`.
- Back up PostgreSQL before replacing files and restarting containers.
- Never run `docker compose down -v` when preserving the existing database volume.

## Validation performed while preparing this release

- 27 focused API tests passed (identity rules, identity assessment safety and candidate-quality tests).
- 2 Overture review-script tests passed.
- Python syntax checks passed for all changed Python modules and scripts.
- The review script completed a 16-row functional smoke test using a rectangular bounding-box fixture. That fixture is not an authoritative Thurrock boundary; the actual user run will fetch the ONS polygon before geographic conclusions are produced.
- The complete API test suite was not run here because this build environment lacks the Redis and Celery runtime dependencies; run the full suite in the project's Docker/API environment.
