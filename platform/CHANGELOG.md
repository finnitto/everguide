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
