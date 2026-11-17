# Overture discovery and automatic publication

## Development and end-to-end validation mode

Scheduled Overture polling, enrichment retries and stale-run recovery are disabled by default using `OVERTURE_SCHEDULED_TASKS_ENABLED=false`. This switch controls Celery Beat registration only. It does not disable the on-demand API actions for an immediate feed check, importing a controlled dataset, or processing candidates. `OVERTURE_FEED_ENABLED` controls whether the feed integration is available; `OVERTURE_AUTO_PROCESS` controls whether a completed import automatically queues candidate processing. Keep `AUTO_APPROVE_PROVIDERS=false` during ordinary development. For controlled approval tests, enable it only against test data after the approval safeguards are verified.

## Scheduled England-wide feed (v2.7.4)

Everguide's normal Overture workflow is fully scheduled; an administrator does not upload or import a CSV. Celery Beat checks the authoritative Overture STAC catalogue daily at the configured Europe/London time. It compares the latest release with previous scheduled feed runs and only scans Places when a new release is available.

The worker queries the cloud-hosted Overture Places GeoParquet directly with DuckDB HTTPFS and the spatial extension. It does not download the entire global dataset. A broad England bounding box reduces cloud scanning; every candidate point is then tested against ONS December 2025 English county/unitary-authority polygons. If the ONS geometry cannot be fetched or validated, ingestion fails closed.

Discovery uses Overture taxonomy and name signals (funeral, undertaker, undertaking, mortuary, cremation and burial terms) to find potential candidates. It is a candidate-discovery filter, not proof that the business is a funeral director. The existing deterministic service classifier excludes adjacent categories such as memorial masons, celebrants and cemeteries. GERS IDs are the upsert key, allowing new releases to refresh the same candidate without creating duplicate candidate entities.

Each observation retains the Overture release, GERS ID, contributor provider/dataset, contributor record IDs, source licence, Overture confidence and retrieval timestamp. Missing or unrecognised contributor licence values are not silently accepted; they block automatic publication and create an exception. The Overture place-existence confidence is provenance only, never field confidence or approval proof.

## Evidence and publication

After import, Celery processes candidates in bounded batches. It checks the candidate's HTTPS website using Everguide's SSRF-aware verifier, validates public HTTPS destinations, checks robots.txt permission and discards page bodies after extracting limited identity evidence. If no usable website is supplied by Overture, the configured Brave Search provider may discover a lead.

Automatic publication requires all configured gates: confirmed funeral-director service on first-party evidence, permitted website access, aligned business identity and domain, complete UK branch address, matching postcode and telephone, first-party confidence at or above the configured threshold (default 0.94), accepted contributor licence metadata, official England boundary confirmation and no unresolved duplicate/provider/branch conflict. Provider and branch creation, accepted observations and audit events are committed atomically. Existing verified fields are not overwritten or merged. Directory and price publication remain separate.

Candidates that lack evidence remain in automated enrichment; identity, branch, source-rights or location conflicts enter the exception queue; adjacent services are excluded. Manual approval is not the normal route.

## Admin monitoring

The Overture admin panel shows feed enablement and schedule, last feed check, latest release, candidate/outcome counts, automatically published providers, ingestion run history and unresolved candidates. It has a diagnostic **Check for new Overture release** action and a **Retry awaiting enrichment** action. It does not offer a routine CSV upload.

## Configuration

```dotenv
OVERTURE_FEED_ENABLED=true
OVERTURE_SCHEDULED_TASKS_ENABLED=false
OVERTURE_FEED_DAILY_HOUR=4
OVERTURE_FEED_DAILY_MINUTE=30
OVERTURE_FEED_BATCH_SIZE=500
OVERTURE_AUTO_PROCESS=true
AUTO_APPROVE_PROVIDERS=false
AUTO_APPROVAL_MIN_CONFIDENCE=0.94
ONS_BOUNDARY_CACHE_TTL_HOURS=720
BRAVE_SEARCH_API_KEY=
```

Automatic publication is disabled by default; keep `AUTO_APPROVE_PROVIDERS=false` during discovery validation. Only enable it explicitly after the evidence and exception outcomes have been validated. ONS geometry is cached for 30 days in the `ons_boundary_cache` Docker volume; the cache stores source and retrieval metadata and rejects expired or invalid entries.

When scheduled automation is explicitly authorised, the scheduled feed requires outbound HTTPS access to `stac.overturemaps.org`, Overture's public S3 Parquet bucket, the ONS ArcGIS boundary service and, when configured, the search provider. DuckDB downloads its `httpfs` and `spatial` extensions on first query.

## API

- `GET /api/v1/overture/status` — feed schedule, last check, candidate counts and latest run.
- `POST /api/v1/overture/feed/check` — queue an immediate STAC release check for diagnostics.
- `GET /api/v1/overture/imports` — scheduled feed run history (legacy CSV runs remain identifiable).
- `GET /api/v1/overture/candidates` — candidate decisions and evidence summaries.
- `POST /api/v1/overture/process` — retry awaiting enrichment candidates.
- `POST /api/v1/overture/imports` — legacy CSV compatibility endpoint; not part of the normal admin workflow.

## Scope and limitations

The Overture feed scans potential funeral-related Places in England when invoked manually or by an authorised schedule. The bounding box is only a query optimisation; official ONS point-in-polygon validation is the final England-scope check. Records without a point or outside England are not imported. The taxonomy/name filter may not discover a funeral director whose Overture record has neither relevant taxonomy nor relevant name terms; Companies House and first-party website discovery remain complementary sources.

The feed ingests a new Overture release once and upserts candidates by GERS ID. It does not infer that a provider has closed solely because a record is absent from a later release, and it does not delete provider/branch records. Existing verified data is retained. Future release-delta/changelog integration can improve update efficiency, but full England candidate scans occur only when Overture publishes a new release.

## Upgrade and deployment

No new Alembic migration is required beyond `0020_overture_feed`; this release adds application tasks, configuration and the pinned DuckDB dependency. Back up PostgreSQL, preserve `.env` and Docker volumes, extract the full ZIP over the project root and run `docker compose up -d --build`. Do not run `docker compose down -v`.


### v2.7.4 website and boundary safeguards

Overture-supplied URLs are discovery leads only. Third-party directory/listing/news/company-record URLs are not accepted as provider-owned websites. The first-party site is discovered independently and must corroborate the candidate identity, postcode and telephone. Original lead provenance remains stored separately. Official ONS geometry is cached on the `ons_boundary_cache` Docker volume with a retrieval timestamp and SHA-256 integrity check. Expired or invalid cache data is rejected; network failures are retried with verified TLS and publication remains blocked unless boundary verification succeeds. Automatic publication defaults to disabled.

Only `awaiting_enrichment` records receive automatic retries, with an initial assessment and no more than three further attempts at 2, 7 and 21 days. Excluded records and unresolved identity/branch exceptions are not automatically retried. Retry decisions and limits are audited.

Import runs older than 24 hours are checked daily. Stale candidate claims are released, outstanding unprocessed work is resumed, and runs with no linked candidates are closed as failed with an audit event. Runs with all candidates assessed are marked completed. No run history or candidate evidence is deleted.
