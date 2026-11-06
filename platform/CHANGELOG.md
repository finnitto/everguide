# Changelog

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
