# Everguide

Current release: **0.4.1**. Early development build of the Everguide funeral director directory and provider-management platform.

## Stack

- Next.js / React / TypeScript web application
- FastAPI / Python API
- PostgreSQL with PostGIS
- Redis and Celery background worker
- Docker Compose local deployment

## Local deployment

1. Extract this release into your existing repository, replacing the files from the previous release. Keep your existing `.env` file and database volumes.
2. From Git Bash:

```bash
cd /c/projects/everguide/platform
bash scripts/deploy-local.sh
```

The API applies Alembic migrations at startup. Release 0.4.1 does not add a database migration and does not require deleting or recreating database volumes.

## Google Places discovery

Set `GOOGLE_PLACES_API_KEY` in the project-root `.env` file. Enable Places API (New) and billing in the associated Google Cloud project. Restart the API and worker after changing the key:

```bash
docker compose up -d --force-recreate api worker
```

The initial discovery connector uses 40 England regional anchors with 30 km location bias. This is an initial regional discovery pass, not a boundary-validated exhaustive census or a guarantee of complete England coverage.

Google Places observations retain the Google Place ID only. Google's Places policy exempts Place IDs from caching restrictions; other Places content remains subject to restrictions and attribution requirements. See [Google Maps Platform Places API policies](https://developers.google.com/maps/documentation/places/web-service/policies).

## Provider matching and review (0.4.1)

The matching engine compares source fields already stored in Everguide against provider and branch records. It can use business name, postcode, telephone number, website domain and town/city. Scores and reasons are indicative suggestions only; the system does not automatically merge, approve or publish records.

Google Place ID-only observations cannot be responsibly matched by name or address. They are explicitly labelled as needing enrichment rather than being guessed. The matching queue supports linking a reviewed observation to an existing provider and branch; the API validates that the branch belongs to the selected provider and records an audit event.

Duplicate detection reports exact duplicate Place IDs and duplicate fingerprints where enough independently sourced business fields exist. Discovery already deduplicates repeated Place IDs within an individual run.

## Development and security notes

- The admin interface is a local development preview. Authentication and role-based access control are not yet enabled; do not expose it to the public internet.
- Keep `.env` private. Never commit API keys or database credentials.
- Do not remove Docker volumes to troubleshoot application updates; doing so deletes local database data.


## v0.5.1 source permission workflow
See `docs/SOURCE-PERMISSIONS.md`. Sources are pending by default; only explicitly approved HTTPS websites are eligible for a limited homepage evidence check. SAIF/NAFD directory data is excluded without written permission. This feature does not enrich Place ID-only observations or publish provider records.


## Automatic website discovery (v0.6.0)
Configure `BRAVE_SEARCH_API_KEY` in `.env` to enable independent England regional website search. See `docs/WEBSITE-DISCOVERY.md`. Choose a search plan whose terms permit storing result metadata.


## v1.0.3
Includes interrupted verification batch recovery and a more diagnostic web health check. No database migration is required.


## v1.1.1 — Existing candidate backlog reassessment

Website verification batches now include previously checked candidates from earlier releases so the broader v1.1 extraction rules can reassess them. Each batch remains capped at 50. Previously published providers and possible-duplicate holds are not reprocessed. Candidates still lacking sufficient evidence are marked reassessed and audited to prevent repeated negative checks. No database migration is required.

## v1.1.0 — Broader automatic provider approval

This release broadens website identity extraction. It accepts Schema.org `FuneralHome` directly and accepts `LocalBusiness`, `Organization`, or `ProfessionalService` only when the page contains explicit funeral-sector language. A new provider may be published when identity is sufficiently clear even if branch address details are incomplete; a branch is created only when a complete UK street address, town and postcode are evidenced. Exact name, postcode and domain collisions remain held for duplicate review. Existing records are not overwritten. Pricing is not extracted or approved. No database migration is required.
