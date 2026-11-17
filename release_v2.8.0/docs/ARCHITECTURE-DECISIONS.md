# Architecture decisions – initial baseline

| Area | Decision |
|---|---|
| Web | Next.js, React, TypeScript |
| API | Python, FastAPI |
| Database | PostgreSQL with PostGIS |
| ORM | SQLAlchemy |
| Migrations | Alembic |
| Background processing | Celery with Redis |
| Local orchestration | Docker Compose |
| Cloud direction | AWS-compatible boundaries; AWS implementation deferred |

## Constraints

1. Keep external observations separate from approved directory data.
2. Do not overwrite verified information with lower-confidence observations.
3. Keep provider publication and price publication independent.
4. Make discovery coverage system-operated and configurable; England is initial coverage.
5. Make jobs idempotent, observable and safely retryable.
6. Keep secrets and environment-specific data out of Git and release ZIP files.
7. Preserve persistent Docker volumes when application containers are rebuilt or stopped.
8. Keep business workflows independent of the local queue implementation where practical.
