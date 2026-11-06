# Everguide – Release 0.1.1

Patch release 0.1.1: resolves the Celery/Kombu/Redis Python dependency conflict and makes release ZIP contents extract directly into the repository root.

Initial local development foundation: Next.js/React/TypeScript, FastAPI, PostgreSQL/PostGIS, SQLAlchemy/Alembic, Redis/Celery and Docker Compose.

## First-time setup

From Git Bash in the repository root:

```bash
cp .env.example .env
./scripts/deploy-local.sh
```

Review `.env` first if you want to change local credentials or ports. The example credentials are for local development only.

## Local URLs

- Public website: http://localhost:3000
- Administration placeholder: http://localhost:3000/admin
- Backend API: http://localhost:8000
- API documentation: http://localhost:8000/docs
- API health: http://localhost:8000/health
- API readiness: http://localhost:8000/health/ready

## Useful commands

```bash
docker compose ps
docker compose logs -f
docker compose logs -f api
docker compose exec api pytest -q
docker compose up -d --build
./scripts/stop-local.sh
```

`stop-local.sh` preserves named database and Redis volumes. `docker compose down -v` deletes them and should only be used when intentionally resetting local data.

## Release packaging

Run `./scripts/package-release.sh`. The packager reads `VERSION`, excludes environment secrets, Git metadata, dependencies, caches, build output, local data, uploads and backups, and writes the ZIP under `releases/`.

## Current scope

This is a technical foundation, not yet the complete directory product. Provider/branch CRUD, authentication, Google Places discovery, enrichment, matching, pricing extraction, approval workflows and AWS deployment are planned for later releases.

Do not expose this development stack directly to the public internet.
