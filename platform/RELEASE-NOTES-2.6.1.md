# Everguide v2.6.1 — Automation-first provider approval

## Purpose

Corrects the v2.6.0 pilot's manual-first emphasis and implements a conservative automatic approval path. Automation is the default; administrators are reserved for exceptions.

## Included

- Deterministic provider auto-approval ruleset `provider-auto-approval-v1.1`.
- Automatic creation and publication of a provider and its first branch when explicit first-party Schema.org `FuneralHome` evidence passes every quality, completeness, confidence, domain and duplicate gate.
- Accepted source observation and audit events for the provider, branch and candidate.
- Exception routing with machine-readable reasons for incomplete, low-confidence, conflicting, duplicate or ambiguous candidates.
- Configurable `AUTO_APPROVE_PROVIDERS` (default `true`) and `AUTO_APPROVAL_MIN_CONFIDENCE` (default `0.94`).
- Discovery summary metrics for auto-approved providers and exception/not-eligible candidates.
- Thurrock workbook retained as an exception-review tool for Overture-derived observations; those observations are not auto-published while source permissions remain unresolved.

## Guardrails

- Only explicit `FuneralHome` structured data qualifies for automatic publication; generic `LocalBusiness` evidence is exception-only.
- Requires complete UK street/locality/postcode and telephone, matching website domain and no exact name/domain/postcode/telephone collision.
- Existing providers and branches are never overwritten, merged or deleted by auto-approval.
- Page bodies are discarded; selected facts and content digest are retained.
- Directory approval is independent of professional membership, FCA status and price approval.
- robots.txt is not treated as a data reuse licence; commercial source terms/legal basis still require review.

## Database and deployment

No new Alembic migration. Existing model/migration already supports extracted structured evidence, source observations, provider/branch records and audit events. Back up PostgreSQL before deployment, preserve `.env` and Docker volumes, and do not run `docker compose down -v`.

## Validation

Focused tests cover automatic eligibility, generic structured-data exception, incomplete address, duplicate provider/branch, domain mismatch, global disable switch and confidence threshold. Full API suite could not be run in the build environment because `psycopg`, `celery` and `redis` runtime dependencies are unavailable; run the full suite in the Docker environment after deployment.
