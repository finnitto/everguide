# Everguide 2.7.7 — Unified approval policy foundation

## What changed

- Added `app.approval_policy`, a shared, deterministic and side-effect-free approval gate for common first-party evidence requirements.
- Integrated both the website/Companies House provider approval adapter and the Overture approval adapter with the shared policy.
- Kept source-specific rules in their adapters: Schema.org FuneralHome and Companies House name relationship checks remain distinct from Overture service classification, contributor licence checks and Overture provenance checks.
- Versioned the adapters as `provider-auto-approval-v1.2` and `overture-auto-approval-v1.1`; both report `shared-provider-approval-v1.0`.
- Added an explicit official-England-boundary requirement to the provider/Companies House approval evaluator. It fails closed unless `point_in_england=True`; points outside England are rejected. Existing task callers do not yet provide this evidence, so those records remain unpublished and reason-coded pending boundary integration.
- Kept the v2.7.6 manual-first scheduling setting: Overture scheduled tasks remain disabled by default.

## Validation

- Targeted approval suite: **24 passed**.
- Python compile check: **passed**.
- Full API test collection: **not completed**. The packaging environment lacks `psycopg`, `celery` and `redis`; 12 test modules failed collection for those missing dependencies. No full-suite pass is claimed.
- No production database was accessed. Frontend and Docker builds were not run.

## Remaining work

1. Wire authoritative ONS England point-in-polygon evidence into every Companies House and website publication path.
2. Add end-to-end tests for each discovery adapter, atomic publication, retry/idempotency and worker interruption.
3. Run the full suite and PostGIS-backed integration tests in the project dependency environment before enabling production automation.
