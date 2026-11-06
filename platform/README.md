# Everguide — local development

Current release: **0.3.1**. This is an early development build of the Everguide directory and provider-management platform.

## Start / update locally

From Git Bash in `C:/projects/everguide/platform`:

```bash
bash scripts/deploy-local.sh
```

The deployment script rebuilds the application images and starts the services. Existing PostgreSQL and Redis volumes are retained. Do not use `docker compose down -v` unless you intend to delete local data.

## Addresses
- Public website: http://localhost:3000
- Directory search: http://localhost:3000/search
- Admin preview: http://localhost:3000/admin
- API: http://localhost:8000
- API docs: http://localhost:8000/docs
- Readiness: http://localhost:8000/health/ready

## Core directory capabilities
- Create parent provider records and their first branch.
- List and search provider records by provider name, branch name, town/city and postcode.
- View dashboard counts and filter provider lifecycle status.
- Move providers to review or publish them from the local admin preview.
- Store source observations separately from approved provider and branch fields, including source name/type/URL, retrieval timestamp, confidence, observed data and review status.
- Record basic audit events for provider and observation actions.
- Search public directory records; only providers and branches with `published` status appear.

## Important limitations
This is a development milestone, not a production-ready directory. The admin interface has **no authentication or role-based access control** and must remain local; do not expose it to the internet. The public directory will be empty until records are entered and published. No Google Places integration, England-wide automated discovery, website enrichment, NAFD/SAIF/FCA checks, pricing extraction, map search, geocoding, automated publication rules or scheduled revalidation are implemented yet. The source-observation API is available, but a full evidence review interface is still pending.

Provider and pricing approval are intended to remain independent. This release only implements provider lifecycle statuses; pricing workflows arrive in a later milestone.

## Database safety
Release 0.3.1 adds an Alembic migration and does not require deleting existing database volumes. The API applies migrations at startup. Back up local data before any future destructive schema operation.

## API quick reference
- `GET /api/v1/dashboard`
- `GET /api/v1/providers?q=...&status=...`
- `POST /api/v1/providers`
- `GET /api/v1/providers/{id}`
- `PATCH /api/v1/providers/{id}`
- `POST /api/v1/providers/{id}/branches`
- `POST /api/v1/providers/{id}/status?status=published`
- `POST /api/v1/observations`
- `GET /api/v1/observations?review_status=pending`
- `PATCH /api/v1/observations/{id}`
- `GET /api/v1/directory/search?q=...`

All provider, branch and observation writes are validated by the API. See `/docs` for interactive API documentation.


## Automated provider discovery (0.3.1)

The admin dashboard includes a Google Places discovery control. Configure `GOOGLE_PLACES_API_KEY` in your local `.env` file and restart Docker Compose before launching a run. Enable the Places API (New) and billing in the associated Google Cloud project, and restrict the key to the Places API and appropriate usage.

A run performs one search at 40 regional England anchor locations (30 km location bias). Only Google Place ID references and Everguide's own search-anchor metadata are retained by default. Other Google Places business content is not stored pending a formal review of Google Maps Platform terms, attribution and retention rules. Existing provider records are not overwritten and new providers are not automatically published.

**Coverage limitation:** this first connector is a regional discovery pass, not a boundary-validated exhaustive census of every location in England. It is a technical integration milestone; a validated national coverage grid, paging/quotas, geographic coverage reporting and ongoing scheduling are subsequent work. Review Google Maps Platform terms, attribution, storage and retention requirements before production use.


### 0.3.1 diagnostic update
If Google Places rejects a discovery request, the run now records Google's structured error message and status. No database migration is required.
