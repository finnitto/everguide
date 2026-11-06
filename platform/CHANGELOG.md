# Changelog

## 0.3.1 — Google Places error diagnostics
- Preserve Google's structured HTTP error response in failed discovery run details (HTTP status, API status and message).
- Distinguish invalid request parameters from API enablement, billing and key restriction errors.
- No database schema changes; existing discovery runs, providers and branches are preserved.


## 0.3.0 — Initial automated discovery connector
- Added a Google Places API (New) discovery connector and background Celery task.
- Added discovery run tracking and pending Place ID source observations; raw Google business content is not persisted.
- Added an admin control to launch and monitor a single England regional discovery pass.
- Discovery candidates are evidence only; they do not create or publish directory records.
- Added local GOOGLE_PLACES_API_KEY configuration.
- Initial 40-anchor regional pass is not a boundary-validated exhaustive England census; coverage refinement remains required.


## 0.2.1 — Web build corrections
- Fixed ESLint configuration imports to use explicit `.js` module paths.
- Removed an unused `useSearchParams` reference from the public search page; initial search terms are read from the URL after mount.
- No database schema changes; existing local data and volumes are preserved.


## 0.2.0 — Core directory
- Added parent provider and branch data models with separate lifecycle statuses.
- Added source observations with source attribution, retrieval timestamps, confidence and review status.
- Added audit event recording for provider and evidence changes.
- Added provider CRUD, branch creation, status management, dashboard metrics and public published-directory search API endpoints.
- Replaced the administration placeholder with a working local provider management interface.
- Added public directory search against published providers and branches.
- Added database migration `0002_core_directory`.
- Kept automated discovery, enrichment, pricing extraction, authentication and production hardening out of scope for this release.

## 0.1.1
- Corrected Redis client dependency compatibility.
- Corrected release ZIP root layout.

## 0.1.0
- Established Docker Compose, Next.js, FastAPI, PostgreSQL/PostGIS, Redis and Celery foundation.
