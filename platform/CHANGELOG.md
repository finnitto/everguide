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
