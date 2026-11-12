# Everguide v2.4.0

Companies House-led discovery foundation for the Everguide funeral director directory.

## Important deployment behaviour

On first startup after v2.0.0 is deployed, Alembic migration `0013_ch_reset` clears the early-development directory and its operational discovery data. It clears providers, branches, source observations, Google Places discovery observations, website discovery and verification data, correction proposals, source permission records and related development audit events. It retains the PostgreSQL database and schema, Alembic migration history, Redis infrastructure and application configuration. A new system audit event records the reset.

This migration is intentionally destructive to the old development directory and is not reversible. Do not deploy it against production customer data.

## Companies House setup

1. Register an application and obtain an API key from the [Companies House Developer Hub](https://developer.company-information.service.gov.uk/).
2. Add these settings to the existing `.env` file:

```dotenv
COMPANIES_HOUSE_API_KEY=your_api_key_here
COMPANIES_HOUSE_SIC_CODES=96030
```

3. Extract the release over the existing project, preserving `.env`.
4. Run:

```bash
docker compose up -d --build
```

5. Open `http://localhost:3000/admin` and select **Import active Companies House companies**.

The importer uses the Companies House Advanced Company Search API, requesting active companies with the configured SIC codes. It paginates through the result set, upserts candidates by company number, and records each import run. API credentials are sent only from the backend using HTTP Basic authentication.

## What the importer does not do

Companies House records are legal-entity candidates, not verified funeral directors. SIC 96030 includes funeral and related activities, including activities other than funeral directing. A registered office is not assumed to be a funeral home. This release stores candidates separately and does not create or publish providers or branches.

The next stage must classify candidates, establish whether the company actually operates funeral-director services in England, discover trading identities and genuine operating branches, and supplement the register with independent discovery for sole traders and ordinary partnerships.

## Local stack

- Next.js / React admin console
- FastAPI API
- PostgreSQL + PostGIS
- Redis + Celery worker
- Companies House Public Data API

The admin console is a development interface. Authentication and role-based access control are not enabled; do not expose it to the public internet.


## v2.1 candidate triage
The Companies House importer remains the legal-entity discovery layer. After import, an administrator can run **Classify active candidates**. The deterministic name-based rules provide an explainable first-pass triage only; they do not verify the company's operating activity, create providers, create branches, or publish listings. Website and company-profile enrichment is the next stage.

The import history exposes the API-reported total, response page size, pages fetched and distinct candidate count. The importer uses `start_index` and continues until the API-reported total has been consumed.


## v2.2 company profile enrichment

After importing and classifying Companies House candidates, use **Enrich Companies House profiles** in the admin console. This background job fetches each active candidate's official company profile and stores legal-entity evidence. Previous-name history is not requested because the endpoint returned server errors during the initial integration test. It does not create providers, branches or publication records. Requests are paced at 1.1 seconds between successful requests. If Companies House returns HTTP 429, a temporary HTTP 5xx, an authentication/permission error, or a network timeout, the batch is marked interrupted and stops without changing the current candidate. A later enrichment run retries only candidates still marked failed or not requested; completed profiles are not fetched again.

### v2.4.2 identity assessment

Identity assessment is queued to the Celery worker and processed in batches of 25 companies. Progress is persisted in `identity_assessment_runs`; a failed/interrupted run can be resumed from its last committed company using `POST /api/v1/identity-review/runs/{run_id}/resume`. Inspect progress with `GET /api/v1/identity-review/runs`.

Branch proposals require complete structured address evidence, a positive England postcode/country assessment, and a source page on the same domain as the business website declared in its structured data. Devolved-nation and ambiguous postcode areas are excluded. Numeric telephone values are omitted because they may have lost formatting or precision. Assessment creates review-only proposals; it does not create or publish providers or branches.


### Docker Desktop proxy for web builds (v2.4.3)

The web image passes Docker Desktop's `http.docker.internal:3128` proxy to npm during the dependency-install stage. This is a build-time setting only. For another environment, override `HTTP_PROXY` and `HTTPS_PROXY` in the shell or `.env`; set both to empty values to disable the local defaults. The npm cache uses a BuildKit cache mount.
