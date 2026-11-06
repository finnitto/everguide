# Changelog

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

## 0.6.1
- Introduced a provider-independent search adapter interface.
- Moved Brave-specific HTTP handling out of the discovery task into `search_providers.py`.
- Added SEARCH_PROVIDER configuration; Brave remains the implemented and default adapter.
- Added an explicit, safe response when Google is selected without a supported eligible API integration.
- Corrected Docker Compose environment formatting and wired SEARCH_PROVIDER to API and worker.
- No schema migration; existing website candidates and provider records are preserved.

# Changelog

## 0.6.0
- Added independent Brave Search API integration for automatic regional funeral-director website discovery.
- Added an England regional search job, candidate URL provenance storage, status endpoint and admin dashboard.
- Removed the provider-by-provider website registration form from the main workflow.
- Excludes SAIF and NAFD directory domains from candidate ingestion.
- Requires BRAVE_SEARCH_API_KEY; use a Brave plan whose terms permit storage of returned search-result data.
- Candidate websites are not yet verified official websites; no business facts are extracted or provider records updated in this release.

# Changelog

## 0.5.2
- Reframed provider-owned website research as automatic technical screening without requiring an individual permission record for each provider.
- Made source notes optional and clarified that registration is not legal clearance to extract, retain or publish content.
- Added source classes and safeguards for provider-owned sites, restricted sources and third-party curated directories.
- SAIF and NAFD bulk directory ingestion remains excluded pending an appropriate licence or confirmed legal basis.
- Existing worker remains metadata-only; no business facts are extracted and no provider records are auto-updated or published.

# Changelog

## 0.5.1
- Revised provider website registration to queue automated technical eligibility checks.
- Removed individual administrator approval as a prerequisite for initial technical checks.
- Clarified robots.txt is a crawler instruction, not a licence or reuse permission.
- Kept checks metadata-only; no page body extraction, provider updates, match confirmation or publication.

# Changelog

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
