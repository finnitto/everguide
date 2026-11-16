# Everguide v2.7.4

## Overture website evidence and boundary reliability

- Treat Overture website values as attributed discovery leads, not proof that a domain is provider-owned. Known directory, listing, news/company-record and search-result pages are excluded from first-party website verification.
- Search for a provider-owned HTTPS website independently; only a page whose extracted business name, postcode and telephone match the Overture candidate is accepted as first-party evidence. Search-result mismatches are discarded rather than promoted to identity conflicts. A mismatch on the candidate's own non-directory URL remains an exception signal.
- Preserve the original discovery URL and its classification in the candidate evidence while keeping it separate from the verified provider website.
- Cache validated ONS England and Thurrock boundary geometry in a dedicated Docker named volume across 20-record task batches and worker restarts. Cache files include source URL, retrieval timestamp, schema version and SHA-256 digest; malformed, modified or expired cache entries are rejected.
- Retry transient ONS transport, incomplete-read and TLS verification failures with bounded backoff. TLS certificate and hostname verification remain enabled. Boundary failure remains fail-closed for publication.
- Change automatic publication defaults to disabled in application configuration and Docker Compose. Existing `.env` values remain authoritative.
- Adds a bounded enrichment retry cycle (initial assessment plus at most three retries after 2, 7 and 21 days); unresolved identity/branch exceptions and exclusions are not retried.
- Adds daily stale-run reconciliation: recover old unclaimed candidates, resume incomplete work, and close orphaned runs with explicit audit events; no history is deleted.
- No database migration and no changes to existing provider, branch, PostgreSQL or Redis data. The new `ons_boundary_cache` Docker volume stores only validated boundary cache files.

## Validation

- Automated tests cover third-party lead filtering, first-party website matching, persistent boundary cache integrity/expiry and bounded ONS retries.
- Python compile passed; 113 API tests passed using SQLite and local Celery/Redis test shims. This is not a substitute for running against the production dependency set.
- Docker image build was not run (Docker unavailable); frontend build was not run (`node_modules` absent); live ONS/Overture calls were not run. These checks remain for the target installation.
