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
- [ ] All active administrative endpoints pass unauthenticated 401 and authenticated access tests; public endpoints are documented.
- [ ] Migrations 0021 and 0022 pass isolated upgrade and schema validation.
- [ ] Full API and front-end checks pass.
- [ ] Stage acceptance records source-rights and admin-access review.

### Current assessment
Core implementation is present. A code review found and fixed three missed administrative protections: observation creation, source-permission listing and website-check listing. The new regression tests and current full CI run must pass before Stage 1 is signed off.

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
Ruleset v2.0 is implemented. The postcode-conflict detector has been narrowed to verified first-party evidence about the same street/locality, and regression tests were added. A read-only candidate outcome analysis and product acceptance remain outstanding. Do not import, process or publish operational records as part of acceptance.

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
- [ ] Signed data dictionary and source policy for each evidence domain.
- [ ] Separate models/statuses for pricing, membership and regulatory evidence; no conflation with provider identity or publication approval.
- [ ] Every evidence item records source, retrieved/checked time, evidence payload/digest, status, reviewer/automation actor and any effective/expiry dates.
- [ ] Revalidation is idempotent, bounded and resumable; transient failures do not become negative verification decisions.
- [ ] Branch evidence is linked to the correct branch, not merely the provider parent.
- [ ] Sole trader/partnership and multi-branch cases are tested.
- [ ] Human approval and publication boundaries are explicit; no new automatic publishing behavior without a separately accepted policy.
- [ ] Test fixtures cover stale, missing, conflicting, expired and unavailable evidence.

### Current assessment
Not signed off. Some legacy enrichment components exist, but the current Overture-first workflow and five-stage evidence model need a consolidated implementation and data-contract review before treating this stage as complete.

## Stage 4 — Operational resilience, security and maintenance

### Scope
- Complete reviewer/admin role separation and least-privilege authorization.
- Secure credential provisioning, storage, rotation, revocation and audit; prevent secrets from entering logs, manifests or archives.
- Verify backup scheduling, retention, encryption, restore procedures and recovery-point/recovery-time objectives.
- Observability across API, Postgres, Redis, worker and Beat: structured logs, useful metrics, readiness/liveness, backlog/age, task failures, retries and alerts.
- Bounded retry/recovery, idempotency, stale-run repair and poison-message handling.
- Data retention, privacy and evidence revalidation policy.

### Exit criteria
- [ ] Route-by-route auth matrix and tests for every active admin read/write, including negative and positive credential tests.
- [ ] Role and permission matrix agreed; a single reviewer token role is not treated as a complete RBAC design.
- [ ] Secret lifecycle and rotation runbook tested.
- [ ] Backup artifact is produced, integrity-checked and restored into an isolated environment; restore evidence recorded.
- [ ] Failure injection covers database/Redis interruption, worker loss, task redelivery, rate limiting and upstream outage.
- [ ] Alerts and operational dashboards cover the agreed service-level indicators.
- [ ] Data retention, audit and evidence refresh/expiry policies are documented.
- [ ] No production readiness claim is made from unit tests or disposable CI alone.

### Current assessment
Partially implemented. Reviewer bearer authentication, audit attribution, health/readiness checks, retry/recovery paths and several CI safeguards exist. This review found three route-level authentication gaps and closed them in code with tests. Role separation, credential lifecycle, proven backup/restore, observability/alerts and operational runbooks remain open.

## Stage 5 — Integrated release validation and packaging

### Scope
- Reconcile `VERSION`, web package metadata, Compose defaults, README, CHANGELOG, release manifest, migration list and acceptance-plan references.
- Run full API tests, frontend lint/type/build and isolated Docker integration from the exact release source.
- Generate a release archive from the maintained `platform/` tree; do not distribute the superseded `release_v2.8.0/` snapshot.
- Inspect archive contents; verify secrets, .env files, local data, database volumes, caches and test outputs are excluded while migrations, source, documentation and operational scripts are included.
- Record archive size/hash, source commit and release manifest.
- Review migration SQL/DDL, schema compatibility, target Alembic revision and rollback limitations. Rehearse against a disposable copy, never against the persistent operational database as a routine CI action.

### Exit criteria
- [ ] All CI jobs pass on a commit containing the final code and docs.
- [ ] Release metadata and manifest agree; migrations 0021 and 0022 are declared.
- [ ] Release archive is reproducible from the maintained source and passes ZIP/integrity checks.
- [ ] Archive exclusion audit confirms no secrets or live data are included.
- [ ] Migration upgrade is rehearsed on a disposable database; rollback/forward-fix approach is documented.
- [ ] Pre-replacement checklist is completed for the actual target host/database: Git status, config, current revision, verified restorable backup, image build, migration plan and post-upgrade health checks.
- [ ] Local validation is run only when replacing the existing workload, in line with the operator's preference; no `docker compose down -v` on the existing project.
- [ ] Release sign-off records the exact source commit, archive hash, CI run and migration evidence.

### Current assessment
Partially validated. Earlier run #38 passed API/frontend checks, production frontend build and isolated Docker integration through migration 0022. Follow-up code changes require a new CI pass. The root `release_v2.8.0/` snapshot is marked superseded. Current archive regeneration and integrity/exclusion audit remain outstanding.

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
- Earlier successful CI baseline: [run #38](https://github.com/finnitto/everguide/actions/runs/44118434200).
- Overture approval policy: [OVERTURE-AUTOMATIC-APPROVAL.md](OVERTURE-AUTOMATIC-APPROVAL.md).
- Validation procedure: [VALIDATION.md](VALIDATION.md).
- Current release metadata: [RELEASE-MANIFEST.json](../RELEASE-MANIFEST.json).

This acceptance plan is a working engineering control. It does not authorize a production deployment or persistent database migration.
