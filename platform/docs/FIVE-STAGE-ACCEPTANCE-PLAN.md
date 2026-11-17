# Everguide five-stage implementation acceptance plan

**Working branch:** `stage1-overture-identity-provenance`  
**Current implementation baseline:** commit `7913a992727ddfe415f8b195632a62b03284867f` (application and test changes; later documentation commits may advance HEAD)  
**Product policy:** `overture-first-approval-v2.0`  
**Release target:** 2.8.0  
**Operational mode during implementation and validation:** non-production; automatic publication, post-import processing and scheduled feed tasks remain disabled by default.

This plan turns the five stage names in the 17 November 2026 engineering handover into evidence-based completion criteria. It supplements the existing release roadmap; it does not change the agreed Overture-first source policy.

## Completion standard

A stage is complete only when:
1. Its code and configuration are present on the working branch.
2. Relevant automated tests pass in GitHub Actions.
3. Required security, migration and package evidence is recorded.
4. Product acceptance criteria are explicitly checked.
5. Operational evidence is not inferred from isolated CI: production/local database migration, live feed processing, publication and workload replacement require separate controlled authorization.

Status labels:
- **Implemented:** code exists.
- **CI validated:** current code passes relevant automated checks.
- **Accepted:** product and operational acceptance evidence is complete.
- **Signed off:** all stage exit criteria are evidenced and reviewed.

## Stage 1 — Overture discovery, provenance and access controls

### Scope
- Official Overture Places STAC/GeoParquet feed is the only source for initial discovery.
- GERS ID is the stable candidate identity; preserve Overture release, contributor, source record and licence provenance.
- Retire caller-supplied candidate imports, independent Google Places/Companies House/company-website discovery, direct provider creation and direct branch creation.
- Store reviewer-authenticated Overture-to-Companies House links and structured review evidence. An unverified or absent link cannot be used as a Companies House identity signal.
- Require reviewer bearer authentication for active administrative reads and mutations; preserve only intentionally public directory-search and health/readiness interfaces.
- Record reviewer attribution from the authenticated credential, not from request data.
- Additive migrations 0021 and 0022 are present and ordered; 0022 is optional provenance for website-derived branch proposals and is not a prerequisite for Overture-first publication.

### Exit criteria
- [ ] Feed is the only active initial discovery path; legacy/independent paths are disabled or return 410.
- [ ] GERS/provenance/licence fields are durable and idempotent.
- [ ] No active API path bypasses the Overture publication worker to create/publish providers or branches.
- [x] All internal API routes pass the reviewer route-introspection/auth tests; only directory search and health/readiness/API-root remain public.
- [x] Migrations 0021 and 0022, followed by migration 0023, pass isolated upgrade and schema validation in the current CI stack.
- [x] Full API and front-end checks pass on the current branch (176 API tests, lint, TypeScript and production build in run #153).
- [ ] Stage acceptance records source-rights and admin-access review.

### Current assessment
Core Overture-only discovery, GERS/source/release/contributor/licence provenance, verified Companies House links, retired creation/discovery bypass paths and the Overture approval write boundary are implemented. Observation creation, provider edits, provider status changes and observation decisions require reviewer authentication and record the authenticated reviewer as audit actor. The branch passed run #166 (179 API tests, frontend lint/type/build, release-archive checks and disposable Docker integration through 0023). Source-rights review and product/operational acceptance remain outstanding; no live candidate processing or publication was performed.

## Stage 2 — Overture-first identity and branch approval

### Binding policy
- Overture is authoritative for the published provider/branch name and branch location fields.
- Companies House and official provider websites are optional corroboration and conflict-only evidence, not mandatory approval prerequisites.
- Missing Companies House linkage, missing/unreachable website, robots restrictions, missing telephone and absent branch mention do not alone prevent an otherwise valid Overture candidate from becoming eligible.
- A Companies House conflict is usable only through an explicitly reviewer-verified Overture-to-Companies House link.
- Website conflict evidence must be explicit, first-party, reachable and robots-permitted. A postcode mismatch is material only where the structured street and locality identify the same Overture branch; a different branch at the same provider website is not a conflict for this branch.
- Registered-office differences and legal/trading-name differences alone are not conflicts.
- Source rights/licence, service classification, complete structured Overture address, valid postcode, official ONS England geography, duplicate/collision and write-boundary checks remain mandatory.
- Outcomes remain `auto_approved_eligible`, `awaiting_enrichment`, `exception_review` and `excluded`. Eligibility is not publication while the automatic approval switch is disabled.

### Exit criteria
- [ ] Unit and pipeline tests cover each approval gate and material conflict.
- [ ] Tests demonstrate that absent/unreachable/robots-blocked websites do not create conflicts.
- [ ] Tests demonstrate that a multi-branch website's unrelated address does not create a postcode conflict.
- [ ] Tests cover explicit closure, same-branch postcode mismatch, verified dissolved CH entity, unverified CH link, registered-office mismatch and legal/trading-name variance.
- [ ] Tests cover service exclusions, unknown/missing licences, duplicate GERS, existing-provider collision, incomplete addresses and unavailable/stale ONS boundary data.
- [ ] Non-mutating outcome analysis is completed on a safe, read-only snapshot: eligible, awaiting enrichment, exception and excluded counts plus reason distribution and sample false-positive review.
- [ ] Product owner accepts conflict precision and sample decisions before any operational switch is changed.

### Current assessment
Ruleset `overture-first-approval-v2.0` and synthetic approval/conflict regression coverage are implemented and passed run #166. Conflict handling uses verified Companies House links and reachable, robots-permitted first-party evidence aligned to the same branch street/locality. Non-mutating candidate outcome analysis on a safe read-only snapshot and product acceptance remain outstanding. Do not import, process or publish live operational records as part of acceptance.

## Stage 3 — Enrichment, pricing and verification automation

### Scope
This stage must keep distinct evidence domains separate:
- Optional business/branch enrichment from authoritative sources, without replacing Overture's branch identity/location fields.
- Pricing/tariff extraction with source URL, retrieval timestamp, applicability, effective date, currency, service/fee breakdown, extraction evidence and human approval status.
- Membership and regulatory checks as independent status records, including relevant NAFD, SAIF/SAIFCharter and FCA checks where applicable. A membership or FCA status must not be inferred from a company name or generic website text.
- Sole traders and ordinary partnerships, which may not have Companies House entities, must remain representable without inventing a legal-entity link.
- Multi-branch discovery and branch-level revalidation.
- Explicit evidence freshness, expiry, bounded retries, source rights, exception handling and audit history.

### Exit criteria
- [ ] Signed data dictionary and source policy for each evidence domain (draft data dictionary added; source-specific policy/legal review remains outstanding).
- [x] Separate models/statuses for pricing, membership and regulatory evidence; no conflation with provider identity or publication approval.
- [x] Evidence records capture source URL/name, rights basis, optional approved source-permission reference, retrieval time, evidence payload/digest, reviewer decision and effective/expiry dates.
- [x] Reviewer-created revalidation requests are idempotent, persisted, resumable and bounded to four attempts; transient failure remains a revalidation outcome and never changes the evidence's reported or review status.
- [x] Branch evidence is linked to a branch belonging to the selected provider; provider-wide evidence remains explicitly provider-scoped.
- [x] Sole trader/partnership representation is supported without requiring a Companies House link; multi-branch coverage has branch-scope tests.
- [x] Human evidence approval is separate from provider identity approval/publication; all new evidence is pending review by default.
- [ ] Automated source-specific retrieval, freshness scheduling, source rights configuration and exception handling are not implemented; they require accepted source policy and connector design.
- [ ] Test fixtures cover stale, missing, conflicting, expired and unavailable source evidence across the complete automated revalidation path.

### Current assessment
The Stage 3 evidence foundation is implemented and passed run #166: separate pricing, membership and regulatory evidence, source provenance, provider/branch scope, sole-trader/partnership representation, reviewer-only decisions and bounded idempotent manual revalidation. Migration `0023_stage3_evidence` passed disposable PostgreSQL upgrade/downgrade/re-upgrade validation. Automated source-specific retrieval/scheduling, source-policy/legal sign-off, agreed pricing taxonomy and the full automated freshness/exception path remain open; therefore Stage 3 is not signed off.

## Stage 4 — Operational resilience, security and maintenance

### Scope
- Complete reviewer/admin role separation and least-privilege authorization.
- Secure credential provisioning, storage, rotation, revocation and audit; prevent secrets from entering logs, manifests or archives.
- Verify backup scheduling, retention, encryption, restore procedures and recovery-point/recovery-time objectives.
- Observability across API, Postgres, Redis, worker and Beat: structured logs, useful metrics, readiness/liveness, backlog/age, task failures, retries and alerts.
- Bounded retry/recovery, idempotency, stale-run repair and poison-message handling.
- Data retention, privacy and evidence revalidation policy.

### Exit criteria
- [x] Route-by-route auth boundary and regression matrix: every internal `/api/v1/...` route requires the reviewer dependency except public `/api/v1/directory/search`; valid, invalid/revoked token, unauthenticated read/write and public-route checks passed run #147.
- [ ] Role and permission matrix agreed; a single reviewer token role is not treated as a complete RBAC design.
- [ ] Secret lifecycle and rotation runbook tested ([reviewer credential operations](REVIEWER-CREDENTIAL-OPERATIONS.md) documents provisioning, rotation, revocation, and the in-memory admin token flow; simulated invalid/revoked-token tests passed run #147, but target-environment rotation/revocation remains outstanding).
- [ ] Backup artifact is produced, integrity-checked and restored into an isolated environment; restore evidence recorded.
- [ ] Failure injection covers database/Redis interruption, worker loss, task redelivery, rate limiting and upstream outage.
- [ ] Alerts and operational dashboards cover the agreed service-level indicators.
- [ ] Data retention, audit and evidence refresh/expiry policies are documented.
- [ ] No production readiness claim is made from unit tests or disposable CI alone.

### Current assessment
Partially implemented. Every internal `/api/v1/...` route is reviewer-protected except the intentionally public directory search; route-introspection, unauthenticated read/write, valid/invalid/revoked-token and public-route tests passed run #166. The admin UI prompts for a reviewer token held in memory and attaches it to all internal API calls. Audit attribution is tested and credential provisioning/rotation/revocation is documented. Role separation/RBAC, target-environment secret rotation, backup/restore, observability/alerts, retention and broader operational runbooks remain open.

## Stage 5 — Integrated release validation and packaging

### Scope
- Reconcile `VERSION`, web package metadata, Compose defaults, README, CHANGELOG, release manifest, migration list and acceptance-plan references.
- Run full API tests, frontend lint/type/build and isolated Docker integration from the exact release source.
- Generate a release archive from the maintained `platform/` tree; do not distribute the superseded `release_v2.8.0/` snapshot.
- Inspect archive contents; verify secrets, .env files, local data, database volumes, caches and test outputs are excluded while migrations, source, documentation and operational scripts are included.
- Record archive size/hash, source commit and release manifest.
- Review migration SQL/DDL, schema compatibility, target Alembic revision and rollback limitations. Rehearse against a disposable copy, never against the persistent operational database as a routine CI action.

### Exit criteria
- [x] Run #166 passed 179 API tests, frontend lint/type/production build and isolated Docker integration through migration 0023. This is an implementation checkpoint, not release sign-off.
- [x] Release manifest and migration list declare migrations 0021, 0022 and 0023; version consistency passed run #166.
- [ ] Corrected deterministic release archive, including the explicit exclusion of development patch helper files, is rebuilt and uploaded on the current head. Run #166 validated the initial packager, but manual archive inspection found `stage1_api_patch.py` and `stage1_task_patch.py` should not ship; a follow-up exclusion and test are now committed.
- [ ] Corrected archive exclusion audit confirms secrets, environment files (except templates), package-manager credentials, cloud/SSH keys, development patch helpers, databases, candidate datasets, caches, dependencies and build outputs are excluded.
- [x] Migration 0023 downgrade to 0022 and forward upgrade back to 0023 were rehearsed on the disposable PostgreSQL stack in run #166; target-host rollback/forward-fix decision remains separate.
- [ ] Pre-replacement checklist is completed for the actual target host/database: Git status, config, current revision, verified restorable backup, image build, migration plan and post-upgrade health checks.
- [ ] Local validation is run only when replacing the existing workload, in line with the operator's preference; no `docker compose down -v` on the existing project.
- [ ] Release sign-off records the exact source commit, archive hash, CI run and migration evidence.

### Current assessment
Run #166 on commit `32b1ddef7e94e9493371081e6fe57fd1ac077fa8` passed 179 API tests, Python compile, frontend lint/type/production build, deterministic package generation and artifact upload, plus isolated Docker migration validation. The disposable PostgreSQL stack successfully downgraded from `0023_stage3_evidence` to `0022_branch_overture_provenance`, upgraded back to `0023`, and verified all five evidence tables plus `providers.business_form`. The first generated archive passed integrity checks but included two development patch helpers; these are now excluded and covered by regression tests, and the corrected package awaits a fresh run. The root `release_v2.8.0/` snapshot remains superseded. Target-host backup/replacement checklist and release sign-off remain outstanding.

## Non-negotiable operating safeguards

- Keep `AUTO_APPROVE_PROVIDERS=false`, `OVERTURE_AUTO_PROCESS=false` and `OVERTURE_SCHEDULED_TASKS_ENABLED=false` throughout development and validation.
- Keep `OVERTURE_FEED_ENABLED=false` in disposable validation.
- Do not run live Overture imports, candidate assessment/publication or external enrichment as a substitute for tests.
- Do not migrate or replace the persistent local workload during this review.
- Never run `docker compose down -v` against the existing project.
- Before any later workload replacement, inspect the exact target database/configuration, create and verify a restorable PostgreSQL backup, inspect Alembic current/history and review upgrade/rollback consequences.

## Evidence ledger

- Current implementation branch: `stage1-overture-identity-provenance`.
- Handover baseline: `0958c66a2ec6b6b387accde2b802f84ec927faf1`.
- Earlier CI baseline: [run #38](https://github.com/finnitto/everguide/actions/runs/44118434200).
- Latest completed Stage 5 checkpoint before the development-helper exclusion correction: [run #166](https://github.com/finnitto/everguide/actions/runs/44153667313), commit `32b1ddef7e94e9493371081e6fe57fd1ac077fa8`; 179 API tests, deterministic archive build/artifact upload and disposable migration 0023 downgrade/forward-upgrade passed. Corrected package exclusion changes await a fresh run.
- Overture approval policy: [OVERTURE-AUTOMATIC-APPROVAL.md](OVERTURE-AUTOMATIC-APPROVAL.md).
- Validation procedure: [VALIDATION.md](VALIDATION.md).
- Current release metadata: [RELEASE-MANIFEST.json](../RELEASE-MANIFEST.json).

This acceptance plan is a working engineering control. It does not authorize a production deployment or persistent database migration.
