## 1.5.0 — Existing provider quality assessment and source reconciliation

- Adds an idempotent bulk assessment endpoint for existing provider records using only evidence already retained in Everguide.
- Separates evidence-supported records, records needing review, and records with insufficient retained evidence. Insufficient evidence is not treated as proof that a provider is invalid.
- Writes an audit event for each newly assessed provider; existing records are never automatically unpublished, deleted or merged.
- Adds an admin action to assess all currently unassessed provider records.
- Adds source-observation counts grouped by source type to make the pending observation backlog more transparent. Google Places Place ID observations remain pending and are not enriched from restricted Places content.
- No database migration required.
- County enrichment is not automated in this release; postcode values are retained for a separately controlled authoritative lookup.

# Changelog

## 1.4.0 — Provider quality safeguards
- Added provider quality status and an auditable review queue.
- Flagged obvious generic, directory, cemetery and council-like existing records for review without deleting or unpublishing them.
- Tightened website identity extraction: structured data alone is insufficient; explicit funeral-sector page language and independent contact/location evidence are required.
- Paused automatic publication by default. Extracted candidates are retained for quality review until AUTO_APPROVE_PROVIDERS=true is deliberately enabled after quality checks.
- Added reporting for quality review and missing branch county/postcode enrichment.

# Changelog

## 1.2.0
- Increased website verification batch size from 50 to 250 candidates.
- Automatically queues the next independently tracked batch when eligible backlog remains.
- Preserves per-candidate commits, per-batch progress, duplicate safeguards and interrupted-batch recovery.
- Updated admin wording to describe automatic backlog processing.
- No database migration required.

# Changelog

## 1.1.1
- Adds backlog reassessment to website verification: previously checked candidates from earlier releases are reprocessed under the expanded v1.1 identity-extraction rules, in batches of up to 50.
- Includes both never-checked and previously checked candidates; already published providers and possible-duplicate holds are excluded.
- Marks candidates that still lack sufficient provider identity evidence as reassessed, with an audit event, preventing repeated processing of the same negative result.
- Adds a dashboard count for candidates awaiting initial checks or reassessment and clarifies the verification action.
- No database migration required; existing verification evidence, provider records, branches and approval history are preserved.

## 1.1.0
- Broadened provider identity extraction beyond Schema.org `FuneralHome` to include `LocalBusiness`, `Organization`, and `ProfessionalService` when explicit funeral-sector language corroborates the entity.
- Supports automatic publication of a clearly identified new provider even when no complete branch address is available; a branch is created only when a complete UK street address, town and postcode are evidenced.
- Retains duplicate holds for exact provider-name, existing postcode and website-domain collisions; existing records are never overwritten.
- Records extracted factual fields, confidence, funeral-sector signals, verification reference and content digest; fetched page bodies remain discarded.
- No database migration required. Pricing remains outside automatic approval.

## 1.0.4
- Fixed stale verification recovery API failure by importing the audit model used when recording interrupted batches.
- Recovers old queued/running batches when the Celery worker responds but no longer reports their task; also handles batches whose task ID was not persisted.
- Keeps recovery conservative: if worker inspection is unavailable, active batches are not changed.
- Preserves prior verification checks, provider records, branches and approval audit history.
- No database migration required.

# Changelog

## 1.0.3
- Recover abandoned website-verification batches when a responding Celery worker no longer reports the associated task as active, reserved, or scheduled.
- Preserve previously committed verification checks and approval records when recovering an interrupted batch.
- Improve the web container health check to probe the admin route and report HTTP/transport failures.
- No database migration required.

# Changelog

## 1.0.2
- Fixed migration startup failure: shortened the Alembic revision identifier to fit PostgreSQL’s existing 32-character `alembic_version.version_num` column. The migration filename and schema change remain the same.
- Keeps the v1.0.1 status-column widening and transaction rollback fixes.

## 1.0.1
- Fixed website candidate status truncation: widened `website_discovery_results.status` from 30 to 80 characters so duplicate-hold and automatic-approval states can be persisted.
- Fixed verification task error handling: rolls back a failed SQLAlchemy transaction before recording the batch as failed, preventing a secondary `PendingRollbackError` from hiding the original error.
- Previously committed checks remain intact; no provider or branch data is reset or overwritten.
- Adds migration `0009_expand_status` (file: `0009_expand_website_candidate_status.py`).


## 1.0.0
- Added conservative automatic approval and publication for genuinely new providers only when a reachable HTTPS website permits the check and explicitly publishes complete Schema.org FuneralHome identity and UK branch address data.
- Stores structured facts and verification provenance; discards fetched page bodies.
- Holds exact-name, postcode and domain collisions for exception review; existing provider records are never overwritten.
- Adds migration 0008_auto_provider_approval.
- Pricing is not extracted or auto-approved.

# Changelog

## 0.9.0 — Verification batch tracking

- Adds persistent verification-run records with queued, running, completed and failed states.
- Tracks batch size, completed checks, outcome counts, task ID and timestamps.
- Adds an admin activity panel with progress bars and recent batch history; dashboard refreshes automatically every 10 seconds.
- Prevents a second batch from being queued while a tracked batch is queued or running.
- Adds migration `0007_verification_run_tracking`; preserves existing provider, branch, candidate and verification data.
- Does not alter or publish provider records.


## 0.8.0 — Conservative website verification

- Adds a bounded background verification batch for up to 50 likely provider website candidates.
- Checks HTTPS reachability and `robots.txt` before requesting candidate pages; rejects local/private network destinations and embedded URL credentials.
- Does not automatically follow redirects; records them for later manual review.
- Retains only response metadata, page title and a SHA-256 digest; response bodies are discarded.
- Displays verification outcomes in the admin candidate list. No provider or branch records are created, changed or published.
- Adds database migration `0006_website_verification`.


## 0.7.0 — Website candidate triage and provider-name matching

- Cleans HTML fragments and entities from search-result titles and snippets before display.
- Classifies results into likely provider candidates, directory/comparison results, uncertain results and likely irrelevant results using transparent heuristic signals.
- Normalises candidate URLs and reports repeated results from the same domain to support domain-level deduplication.
- Suggests possible matches against existing provider trading names using shared name terms; suggestions are informational only.
- Adds candidate category and domain metrics to the admin view.
- Does not fetch candidate websites, assert official ownership, extract business facts, create or alter providers, or publish records.
- No database migration; all classifications and match suggestions are computed from existing records.

## 0.6.2
- Fixed a malformed literal newline in the admin page state declarations that prevented the Next.js production build.
- No database schema changes.
- No changes to existing provider, branch, discovery, or website-candidate data.

# Changelog

## 0.8.0 — Conservative website verification

- Adds a bounded background verification batch for up to 50 likely provider website candidates.
- Checks HTTPS reachability and `robots.txt` before requesting candidate pages; rejects local/private network destinations and embedded URL credentials.
- Does not automatically follow redirects; records them for later manual review.
- Retains only response metadata, page title and a SHA-256 digest; response bodies are discarded.
- Displays verification outcomes in the admin candidate list. No provider or branch records are created, changed or published.
- Adds database migration `0006_website_verification`.


## 0.6.1
- Introduced a provider-independent search adapter interface.
- Moved Brave-specific HTTP handling out of the discovery task into `search_providers.py`.
- Added SEARCH_PROVIDER configuration; Brave remains the implemented and default adapter.
- Added an explicit, safe response when Google is selected without a supported eligible API integration.
- Corrected Docker Compose environment formatting and wired SEARCH_PROVIDER to API and worker.
- No schema migration; existing website candidates and provider records are preserved.

# Changelog

## 0.8.0 — Conservative website verification

- Adds a bounded background verification batch for up to 50 likely provider website candidates.
- Checks HTTPS reachability and `robots.txt` before requesting candidate pages; rejects local/private network destinations and embedded URL credentials.
- Does not automatically follow redirects; records them for later manual review.
- Retains only response metadata, page title and a SHA-256 digest; response bodies are discarded.
- Displays verification outcomes in the admin candidate list. No provider or branch records are created, changed or published.
- Adds database migration `0006_website_verification`.


## 0.6.0
- Added independent Brave Search API integration for automatic regional funeral-director website discovery.
- Added an England regional search job, candidate URL provenance storage, status endpoint and admin dashboard.
- Removed the provider-by-provider website registration form from the main workflow.
- Excludes SAIF and NAFD directory domains from candidate ingestion.
- Requires BRAVE_SEARCH_API_KEY; use a Brave plan whose terms permit storage of returned search-result data.
- Candidate websites are not yet verified official websites; no business facts are extracted or provider records updated in this release.

# Changelog

## 0.8.0 — Conservative website verification

- Adds a bounded background verification batch for up to 50 likely provider website candidates.
- Checks HTTPS reachability and `robots.txt` before requesting candidate pages; rejects local/private network destinations and embedded URL credentials.
- Does not automatically follow redirects; records them for later manual review.
- Retains only response metadata, page title and a SHA-256 digest; response bodies are discarded.
- Displays verification outcomes in the admin candidate list. No provider or branch records are created, changed or published.
- Adds database migration `0006_website_verification`.


## 0.5.2
- Reframed provider-owned website research as automatic technical screening without requiring an individual permission record for each provider.
- Made source notes optional and clarified that registration is not legal clearance to extract, retain or publish content.
- Added source classes and safeguards for provider-owned sites, restricted sources and third-party curated directories.
- SAIF and NAFD bulk directory ingestion remains excluded pending an appropriate licence or confirmed legal basis.
- Existing worker remains metadata-only; no business facts are extracted and no provider records are auto-updated or published.

# Changelog

## 0.8.0 — Conservative website verification

- Adds a bounded background verification batch for up to 50 likely provider website candidates.
- Checks HTTPS reachability and `robots.txt` before requesting candidate pages; rejects local/private network destinations and embedded URL credentials.
- Does not automatically follow redirects; records them for later manual review.
- Retains only response metadata, page title and a SHA-256 digest; response bodies are discarded.
- Displays verification outcomes in the admin candidate list. No provider or branch records are created, changed or published.
- Adds database migration `0006_website_verification`.


## 0.5.1
- Revised provider website registration to queue automated technical eligibility checks.
- Removed individual administrator approval as a prerequisite for initial technical checks.
- Clarified robots.txt is a crawler instruction, not a licence or reuse permission.
- Kept checks metadata-only; no page body extraction, provider updates, match confirmation or publication.

# Changelog

## 0.8.0 — Conservative website verification

- Adds a bounded background verification batch for up to 50 likely provider website candidates.
- Checks HTTPS reachability and `robots.txt` before requesting candidate pages; rejects local/private network destinations and embedded URL credentials.
- Does not automatically follow redirects; records them for later manual review.
- Retains only response metadata, page title and a SHA-256 digest; response bodies are discarded.
- Displays verification outcomes in the admin candidate list. No provider or branch records are created, changed or published.
- Adds database migration `0006_website_verification`.


## 0.4.1 — Admin JSX build fix

- Fixed malformed JSX in the provider matching review panel that prevented the Next.js production build.
- No API, database, or migration changes.


## 0.4.0 — Provider matching and review queue

- Added conservative provider/branch matching suggestions using business name, postcode, telephone, website domain and town where those fields are already present in source observations.
- Added matching summary and paginated review-queue API endpoints.
- Added human-controlled observation linking to an existing provider and branch, with validation that the branch belongs to the selected provider.
- Added exact duplicate fingerprint reporting for retained Place IDs and observations with sufficient independently sourced business fields.
- Added an admin matching and review panel with match reasons, indicative scores and explicit human link actions.
- Google Places observations continue to retain Place IDs only. Place IDs are exempt from Places API caching restrictions; other Places content is not stored by this release.
- No database migration required. Existing providers, branches, observations and discovery history are preserved.

## 0.3.1 — Google Places error diagnostics

- Improved Google Places HTTP error diagnostics by preserving Google's structured response message without exposing the API key.
- No database migration required.

## 0.3.0 — Initial automated discovery connector

- Added the Google Places API (New) discovery connector.
- Added 40 explicit England regional discovery anchors with 30 km location bias.
- Added background discovery runs and Place ID-only source observations.
- Added run status and discovery configuration endpoints.


## 0.5.1
- Added a source permission register with pending-by-default website source records.
- Added explicit approval before any automated website fetch.
- Added conservative HTTPS homepage evidence checks for approved sources, including robots.txt checks, timeout and response-size limits.
- Stores limited check metadata (HTTP status, page title and content digest), not page bodies; never auto-updates or publishes provider records.
- Explicitly excludes SAIF/NAFD directory ingestion without written permission.
- Adds source permission and evidence-check API endpoints and admin controls.
- Existing Place ID-only Google observations are preserved and are not falsely enriched.

## 1.3.0 — Published directory coverage and quality reporting
- Adds a reporting endpoint for distinct published providers and branches.
- Adds automatic-approval audit reporting based on provider audit events, avoiding raw batch-event totals as a proxy for unique providers.
- Adds published branch counts by county.
- Adds conservative duplicate signals for exact normalised provider names, shared website domains and shared postcodes across providers. Signals are not automatic merges or proof of duplication.
- Adds source observation totals and an admin dashboard report.
- No database migration; existing provider, branch, source and audit records are read only.

## 1.3.0 — Published directory coverage, quality and scheduled discovery
- Adds distinct provider and branch reporting, auto-approval audit reporting, county-level branch coverage and source-observation totals.
- Adds conservative duplicate signals for exact normalised provider names, shared website domains and shared postcodes across providers. These are review signals only; no automatic merges occur.
- Adds weekly England-wide website discovery at 02:00 Europe/London on Sundays via Celery Beat, followed by a bounded verification batch and existing automatic backlog continuation.
- No database migration; reporting reads existing records.
- Full periodic revalidation of all already-published provider websites is not included in this release and remains a separate follow-on capability.

## Operational note
Automatic publication is intentionally paused by default in v1.4.0. Existing providers remain available and are only flagged for quality review; new extracted candidates are held with their evidence for review. Do not enable `AUTO_APPROVE_PROVIDERS` until the quality queue has been sampled and accepted.

## v1.6.0 — Postcode-based branch county enrichment

- Added an admin action to enrich published branches that have a postcode but no recorded county.
- Uses the Postcodes.io bulk postcode lookup endpoint (up to 100 unique postcodes per request).
- Writes only the explicit `admin_county` value returned for an England postcode. It does not substitute an administrative district, region, postal town, or guessed ceremonial county.
- Leaves existing county values and provider/branch publication statuses unchanged.
- Records per-branch lookup outcomes and source metadata in the audit log, plus a batch summary shown in the admin report.
- Reports areas without a county-level authority (including many unitary authorities and London boroughs) separately; these remain blank rather than being assigned a misleading county.
- No database migration required.
