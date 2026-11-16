# Everguide v2.7.4

Automation-first discovery, verification and publication foundation for the Everguide funeral director directory.

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

### v2.5.0 identity assessment notes
Identity confidence is a review-priority score, not a probability or approval. The assessment now requires alignment between the Companies House name and website-extracted identity for scores above the low-confidence band. Third-party directories and adjacent services are limited to 10%. Directory pages remain useful discovery leads but cannot independently establish provider identity or a branch. Duplicate pending branch proposals for the same company/address are retained as evidence and marked `needs_more_evidence` with a canonical proposal reference. Human decisions are not overwritten. No migration is required.


## v2.5.1 — Conservative candidate-quality validation

- Adds reusable, deterministic service classification for funeral-director candidates, cemeteries, crematoria, celebrants, memorial/masonry businesses, civic services and directories.
- Explicit adjacent-service evidence takes precedence over broad Overture taxonomy labels such as `family_service` and `funeral_service`.
- Adds UK telephone normalisation, postcode checks, same-branch duplicate fingerprints and suggested provider grouping while preserving separate branch locations.
- Adds a Thurrock Overture review script using the official ONS December 2025 boundary `E06000034`. It writes a CSV, JSON summary and Markdown report; it does not access the Everguide database.
- Adds conservative checks for postcode/coordinate conflicts, duplicate coordinate variance and multiple branches sharing a provider identity.
- Tightens Companies House website identity assessment: fuzzy character similarity cannot raise an unrelated company-name match unless at least one meaningful token overlaps.
- Keeps all decisions review-only. No provider/branch records are created, merged, deleted or published.
- No database schema migration.

### Re-run the Thurrock Overture candidate review

The pilot CSV is included at `google_analysis/overture_candidates.csv`. From the project root:

```powershell
python -m pip install -r google_analysis/requirements.txt
python google_analysis/review_overture_candidates.py `
  --input google_analysis/overture_candidates.csv `
  --out google_analysis/quality_review
```

The script downloads the official ONS Thurrock boundary. If the boundary cannot be retrieved, it stops unless `--allow-no-boundary` is explicitly supplied. Without a verified boundary, all funeral-director candidates remain on hold for location review.

The review outputs are local analysis files only. They are not imported into Everguide automatically. Check Overture and upstream source licence terms before reusing candidate data.


## Updating an existing local installation to v2.5.1

This release ZIP is structured with project files at its root so it can be
extracted directly into the existing Everguide project directory.

1. Back up the PostgreSQL database before updating. Do not delete Docker volumes.
2. Stop the stack if you prefer a quiet file replacement:
   `docker compose stop`
3. Extract the ZIP into the existing project root and allow files to overwrite.
   The release archive does not contain `.env`, PostgreSQL data directories,
   Docker volumes, or local database files, so these are not replaced.
4. Rebuild and start:
   `docker compose up -d --build`
5. Check:
   `docker compose ps`
   `docker compose logs --tail=100 api`

This patch adds no Alembic migration. The API container still runs the project's
existing `alembic upgrade head` startup command. Confirm your current migration
revision and retain a database backup before restarting, especially if the
database has not previously been upgraded through migration `0019`.

Never run `docker compose down -v` for this update; `-v` removes named volumes.


## v2.6.1 — Automation-first provider approval

Everguide's normal operating model is automation-first. The system automatically creates and publishes a provider and its first branch when first-party website evidence passes every configured high-confidence rule. Administrators handle exceptions; they do not approve every ordinary provider manually.

The first implemented ruleset (`provider-auto-approval-v1.1`) requires explicit Schema.org `FuneralHome` structured data, explicit funeral-sector page context, a complete UK street address/locality/postcode, a telephone number, a matching candidate/structured-data website domain, meaningful name alignment with the linked Companies House candidate, confidence at or above the configured threshold, and no existing provider/branch name, domain, postcode or telephone collision. Generic `LocalBusiness` and other structured-data types do not qualify for automatic publication. Existing records are never overwritten, merged or deleted by this path.

Eligible candidates create a published provider and branch, an accepted source observation and audit events. The source page body is discarded; selected structured facts and a content digest are retained. Incomplete, conflicting, low-confidence, ambiguous or duplicate candidates enter the administrator exception queue with explicit reasons. Candidates without sufficient identity evidence are marked not eligible.

### Automatic approval configuration (v2.7.4 safety default)

Automatic publication is disabled by default while discovery and evidence collection continue:

```dotenv
AUTO_APPROVE_PROVIDERS=false
AUTO_APPROVAL_MIN_CONFIDENCE=0.94
```

Only explicitly set `AUTO_APPROVE_PROVIDERS=true` after validating the evidence and exception outcomes. Keep the setting false during the initial England-wide discovery assessment. The threshold is configurable; lowering it reduces the precision guardrail and should only follow measured validation. API, worker and scheduler services share these settings.

See `docs/AUTOMATIC-PROVIDER-APPROVAL.md` for the full rules, exception reasons and source-permission safeguards. Directory approval does not imply NAFD/SAIF membership, FCA regulatory status or price approval.

### Thurrock Overture exception pilot

The Thurrock workbook remains an offline exception-review tool for the 16 Overture-derived observations. It does not write to the production database. These source-derived records are not eligible for automatic publication while the upstream licence and source-level permitted use remain unresolved. Use it to resolve the licence question, postcode/address conflicts and branch ambiguity—not as a manual approval queue for all Everguide providers. See `google_analysis/verification_pilot/README.md`.

No new Alembic migration is added in v2.6.1.

## Updating an existing installation to v2.6.1

Follow the same safe overlay process described above for v2.5.1: back up PostgreSQL, extract the full ZIP into the existing project root, preserve `.env` and Docker volumes, then run `docker compose up -d --build`. This release adds no database migration. Do not run `docker compose down -v`.


## Overture scheduled discovery and automatic publication (v2.7.4)

Everguide checks the official Overture STAC catalogue daily and discovers new Places releases. When a new release appears, the worker queries Overture's cloud-hosted Places GeoParquet directly using a broad England bounding box, then filters candidate points against the official ONS England county/unitary-authority boundaries. It does not download the full global Places dataset and does not require an administrator to upload a CSV.

Potential funeral-director records are identified using Overture taxonomy and name signals, then upserted by GERS ID with contributor-level source IDs, licence metadata, release/version and retrieval timestamps. The existing first-party evidence pipeline independently checks official websites, robots.txt permission, funeral-director service evidence, identity, complete branch address, postcode, telephone, source licence and provider/branch collisions. Overture existence confidence remains provenance only. When automatic publication is explicitly enabled, qualifying providers and branches can be published; incomplete records remain in enrichment and unresolved conflicts go to the exception queue. Directory and price publication remain separate. Third-party listing URLs are retained as discovery leads and never accepted as provider-owned websites.

The admin Overture panel is for monitoring feed status, release history, candidate outcomes and exceptions. **No routine CSV import is required.** A one-off **Check for new Overture release** action is available for diagnostics; the scheduled daily check remains the normal operating path.

Default configuration:

```dotenv
OVERTURE_FEED_ENABLED=true
OVERTURE_FEED_DAILY_HOUR=4
OVERTURE_FEED_DAILY_MINUTE=30
OVERTURE_FEED_BATCH_SIZE=500
OVERTURE_AUTO_PROCESS=true
AUTO_APPROVE_PROVIDERS=false
AUTO_APPROVAL_MIN_CONFIDENCE=0.94
ONS_BOUNDARY_CACHE_TTL_HOURS=720
```

Automatic publication is disabled by default. Keep it disabled while validating candidate outcomes; the existing `.env` value is preserved during overlay updates. Validated ONS geometry is stored in the dedicated `ons_boundary_cache` Docker volume and reused across batches and worker restarts. Do not remove existing volumes or use `docker compose down -v`.

DuckDB and its HTTPFS/spatial extensions are used by the worker to query public Parquet data in place. The first feed check after deployment may take longer while extensions are installed and the England area is queried. A new Overture release is ingested once; unchanged daily catalogue checks do not rescan the dataset.

See [docs/OVERTURE-AUTOMATIC-APPROVAL.md](docs/OVERTURE-AUTOMATIC-APPROVAL.md) for the feed design, API and safeguards. The API retains the old CSV import endpoint for compatibility, but it is no longer exposed as a normal admin workflow.

