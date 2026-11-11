# Changelog

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


## 2.1.0 — Companies House classification and enrichment foundation
- Added explainable, conservative name-based candidate triage: likely funeral director, related service, directory/comparison, holding/group, and uncertain.
- Added classification confidence, reason and timestamp to each Companies House candidate.
- Added admin action and summary for bulk classification. Classification never creates or publishes provider records.
- Exposed API page size and unique candidate count on import history to make pagination completeness auditable.
- Confirmed the API supports up to 5,000 results per page; import records response pagination metadata and continues until total_results is reached.
- Added migration 0014_ch_classify.


## 2.2.0 — Companies House profile enrichment

- Added resumable background enrichment of active Companies House candidates with official company profiles and previous company names.
- Added profile enrichment status, completion and failure metrics to admin.
- Kept legal-entity enrichment separate from provider creation, branch discovery and publication.
- Added migration `0015_ch_profiles`.

## 2.3.0 — Companies House-linked website discovery foundation
- Adds a separate website-discovery run and candidate model linked to each Companies House legal-entity candidate.
- Searches active, profile-enriched likely-funeral-director and uncertain candidates using the configured Brave Search API, in resumable batches of 25.
- Verifies up to two strongest HTTPS leads per company using existing public-host, robots.txt, response-size and no-redirect safeguards.
- Stores search provenance, result metadata, verification outcome, content digest and minimised extracted business identity signals; response page bodies are discarded and personal email fields are not retained.
- Pauses safely on search-provider or unexpected errors and supports resuming without re-searching completed candidates.
- Does not create or publish providers, branches, addresses, prices or public listings. Registered-office addresses are query context only.
- Requires SEARCH_PROVIDER=brave and BRAVE_SEARCH_API_KEY.
- Adds migration 0017_company_websites; existing candidate/profile data is preserved.
