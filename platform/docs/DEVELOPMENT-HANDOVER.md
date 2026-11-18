# Everguide development handover

**Handover date:** 18 November 2026  
**Repository:** `finnitto/everguide`  
**Working branch:** `stage1-overture-identity-provenance`  
**Pull request:** [PR #1 – Overture-first evidence, reviewer security and release validation](https://github.com/finnitto/everguide/pull/1)  
**Release:** v2.8.0  
**Status:** Implementation and CI validation substantially complete; PR remains draft/unmerged. Local sync, staging acceptance and operational sign-off remain open.

This is the operational handover for the current implementation. It separates code completion and synthetic CI validation from live-source accuracy, product acceptance and production readiness.

## 1. Executive status

Everguide has moved from several independent discovery mechanisms to an Overture-first, evidence-led England funeral-director directory. Overture Places is the only initial discovery source and the authority for the published branch identity/location fields. Companies House and provider-owned websites are optional corroborating/conflict sources; neither is a prerequisite for sole traders or partnerships.

The current branch adds authenticated reviewer workflows, explicit source provenance and rights controls, separate Stage 3 evidence domains, AI-assisted price extraction with human verification, repeatable CI/Docker validation and deterministic release packaging.

**Current gate:** P1 implementation/CI is complete for the application commit identified below. The next action is P1.5 local image/configuration sync without processing data, followed by a staging browser walkthrough and one bounded price-extraction trial. This is not production-ready and does not authorise merge, deployment or feature-flag changes.

## 2. Baseline and repository state

- Requested comparison baseline: `0958c66a2ec6b6b387accde2b802f84ec927faf1`.
- Current public `main` release commit observed during review: `7e07ad81ef05124063d60aafc9da8b8c6da8753b` (v2.8.0).
- Working implementation branch: `stage1-overture-identity-provenance`.
- PR #1 is still draft/unmerged; no submitted PR reviews or inline review threads were present at review time.
- The comparison API reports the supplied baseline as 92 commits ahead of main, while the working branch is a separate 261-commit descendant of main. Treat the supplied SHA as the requested historical reference, not as the current branch head. The branch/PR head must be checked again before any merge or release action.
- The handover-only follow-up commit recorded in PR #1 is `b03cc4240fda973e4a58c7e5da30e357e48c3a0c`; application/Compose validation commit is `431094f0c323656681c241f09f75d3a98a8ed4b9`.

## 3. Product and data policy

1. England-only funeral-director directory.
2. Overture Places is the sole initial candidate source; retain GERS ID, release, contributor lineage, licence and retrieval provenance.
3. Overture remains authoritative for published branch name, address and coordinates. Corroborating sources do not silently overwrite these fields.
4. Companies House linkage must be explicitly reviewer-verified before its record can be used as an identity/conflict signal. Missing linkage does not exclude a candidate.
5. Keep conventional funeral directors distinct from adjacent services, including cemeteries, crematoria, celebrants, memorial/masonry, pet services and funeral-plan-only businesses. Direct-cremation providers remain a separate service category.
6. Same-name/postcode collisions and material coordinate discrepancies go to review. The 100-metre separation is a review trigger, not proof of error. Never automatically merge, delete or overwrite conflicting source records.
7. Provider approval, price extraction, price evidence review, membership/regulatory evidence and public price display are separate decisions.

## 4. Work completed

### 4.1 Overture-first discovery and identity

- Overture GERS IDs and contributor/release/licence provenance are retained.
- Deterministic service classification and conservative candidate-quality checks are implemented.
- Independent Google Places, Companies House-led candidate discovery and independent company-website discovery are retired; legacy routes fail closed/return HTTP 410.
- Direct provider/branch creation and direct publication paths are blocked. Overture approval is the controlled provider/branch publication path.
- Reviewer-verified Overture-to-Companies House links are persisted; absent or unverified links cannot be treated as corroboration.
- Overture-first approval rules distinguish eligible, awaiting-enrichment, exception-review and excluded outcomes.
- A read-only local reassessment of 7,769 candidates was recorded: 5,921 hypothetically eligible, 300 exception review, 136 awaiting enrichment and 1,412 excluded. The 5,921 is not a published-provider count. The exception set includes 256 coordinate-conflict records and 44 possible-same-service duplicate records; these are record counts, not necessarily independent groups.
- Reviewer bearer-token authentication protects internal API routes; reviewer identity for audit events comes from the authenticated credential. Public directory search and health/readiness interfaces are intentional exceptions.
- Authentication is a single reviewer permission tier, not full role-based access control.

### 4.2 Stage 3 evidence foundation

Migration `0023_stage3_evidence` adds separate pricing, membership and regulatory evidence domains and provider business-form metadata. Evidence can be provider-wide or branch-specific, starts pending, carries source/provenance/review data and is reviewed independently of provider publication. Sole traders and partnerships do not require a Companies House link.

The Stage 3 evidence-entry and manual revalidation APIs do not themselves perform NAFD, SAIF or FCA retrieval. Source-specific legal/rights policy, automated retrieval and scheduled freshness remain outstanding.

### 4.3 AI-assisted price extraction

The current branch implements the following guarded workflow:

1. A candidate must be linked to an approved/published funeral-director provider.
2. A verified provider-owned HTTPS website and reviewer-approved source permission for the matching domain are required.
3. Retrieval repeats HTTPS/public-address/SSRF, robots, same-host and bounded-response checks; redirects are not followed automatically.
4. A bounded number of same-host HTML pages is examined (default maximum six).
5. The extractor may return only explicit GBP amounts. It must supply an exact quotation and source-page URL; the application checks the quotation and amount against fetched content and discards unsupported output.
6. Valid results are stored as pending `PricingEvidence`, with source URL, quote, digest, model and candidate provenance.
7. A reviewer approves or rejects the evidence. Public results distinguish **“AI-extracted · Not verified”** from **“Verified by Everguide reviewer”**. Rejected evidence is hidden; evidence is suppressed if its source permission is withdrawn/removed.
8. “Verified by Everguide reviewer” means the reviewer checked the cited source. It is not a provider guarantee and does not establish that the price is still current.

Automatic/manual provider approval can queue candidates for enrichment; an idempotent backfill and reviewer-controlled batch dispatch are available. Queueing does not itself fetch pages or create a price record.

### 4.4 Reviewer UI, release and CI

- Dedicated `/admin/pricing` UI supports source registration/approval and pending price approve/reject review.
- Compose passes the price-enrichment settings to API and worker containers.
- Deterministic release packaging builds from the maintained `platform/` tree, audits required files and exclusions, and emits a ZIP plus checksum/package manifest.
- CI uses synthetic fixtures and disposable infrastructure, not the developer's persistent database.

## 5. Latest validation evidence

GitHub Actions [run #304](https://github.com/finnitto/everguide/actions/runs/44283502723) passed on application/Compose commit `431094f0c323656681c241f09f75d3a98a8ed4b9`:

- 202 backend tests passed (one deprecation warning).
- Python application and migration compilation passed.
- Frontend lint, TypeScript and production build passed.
- Release archive integrity, required-file and exclusion checks passed.
- Isolated Docker integration passed: API readiness, reviewer credential forwarding, safety switches disabled, migration downgrade/re-upgrade `0023 → 0022 → 0023`, admin HTTP 200, empty Beat schedule, online/idle worker.
- Uploaded release artifact: [Actions artifact](https://github.com/finnitto/everguide/actions/runs/44283502723/artifacts/14418545979).
- Uploaded ZIP SHA-256: `8d7441661f134ad6e16631b10f6e3b29ad5d9edf539048d803a3c2cda755a82e`.

The handover-only follow-up is commit `b03cc4240fda973e4a58c7e5da30e357e48c3a0c`. The PR description records that the CI suite covers approval-to-queue hand-off, idempotent backfill, source-permission release, exact quote/amount validation, public pending/verified labels, source-permission withdrawal/removal and Compose configuration forwarding.

**Validation boundary:** no real OpenAI API request, live provider website price extraction, local candidate backfill, production operation or publication has been performed. The code and synthetic integration are CI-validated; real-world extraction accuracy and reviewer usability are not yet validated. CI success is not production sign-off.

## 6. Runtime safety controls

Keep all of the following disabled during local sync and validation:

```dotenv
AUTO_APPROVE_PROVIDERS=false
OVERTURE_AUTO_PROCESS=false
OVERTURE_FEED_ENABLED=false
OVERTURE_SCHEDULED_TASKS_ENABLED=false
PRICE_ENRICHMENT_ENABLED=false
OPENAI_API_KEY=
```

The OpenAI key must be supplied only through an approved private staging/runtime secret store for a separately authorised trial. Never commit it or include it in a release archive. A queue marker may exist while the feature flag is off; it must not be dispatched.

Do not run live Overture processing, website enrichment, price extraction, candidate backfill or publication against the existing local database as part of ordinary validation.

## 7. Milestones and next steps

### P1 — Implementation and CI validation — COMPLETE
- [x] Full backend checks: 202 tests passed.
- [x] Python compile, frontend lint, TypeScript and production build.
- [x] Isolated Docker integration with all automation disabled.
- [x] Reviewer-protected source-permission/evidence routes and pricing queue/review tests.
- [x] Exact quotation/amount validation and public pending/verified/source-revocation behaviour.
- [x] Deterministic release archive and exclusion audit.
- [ ] Manual staging browser walkthrough remains outstanding; this is an acceptance task, not a CI task.

### P1.5 — Sync validated images/config to local development — NEXT
- [ ] Inspect local Git status/branch and resolve or preserve local edits before syncing the validated branch.
- [ ] Rebuild API, worker, Beat and web images from the validated source.
- [ ] Inspect effective settings inside both API and worker containers; verify all five switches above are false and no OpenAI key is configured.
- [ ] Confirm Alembic is at `0023_stage3_evidence`; price-enrichment work adds no migration.
- [ ] Check service readiness and logs. Do not dispatch tasks, process candidates or modify database records.
- [ ] Preserve PostgreSQL, Redis and ONS cache volumes. Never use `docker compose down -v`.

### P2 — Controlled staging price-extraction trial
- [ ] Use a disposable/staging environment and configure the OpenAI key privately.
- [ ] Keep Overture feed, scheduled processing and automatic publication disabled.
- [ ] Obtain explicit approval for a single known provider, its provider-owned website and source permission.
- [ ] Dispatch one candidate manually; record selected pages, exact source quote, extracted amount, model response and actual API cost.
- [ ] Have a reviewer check service, fee type, price basis, inclusions/exclusions, branch applicability and cited source.
- [ ] Verify public pending label before review and reviewer-verified label only after approval.
- [ ] Test robots denial, redirect, missing price, timeout, malformed model output and permission revocation/removal.

### P3 — Accuracy, rights and cost sign-off
- [ ] Build a human-labelled sample and measure precision/recall by price type.
- [ ] Prevent conflation of package prices, professional fees, disbursements, cremation and burial fees.
- [ ] Decide VAT, optional extras, local authority charges, branch applicability and effective/expiry-date semantics.
- [ ] Obtain source terms, copyright/database-rights, data-protection, retention and permitted-purpose review.
- [ ] Set per-provider and monthly API budgets, rate limits, alerts and a stop mechanism.
- [ ] Define stale-price expiry, change detection and reviewer re-extraction procedures.

### P4 — Limited pilot and operational monitoring
- [ ] Pilot only with an explicitly approved small provider cohort.
- [ ] Compare extraction with manual source checks and, where practical, provider confirmation.
- [ ] Monitor coverage, blocked/no-price/failure rates, reviewer corrections/rejections, duplicates and cost.
- [ ] Add scheduled refresh only after P2/P3 acceptance and separate operational approval.
- [ ] Expand gradually; reviewer approval remains the only route to the verified label.

### P5 — Production/release readiness
- [ ] Implement least-privilege roles/RBAC, credential lifecycle and target-environment security review.
- [ ] Complete backup/restore, retention, monitoring, alerting, failure-recovery and incident runbooks.
- [ ] Complete the 256 coordinate-conflict record/group audit and representative duplicate review.
- [ ] Rehearse target-host packaging, migration, backup and rollback/forward-fix plan.
- [ ] Record product, legal, security and operational sign-off against exact source commit and artifact hash.
- [ ] Only then request PR readiness/merge, deployment and any feature-flag changes.

## 8. Known limitations

- Price extraction currently targets explicit GBP amounts in bounded same-host HTML; PDF/image-only price lists and third-party pages are not covered.
- Page discovery may miss price lists behind unsupported navigation patterns.
- No price is inferred when none is explicitly found.
- A candidate without a verified provider-owned website and approved source permission cannot use this extraction path.
- AI confidence is not a calibrated probability.
- Reviewer verification checks a cited source at a point in time; it does not guarantee current price or provider confirmation.
- Reviewer credentials currently provide a shared reviewer-level permission, not role separation or full RBAC.
- Membership/regulatory evidence is a separate reviewer-entry foundation; automated NAFD/SAIF/FCA checks are not complete.
- CI does not prove production infrastructure, persistent database compatibility, live upstream permissions, real-model accuracy or operational resilience.

## 9. Operational handover rules

- Keep PR #1 draft/unmerged until remaining acceptance and sign-off are complete.
- Never commit API keys, reviewer tokens, local `.env`, database dumps or local datasets.
- Preserve Overture provenance and ambiguous records; no automatic merge/delete/coordinate overwrite.
- Do not run live enrichment or publication against the existing local database without a separately approved bounded plan.
- Inspect Git status, effective configuration, database revision and verified backup before any workload replacement.
- Preserve persistent volumes; never run `docker compose down -v` against the existing project.
- The local inspection commands below are read-only:

```bash
git status --short
git branch --show-current
git log -5 --oneline

docker compose -f platform/docker-compose.yml -f platform/.stage1-api-override.yml ps
docker compose -f platform/docker-compose.yml -f platform/.stage1-api-override.yml exec -T api alembic current
```

For the local sync procedure and effective API/worker setting assertions, use the P1.5 commands in the handover-only follow-up commit `b03cc4240fda973e4a58c7e5da30e357e48c3a0c`. Do not dispatch the enrichment endpoint or enable a feature flag during that check.
