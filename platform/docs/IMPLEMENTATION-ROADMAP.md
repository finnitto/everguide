# Everguide implementation roadmap

Current engineering state, validation evidence and next operational gates are summarised in [Development handover](DEVELOPMENT-HANDOVER.md).

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

## Stage 5 release packaging and migration rehearsal

- [x] Add deterministic ZIP generation from the maintained `platform/` tree, fixed timestamps/member order, required-file/version checks, SHA-256 checksum and source-commit package manifest.
- [x] Add synthetic regression tests for archive reproducibility, ZIP integrity, required files and secret/local-data exclusions.
- [x] Add CI artifact upload for the ZIP and both sidecars, with 14-day retention.
- [x] Add disposable PostgreSQL downgrade from migration 0023 to 0022 and forward-upgrade to 0023, verifying the new evidence tables/column.
- [x] Corrected package excludes `stage1_api_patch.py` and `stage1_task_patch.py`; reproducibility, integrity, secret/local-data exclusion and artifact upload passed GitHub Actions run #183.
- [ ] Complete target-host backup/restore, rollback/forward-fix and replacement checklist before any persistent workload change.

## Price enrichment and verification transparency — next milestone

**Implementation status:** In progress on `stage1-overture-identity-provenance`; new extraction/reviewer flow requires CI validation and a controlled staging trial.

- [x] Queue price enrichment after automatic Overture publication.
- [x] Queue price enrichment after manual provider approval.
- [x] Add an idempotent backfill for already-approved/published Overture-linked funeral-director candidates.
- [x] Add a bounded AI extraction worker using verified provider-owned websites, same-host HTTPS pages and robots checks.
- [x] Require reviewer-approved `SourcePermission` before price-page retrieval; release candidates waiting for permission when the matching source is approved.
- [x] Restrict extraction to explicit GBP amounts and require a matching source-page quotation; never infer or invent a price.
- [x] Store extracted amounts as pending `PricingEvidence` with source URL, quote, SHA-256, model and Overture candidate provenance.
- [x] Distinguish `AI-extracted · Not verified` from `Verified by Everguide reviewer` in the API and public search display.
- [x] Add reviewer approve/reject UI for price evidence and source permission approval.
- [ ] Pass CI on the latest branch head, including extraction, provenance, source-permission and public-display tests plus isolated Docker validation.
- [ ] Run a controlled staging trial with a small known candidate set and privately configured API key.
- [ ] Measure extraction precision, review corrections, page coverage and API cost; agree thresholds before expansion.
- [ ] Add reviewer requeue/re-extraction controls, stale-price handling, history/change detection and scheduled revalidation.
- [ ] Complete source-use/legal review, retention policy and production monitoring before enabling AI price enrichment beyond the pilot.

Runtime defaults remain `PRICE_ENRICHMENT_ENABLED=false` and `OPENAI_API_KEY` unset. Provider approval does not verify price evidence; no AI-extracted price may be marked verified without reviewer approval. See [Development handover](DEVELOPMENT-HANDOVER.md) for controls, local state and staged acceptance criteria.

## Five-stage implementation acceptance

The current five-stage status, exit criteria, evidence requirements and operating
safeguards are maintained in [FIVE-STAGE-ACCEPTANCE-PLAN.md](FIVE-STAGE-ACCEPTANCE-PLAN.md).
The plan preserves the Overture-first policy and separates implemented code,
CI validation, product acceptance and operational sign-off.
