# Everguide implementation roadmap

## Release 0.1.0 – Development foundation
- [x] Next.js application scaffold
- [x] FastAPI service scaffold
- [x] PostgreSQL/PostGIS container
- [x] SQLAlchemy/Alembic foundation
- [x] Redis/Celery worker scaffold
- [x] Docker Compose
- [x] Local deployment and packaging scripts
- [x] Basic API tests and health checks

## Release 0.2.0 – Core provider directory (implemented)
- [x] Parent provider and branch entities
- [x] Branch contact details, service fields and coordinates
- [x] Source observations with attribution, retrieval time and confidence
- [x] Audit events for provider and evidence actions
- [x] Versioned database migration
- [x] Provider CRUD, status management and directory search API
- [x] Local admin provider creation and review-status controls
- [x] Public search limited to published providers and branches
- [x] API smoke tests for core directory workflows

## Subsequent releases
- Public directory search and profiles
- Admin authentication and role-based access
- England-wide discovery and candidate review
- Provider enrichment and verification
- Pricing discovery, extraction and approval
- Scheduled revalidation and exception workflows
- AWS deployment and infrastructure as code

## v2.6.1 – Automation-first provider approval (implemented first pathway)
- [x] Configurable automatic approval switch and confidence threshold.
- [x] High-precision first-party website approval using explicit Schema.org `FuneralHome`, complete UK address, telephone, matching website domain, Companies House name relationship and duplicate checks.
- [x] Automatic creation/publication of eligible provider and first branch, with accepted source observation and audit events.
- [x] Exception routing for incomplete, conflicting, low-confidence, duplicate or ambiguous candidates.
- [x] Exclude auto-approved records from the manual identity/branch exception workflow.
- [ ] Extend independent evidence pathways to providers not represented in Companies House (sole traders and partnerships).
- [ ] Automate multi-branch discovery and branch-level revalidation.
- [ ] Automate NAFD, SAIF/SAIFCharter and FCA checks with independent status records.
- [ ] Add source-permission policy configuration and legal review before commercial rollout.
- [ ] Expand the ruleset with calibrated validation data and false-positive/false-negative monitoring.


## Stage 3 evidence data foundation

- [x] Separate pricing, membership and regulatory evidence records with source provenance and reviewer-only decisions.
- [x] Provider-wide and branch-specific evidence scopes; explicit sole-trader/partnership business form without requiring a Companies House link.
- [x] Idempotent, bounded reviewer-recorded revalidation ledger; transient failure does not imply negative verification.
- [ ] Source-specific permitted retrieval, automated refresh, agreed pricing taxonomy and signed policy remain open. See [Stage 3 evidence data dictionary](STAGE3-EVIDENCE-DATA-DICTIONARY.md).

## Stage 4 reviewer-access hardening

- [x] Apply reviewer authentication at every internal admin router boundary; keep only the public directory search and health/root endpoints unauthenticated.
- [x] Add route-graph regression coverage, unauthenticated mutation/read checks, valid/invalid/revoked-token checks and public-route checks; passed in GitHub Actions run #147.
- [x] Attribute provider/observation audit events to the authenticated reviewer.
- [x] Document credential provisioning, rotation, revocation and incident handling in [REVIEWER-CREDENTIAL-OPERATIONS.md](REVIEWER-CREDENTIAL-OPERATIONS.md); the admin page now uses an in-memory token prompt.
- [ ] Agree and implement role-based permissions and least privilege; test secret lifecycle in the target environment; prove backup/restore, failure recovery, monitoring, retention and runbooks.

## Five-stage implementation acceptance

The current five-stage status, exit criteria, evidence requirements and operating
safeguards are maintained in [FIVE-STAGE-ACCEPTANCE-PLAN.md](FIVE-STAGE-ACCEPTANCE-PLAN.md).
The plan preserves the Overture-first policy and separates implemented code,
CI validation, product acceptance and operational sign-off.
