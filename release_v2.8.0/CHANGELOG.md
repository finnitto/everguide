# Superseded Everguide release snapshot

This historical `release_v2.8.0/` package snapshot is **not a current release
candidate**. It predates Overture-first approval v2.0 and migrations 0021/0022.
Do not package, distribute or install it.

The current implementation and validation evidence are maintained under
`platform/` on branch `stage1-overture-identity-provenance`. See `platform/CHANGELOG.md`,
`platform/README.md` and `platform/RELEASE-MANIFEST.json`.

> Release history is maintained in this single file. Newest entries appear first.

## 2.8.0-rc.1 — Configurable local-authority geography framework (pre-release)

### Added
- Adds configurable geography modes: selected local authorities or England-wide coverage.
- Registers Thurrock (`E06000034`), Basildon (`E07000066`) and Havering (`E09000016`), with Thurrock-only retained as the safe default.
- Uses ONS December 2025 Local Authority District boundaries (`LAD25CD`, `LAD25NM`) consistently for local-authority and England-wide validation.
- Adds authority-aware boundary caching and invalidates the previous boundary cache schema.
- Filters scheduled Overture ingestion to the configured geography and records the verified scope on imported candidates.
- Keys scheduled import-run idempotency by geography selection.
- Rechecks configured geography during candidate processing, including manual imports, and fails closed for unsupported or unselected scopes.
- Exposes configured geography mode and authorities through Overture status.

### Changed
- Aligns API, web, Compose and release metadata to `2.8.0-rc.1`.
- Consolidates historical release notes into this single `CHANGELOG.md`; individual `RELEASE-NOTES-*.md` files are removed.

### Validation status
- Python compile/AST checks, Docker Compose YAML parsing, whitespace checks and 15 focused Overture approval tests were reported as passing for the geography patch.
- Full API suite, full feed/pipeline tests, frontend build and Docker image builds have not been completed for this release candidate.
- Default geography remains Thurrock only. Basildon/Havering and England-wide modes are not activated by this package.

## 2.7.9 — ONS boundary reliability, publication guard and worker hardening

- Improves ONS boundary retrieval, pagination, validation and persistent cache handling; boundary failures remain fail-closed.
- Strengthens the publication write-boundary guard so automatic publication cannot proceed when the configured approval gate is disabled.
- Corrects duplicate reason-code handling and adds regression coverage for boundary and publication safety.
- Runs the worker as a non-root user and verifies access to its persistent ONS cache volume.
- Stage 1 Overture-first source restrictions disable independent legacy discovery POST routes and legacy discovery Celery tasks while preserving read-only endpoints and existing records.
- No production candidate import, enrichment, approval or publication is implied by these source changes.

## 2.7.4 — First-party website classification and persistent ONS boundaries

- Separates attributed discovery URLs from verified provider-owned websites; excludes third-party directories, listing pages, news and company-record pages from first-party verification.
- Only matching first-party website evidence can populate the verified website field; search-result mismatches no longer become identity conflicts.
- Adds a persistent, integrity-checked ONS boundary cache shared across candidate batches and worker restarts.
- Adds bounded retries for incomplete downloads, timeouts and TLS transport errors without disabling certificate verification.
- Keeps publication fail-closed when official boundary verification is unavailable and changes application/Compose publication defaults to disabled.
- Adds a daily bounded enrichment retry sweep (initial assessment plus at most three retries after 2, 7 and 21 days); exclusions and exception-review records are not automatically retried.
- Adds audit-safe daily reconciliation for import runs stuck for over 24 hours: stale claims are recovered, pending work is resumed, and empty orphaned runs are closed without deleting history.
- No database migration; adds a dedicated `ons_boundary_cache` named volume.

## 2.7.3 — Overture candidate batch query fix

- Applies the scheduled import-run filter before SQLAlchemy `order_by()` and `limit()`, fixing candidate processing failures before the first batch.
- Adds a regression test for processing with a specific Overture import run ID.
- No schema migration or data deletion. Automatic publication remains governed by `AUTO_APPROVE_PROVIDERS`.

## 2.7.2 — Overture ingestion recovery and diagnostics

- Persists the scheduled Celery task ID on its import run and resumes the same run after late-ack redelivery or transient failure, rather than creating a new permanently-running run on each retry.
- Reuses the newest unfinished scheduled run for the release when recovering runs created by v2.7.1, which did not persist scheduled task IDs.
- Adds task lifecycle, DuckDB query-start, batch and completion logs; stores batch progress metadata and England record counts on the import run.
- Makes source-observation creation idempotent when a GERS record is encountered again during a resumed import run.
- Retains the native DuckDB GEOMETRY extraction (`ST_X(geometry)`, `ST_Y(geometry)`) and removes the unsafe JSON conversion of the taxonomy struct.
- No database migration. Existing PostgreSQL and Redis volumes are preserved; keep `AUTO_APPROVE_PROVIDERS=false` while validating the feed.
- Validation: Python syntax/compile and ZIP integrity checks; focused pytest could not be executed in this offline packaging environment because Celery and psycopg test dependencies are not installed. Live Overture S3/Parquet and ONS calls were not run.

## 2.7.1 - PostgreSQL Alembic revision-length fix

- Fixes API startup failure on PostgreSQL by shortening migration 0020's Alembic revision identifier to `0020_overture_feed` (18 characters), within the default `alembic_version.version_num VARCHAR(32)` limit.
- Keeps the migration filename and parent revision unchanged; the migration remains additive and creates the same Overture tables and indexes.
- No database reset, manual SQL, data deletion or Docker volume changes are required. A failed PostgreSQL migration transaction is rolled back and can be retried by the normal API startup command.
- Bumps application, web and Compose version metadata to 2.7.1.

## 2.7.0 - Scheduled England-wide Overture Places feed

- Adds daily Celery Beat polling of Overture's authoritative STAC catalogue and idempotent detection of new Places releases.
- Queries the latest cloud-hosted Places GeoParquet in place using pinned DuckDB, HTTPFS and spatial extensions; does not download the full global release.
- Scans a broad England bounding box and filters candidates against validated ONS December 2025 English county/unitary-authority geometry before ingestion.
- Identifies potential funeral-related records using Overture taxonomy and name signals, then upserts by GERS ID with contributor-level licence, record ID, release and retrieval provenance.
- Extends the evidence-led automatic approval rules to England-wide candidates rather than applying Thurrock-only postcode/boundary checks.
- Processes candidates in bounded, resumable Celery batches and prevents an endless retry loop for records awaiting additional evidence.
- Replaces the admin CSV-upload workflow with feed monitoring, last-check/release status and diagnostic check/retry controls. The old CSV API remains for compatibility only.
- No new database migration; uses the existing Overture tables introduced in migration 0020.
- Feed polling and ingestion require outbound access to Overture STAC/S3, ONS ArcGIS and DuckDB extension distribution.

## 2.6.3 - Overture production verification and publication pipeline

- Adds durable Overture import runs and GERS-keyed candidate records with contributor-level source/licence provenance, release metadata, retrieval timestamps and audit events.
- Adds Celery-backed Overture import and evidence-processing jobs, official ONS Thurrock polygon validation, safe first-party website verification and optional Brave Search website discovery.
- Automatically creates and publishes eligible providers and branch records in one transaction after service, licence, boundary, identity, address, telephone, confidence and collision checks pass.
- Supports multiple verified branches under the same provider identity without overwriting existing branch details; duplicate branch locations and ambiguous parent/provider identities remain exceptions.
- Adds Overture import, status, candidate and run-history API endpoints plus an admin CSV import and monitoring section.
- Adds migration `0020_overture_production_pipeline`; migration is additive and does not reset existing provider data.
- The CSV adapter is production-connected, but direct downloading/querying of the complete Overture Parquet release is not included yet.

## 2.6.2 - Overture evidence-led approval

- Added a deterministic Overture candidate assessment ruleset that treats Overture confidence as provenance, not proof.
- Added source-level licence checks, Thurrock postcode/boundary checks, independent first-party evidence requirements, and duplicate/branch exception handling.
- Added a reproducible assessment CLI for the supplied Thurrock Overture snapshot and regression tests.
- Explicitly documents that this release does not yet perform production DB ingestion/publication for Overture; no record is published from the offline CSV.

## 2.6.1 — Automation-first provider approval

- Implements deterministic automatic provider and first-branch creation/publication for high-confidence first-party provider website evidence.
- Requires explicit Schema.org `FuneralHome`, complete UK address and postcode, telephone, matching candidate/structured website domain, meaningful Companies House/provider name alignment, configured confidence threshold and no provider/branch collision.
- Routes incomplete, conflicting, ambiguous, low-confidence and duplicate cases to an administrator exception queue with machine-readable reasons.
- Adds accepted source observations and audit events for automatic provider, branch and candidate decisions.
- Defaults automatic approval to enabled; adds `AUTO_APPROVE_PROVIDERS` and `AUTO_APPROVAL_MIN_CONFIDENCE` controls.
- Exposes automatic approval settings and outcome counts in the discovery summary.
- Keeps the Thurrock Overture workbook as an exception-review aid; source-derived candidates are not auto-published while licence/permission remains unresolved.
- No new database migration.

## 2.6.0 — Thurrock provider verification pilot

- Adds provider-group and branch-candidate verification registers from the ONS-boundary Thurrock quality review.
- Adds a formatted Excel workbook with Provider Review, Branch Review, Evidence Log, Decision Log and Evidence Standards sheets.
- Adds reviewer guidance covering source permissions, provider activity, trading status, provider identity, operating branches, addresses, postcodes and contact details.
- Adds a completeness validator that blocks verified provider/branch outcomes when required evidence and parent-provider approval are missing.
- Preserves all source observations; duplicate and address conflicts remain review-only.
- Keeps the pilot offline and separate from the Everguide database and public directory. No provider/branch creation, merge, deletion or publication.
- No database schema migration.

## v2.5.1 — Conservative candidate-quality validation

- Adds reusable, deterministic classification for funeral-director candidates and adjacent services, with explicit adjacent-service signals taking precedence over broad source taxonomy labels.
- Adds UK telephone normalisation, postcode validation, same-branch duplicate fingerprints and suggested provider grouping while preserving separate branch records.
- Adds a local Thurrock Overture review tool using the official ONS December 2025 boundary (E06000034); outputs are review-only and do not modify the database.
- Flags postcode/coordinate conflicts, duplicate coordinate variance and same-provider multi-branch relationships for human review.
- Prevents fuzzy character similarity alone from inflating identity scores for unrelated Companies House and website names.
- Adds regression tests for adjacent-service classification, branch identity, duplicate detection, postcode conflicts and review-only behaviour.
- No database migration; no provider or branch records are automatically created, merged, deleted or published.

## 2.5.0 — Identity matching and evidence quality

- Identity triage now compares extracted website identity with the Companies House legal name; unrelated name matches are capped at 20%.
- Third-party directories and adjacent services are capped at 10% and remain discovery leads only.
- Stronger identity scores require same-domain declared website evidence plus name alignment; scores remain triage aids, not approval probabilities.
- Branch eligibility continues to require complete England address evidence on the same official domain as the declared business website; directory sources cannot establish branch identity.
- Duplicate branch proposals for the same company and normalized address are retained but secondary pending records are moved to `needs_more_evidence` with a link to the retained canonical proposal.
- Existing pending identity reviews are reassessed in place; accepted/rejected human decisions are not overwritten. Existing evidence is retained.
- No migration, provider creation, branch publication, Companies House import, or paid search is triggered by this release.

## v2.4.4 — Identity assessment resilience and conservative scoring

- Prevents promotional page descriptions from being stored as trading names; only concise candidate labels within the 240-character field limit are accepted, with original extracted data retained in evidence.
- Replaces relevance-driven confidence inflation with a conservative evidence-priority score capped at 0.75; known directories and adjacent sectors such as pet cremation and funeral-plan services are capped at 0.20. Scores are explicitly not probabilities or proof of provider identity.
- Excludes adjacent-sector signals from branch proposals. Existing pending branch proposals that fail the stricter reassessment are moved to `needs_more_evidence`; accepted/rejected human decisions are not changed.
- Isolates unexpected per-company processing errors with database savepoints, records an audit event and continues the batch. Runs finish as `completed_with_errors` when any company failed, rather than losing the remaining national assessment.
- Reprocesses pending identity/branch proposals idempotently; original website leads and extracted evidence remain intact. No provider or branch is created or published.
- No schema migration.

## v2.4.3 — Docker Desktop proxy-aware web builds

- Pass Docker Desktop's local HTTP proxy to the web dependency-install build stage by default, fixing environments where direct container egress is unavailable.
- Keep proxy values build-time-only; they are not copied into the runtime image or application environment.
- Add a BuildKit npm cache mount to reduce repeat downloads and improve recovery from interrupted builds.
- Allow other build environments to override `HTTP_PROXY` and `HTTPS_PROXY`; set both to empty values to disable the local proxy defaults.
- No database schema or data changes.
- Dependency installation still uses the existing pinned `package.json`; a lockfile has not yet been introduced.

# Changelog

## v2.4.2 — England-only resumable identity assessment

- Replaced synchronous identity queue preparation with a Celery-backed assessment run, processed in committed batches of 25 Companies House candidates.
- Added persistent run progress, counters, last committed candidate cursor, failure detail, and a resume endpoint. Re-running is idempotent and preserves human decisions.
- Restricted branch proposals to complete structured addresses with positive England postcode/country evidence. Scottish, Welsh, Northern Irish and ambiguous cross-border postcode areas are excluded; unconfirmed geography is skipped for review rather than guessed.
- Require the page carrying structured address evidence to be on the same domain as the website declared by that structured data, and exclude known directory domains.
- Numeric telephone values are omitted rather than rendered as corrupted numbers; textual phone values are preserved.
- Added `GET /api/v1/identity-review/runs` and `POST /api/v1/identity-review/runs/{run_id}/resume`.
- No provider or branch records are created or published. Existing source leads and evidence are not deleted.

## 2.4.1

- Tightened identity confidence so third-party directory results cannot receive high identity confidence from search relevance alone.
- Restricted branch proposals to complete UK addresses extracted from structured business data on non-directory domains.
- Preserved original website candidate rows and evidence; no provider or branch publication is performed.
- Kept telephone values as text when transferring extracted evidence into branch proposals.

## 2.4.0 — Website identity and branch review

- Adds company-level identity review records derived from existing website leads.
- Consolidates repeated leads by company and canonical domain for review while preserving every original lead and verification attempt.
- Adds review-only branch proposals only when a website extraction explicitly supplies a complete address and marks it complete. Registered-office data is never used to create a branch proposal.
- Adds idempotent review-queue preparation, summary/list endpoints, decision endpoints and audit events.
- Adds an admin panel for preparing and inspecting identity and branch review queues.
- No provider or branch records are created or published.
- Adds migration `0018_identity_branch_review`; existing Companies House candidates and website leads are preserved.

## 2.3.0 — Companies House-linked website discovery foundation

- Adds a separate website-discovery run and candidate model linked to each Companies House legal-entity candidate.
- Searches active, profile-enriched likely-funeral-director and uncertain candidates using the configured Brave Search API, in resumable batches of 25.
- Verifies up to two strongest HTTPS leads per company using existing public-host, robots.txt, response-size and no-redirect safeguards.
- Stores search provenance, result metadata, verification outcome, content digest and minimised extracted business identity signals; response page bodies are discarded and personal email fields are not retained.
- Pauses safely on search-provider or unexpected errors and supports resuming without re-searching completed candidates.
- Does not create or publish providers, branches, addresses, prices or public listings. Registered-office addresses are query context only.
- Requires SEARCH_PROVIDER=brave and BRAVE_SEARCH_API_KEY.
- Adds migration 0017_company_websites; existing candidate/profile data is preserved.

## 2.2.4

- Pause the whole enrichment batch immediately on HTTP 429, transient HTTP 5xx, authentication/permission errors, network errors or timeouts.
- Preserve the current candidate status and profile data when a transient service condition interrupts a run.
- Mark the run `interrupted`, record the reason and audit the processed count; a later run resumes only failed and unprocessed candidates.
- Pace successful profile requests at 1.1 seconds, including 404 responses, and remove blind per-candidate retries after a rate limit.
- Keep previous-company-name lookup out of the critical path and correct the admin UI wording.
- No schema migration, provider creation, branch creation or publication.

## 2.2.3 — Web container bind-address correction

- Explicitly sets `HOSTNAME=0.0.0.0` in the production web image. Next.js standalone server otherwise inherited Docker's injected container hostname and bound only to the container interface, causing the loopback Docker health check to fail.
- Keeps the existing loopback health check; no health-check masking.
- No database migration or data changes. Companies House enrichment remains paused until separately verified.

## 2.2.2 — Companies House enrichment recovery

- Removed the failing previous-company-names request from the critical profile lookup path; previous names remain optional and existing values are preserved.
- Added conservative request pacing and bounded HTTP 429 retries using Retry-After when provided, with exponential backoff otherwise.
- Failed and not-requested candidates remain eligible for a subsequent enrichment run; completed profiles are not fetched again.
- Added migration 0016 to mark an interrupted enrichment run as interrupted after a worker termination, without modifying candidate/profile data.
- No provider, branch, or publication records are created.

## 2.2.1

- Fix Candidate TypeScript definition for profile enrichment status.
- Fix ESLint flat-config handling for eslint-config-next 15.5.6 by treating exported configs as config objects rather than iterables.
- No database migration; preserves the v2.2.0 schema and imported Companies House data.

# Changelog

## 2.2.0 — Companies House profile enrichment

- Added resumable background enrichment of active Companies House candidates with official company profiles and previous company names.
- Added profile enrichment status, completion and failure metrics to admin.
- Kept legal-entity enrichment separate from provider creation, branch discovery and publication.
- Added migration `0015_ch_profiles`.

## 2.1.0 — Companies House classification and enrichment foundation

- Added explainable, conservative name-based candidate triage: likely funeral director, related service, directory/comparison, holding/group, and uncertain.
- Added classification confidence, reason and timestamp to each Companies House candidate.
- Added admin action and summary for bulk classification. Classification never creates or publishes provider records.
- Exposed API page size and unique candidate count on import history to make pagination completeness auditable.
- Confirmed the API supports up to 5,000 results per page; import records response pagination metadata and continues until total_results is reached.
- Added migration 0014_ch_classify.

## 2.0.0 — Companies House-led discovery foundation

- One-time PostgreSQL migration clears the early development provider directory, branches, Google Places observations, website discovery/verification records, correction proposals, source permissions and related discovery activity.
- Preserves the PostgreSQL database, schema, Alembic migration history, Redis infrastructure and application configuration.
- Records a system reset event in the audit table.
- Adds Companies House candidate and import-run tables.
- Adds a server-side Companies House Public Data API importer using advanced company search, active status and SIC 96030 by default.
- Imports company number, registered name, status, type, SIC codes, registered-office address and profile link as candidate evidence only.
- Does not create providers, branches or published directory entries from company-register records.
- Explicitly does not treat a registered office as a funeral-home branch.
- Replaces the legacy admin dashboard with a Companies House discovery console, import status and candidate list.
- Disables the legacy weekly regional discovery schedule.
- Adds `COMPANIES_HOUSE_API_KEY` and `COMPANIES_HOUSE_SIC_CODES` configuration.

### Important limitations

- SIC 96030 is a discovery filter, not proof that a company operates as a funeral director. It includes other funeral-related activities.
- Companies House does not cover sole traders and ordinary partnerships in the same way as registered companies. Independent discovery remains a required supplementary source.
- This release imports active UK company-register results for the configured SIC code; it does not yet verify England operating locations, official websites, branches or funeral-director status, and does not publish providers.
- The first import requires a Companies House API key. API credentials are stored server-side in `.env`.
