# Everguide development handover

**Handover date:** 18 November 2026  
**Repository:** `finnitto/everguide`  
**Working branch:** `stage1-overture-identity-provenance`  
**Pull request:** [PR #1 – Overture-first evidence, reviewer security and release validation](https://github.com/finnitto/everguide/pull/1)  
**Current release identifier:** v2.8.0  
**Status:** Development and validation. PR remains draft and unmerged.

This document records the current implementation, verified local/CI state, decisions, remaining work and the controlled route to the next milestone. It distinguishes code that exists from capabilities that have not yet been exercised against live websites or real approved providers.

---

## 1. Product and data policy

Everguide is an England-only funeral-director directory. Overture Places is the sole initial source for funeral-director location discovery and for the Overture branch identity/address/coordinates.

Companies House and provider-owned websites are optional corroborating sources and conflict signals. An absence of Companies House linkage, a website or corroborating evidence must not by itself block an otherwise eligible Overture candidate. Sole traders and partnerships remain supported without a Companies House link.

The Overture-first approval ruleset is `overture-first-approval-v2.1`. The conventional funeral-director workflow excludes adjacent service types, while retaining distinct classifications for direct cremation providers, pet services and funeral-plan-only providers. Direct cremation is retained as a separate future funeral-services category, not treated as a conventional funeral-director branch.

Same-name/postcode identity collisions and material coordinate discrepancies are sent to review. The agreed 100-metre location threshold is a conservative review trigger, not proof that either coordinate is wrong. Source records are retained; no automatic merge, delete or coordinate overwrite is allowed.

**Provider approval, price extraction, price verification and public price display are separate states.** A provider being approved does not make its extracted price evidence verified. Price evidence approval does not change provider identity, branch data or publication status.

## 2. Implemented work

### 2.1 Overture-first discovery and approval

Implemented in the working branch:

- Overture GERS IDs, source release, contributor lineage and source-level licences are retained with candidate/source-observation records.
- Deterministic service classification excludes non-conventional service types from the funeral-director candidate path.
- Only other funeral-director candidates can create funeral-director duplicate signals.
- Material location conflicts are flagged where the identity signals match and coordinate separation exceeds 100 metres.
- Overture remains the source for published branch fields. Website and Companies House records are corroboration/conflict signals, not replacement sources.
- The publication write-boundary guard blocks automatic publication unless the runtime switch is enabled.
- Reviewer access is bearer-token gated. The reviewer credential is held as a hash in configuration, not in the repository.

### 2.2 Read-only v2.1 assessment of the local Overture backlog

The local database contained 7,769 Overture candidates. The full v2.1 reassessment was explicitly read-only and performed no website, Companies House or ONS network checks.

| Hypothetical v2.1 outcome | Candidates |
|---|---:|
| Eligible if automatic approval were enabled | 5,921 |
| Exception review | 300 |
| Awaiting enrichment | 136 |
| Excluded from conventional funeral-director workflow | 1,412 |
| **Total** | **7,769** |

All 7,769 cached points were inside the England boundary. The 300 exception-review candidates comprised 256 candidate records with coordinate-conflict flags and 44 candidate records with conservative possible-same-service duplicate flags. Those are candidate-record counts, not a count of independent conflict groups.

The 5,921 eligible figure is hypothetical only. It is not an approved/published provider count.

### 2.3 Evidence and pricing data foundation

The current database model includes separate `PricingEvidence` records linked to a provider and optionally a branch. Each price record supports service classification, fee type, amount/range, price basis, inclusions/exclusions, source URL, source permission link, retrieval timestamp, content hash, evidence excerpt and reviewer decision.

The current evidence API is reviewer-only. Pricing records can be captured, listed and approved/rejected independently from provider approval.

### 2.4 Approval-to-price-enrichment hand-off

Implemented in the branch:

- Automatic Overture publication marks the linked candidate for price enrichment.
- Manual provider approval marks every Overture candidate linked to that provider for price enrichment.
- An idempotent reviewer backfill marks existing approved/published funeral-director candidates.
- Candidate queue state is retained in `OvertureCandidate.first_party_evidence.pricing_enrichment`.
- The queue can be inspected using the Overture pricing-enrichment API.
- Task dispatch occurs only after the approval/queue transaction commits.

The queue is a separate work item. It does not itself create a price record or publish anything.

### 2.5 AI-assisted price extraction and transparent verification

The working branch now contains an AI-assisted price extraction task:

1. The candidate must already be linked to an approved/published funeral-director provider.
2. A verified provider-owned `website_url` must exist on its first-party evidence.
3. A reviewer-approved `SourcePermission` for the matching website domain is required before price-page retrieval.
4. HTTPS, public-address/SSRF, robots.txt, same-host and bounded-response checks are repeated at extraction time. Redirects are not followed automatically.
5. The worker searches a bounded number of same-host HTML pages, currently configurable with a default maximum of six.
6. Only contexts around explicit GBP amounts are sent to the AI extractor. The model is instructed to treat website text as untrusted, ignore embedded instructions, and extract only printed amounts. It must not estimate, infer, calculate or invent a price.
7. The AI response must provide an exact source quotation and source-page URL. The application checks that the quote appears in the fetched page and that the quoted GBP amount matches the structured amount. Items failing those checks are discarded.
8. Valid items are saved as `PricingEvidence` with `review_status=pending`, `extraction_method=ai_extracted` and `verification_status=unverified`. Source page URL, short quote, content hash, extraction model/response and Overture candidate provenance are retained.
9. An authenticated reviewer inspects the price and its source. Only an approval decision changes the price to `verified`. Rejected evidence is not shown publicly.
10. Public directory search returns verified prices and AI-extracted pending prices with distinct labels. Pending manual entries are not shown. If a linked source permission is later withdrawn, the price is hidden from public results.

The intended public labels are:

- **AI-extracted · Not verified** — automatically extracted from the cited provider-owned page; not yet checked by an Everguide reviewer.
- **Verified by Everguide reviewer** — a reviewer has checked the amount against the cited source and approved the evidence.

The public display also supplies the provider-source link and retrieval date, with a prompt to confirm the current price and any additional charges directly with the provider. “AI-extracted” is intentionally more accurate than “AI-generated”: the model is instructed to extract explicit published amounts, not create estimates.

### 2.6 Reviewer screens

The working branch includes a dedicated `/admin/pricing` page. It lets a reviewer:

- sign in with the reviewer bearer token;
- review pending AI-extracted prices and their source quotation, source URL, hash, model and candidate provenance;
- approve or reject each price;
- see candidates waiting for source approval;
- register a provider-owned HTTPS source for a provider;
- approve a source for factual price extraction, which releases matching candidates waiting on that permission.

The main admin dashboard links to the price review page.

## 3. Configuration and runtime safeguards

New configuration (defaults shown):

```dotenv
PRICE_ENRICHMENT_ENABLED=false
OPENAI_API_KEY=
PRICE_ENRICHMENT_MODEL=gpt-6-luna
PRICE_ENRICHMENT_MAX_PAGES=6
```

The OpenAI key must be supplied privately in the local/runtime `.env`; it must never be committed or included in a release archive. The model default is a configurable choice, not a commitment to keep using a fixed model indefinitely.

The following existing controls must remain false during development and validation:

```dotenv
AUTO_APPROVE_PROVIDERS=false
OVERTURE_AUTO_PROCESS=false
OVERTURE_FEED_ENABLED=false
OVERTURE_SCHEDULED_TASKS_ENABLED=false
PRICE_ENRICHMENT_ENABLED=false
```

A queue marker can exist while the feature flag is off. No AI extraction task is dispatched unless both `PRICE_ENRICHMENT_ENABLED=true` and `OPENAI_API_KEY` are configured. The reviewer endpoint to dispatch a bounded queue is also guarded by both settings.

**Do not enable these switches as part of ordinary code validation.** Do not run the price-enrichment queue, Overture processing or source checks against the existing local database until a separate controlled test is agreed.

## 4. Current environment, data and backups

The previously validated local development environment uses Docker Compose under `platform/docker-compose.yml` with a local API override at `platform/.stage1-api-override.yml`.

The local database had been migrated through Alembic revision `0023_stage3_evidence`. The existing migration upgrade was authorised and completed previously; the new price-enrichment change uses existing JSON/evidence structures and is not expected to require a database migration.

At the last recorded local snapshot:

- Overture candidates: 7,769
- Existing providers: 0
- Existing branches: 0
- Verified Overture-to-Companies House links: 0
- Source observations: 23,307
- Overture import runs: 6

The existing backup recorded for the local database is:

- File: `/c/everguide-backups/everguide-pre-v2.8.0-20261117-202550.dump`
- SHA-256: `a0feab156a12c70803fd29d7773f6e619e800cd49aceaa123b0ac492a7d28fa4`

The backup checksum was validated previously and a separate temporary restore test matched the source counts. Keep this backup and the current data volumes. Never use `docker compose down -v` on the existing project.

## 5. Validation evidence

Previously completed validation:

- Overture-first v2.1 offline reassessment completed read-only against all 7,769 candidates.
- GitHub Actions run #198 passed the v2.1 implementation test suite (190 passed) and isolated Docker validation.
- GitHub Actions run #216 passed the approval-to-price-queue hand-off tests (193 passed), frontend production build, release archive audit and isolated Docker integration.
- The isolated Docker job checked API readiness, migration downgrade/re-upgrade, reviewer route availability, disabled Beat schedule and an empty worker queue.

The AI price extraction, source-permission release path, public price display and new reviewer UI have been added after run #216. **They must not be treated as CI-validated until a new workflow run for the current branch head completes successfully.** No real OpenAI request or live provider website extraction has been performed as part of this implementation.

## 6. Next milestones

### Milestone P1 — Complete implementation and CI validation
- [ ] Run the full backend/frontend test suite against the latest branch head.
- [ ] Pass isolated Docker validation with price-enrichment and all Overture runtime switches disabled.
- [ ] Verify that the source-permission router is mounted and reviewer-protected.
- [ ] Verify automatic and manual provider approval queueing, backfill idempotency and source-approval release.
- [ ] Verify amount/quote validation rejects fabricated or mismatched values.
- [ ] Verify public API distinguishes pending AI extraction from reviewer-verified prices and hides withdrawn-source prices.
- [ ] Verify the reviewer UI approve/reject flow and the source approval screen.

### Milestone P2 — Controlled staging trial
- [ ] Configure the OpenAI API key privately in a disposable/staging environment.
- [ ] Keep all Overture publication/feed/schedule switches off.
- [ ] Keep AI price enrichment disabled until the staging candidate and provider website have been checked.
- [ ] Use a small, known approved candidate and a provider-owned site with a reviewer-approved source permission.
- [ ] Dispatch one candidate manually, inspect the pages selected, request/response cost, extracted quote and saved `PricingEvidence`.
- [ ] Confirm the public display shows `AI-extracted · Not verified` before reviewer approval.
- [ ] Approve/reject the evidence and confirm the public label changes correctly.
- [ ] Test a blocked robots.txt page, missing prices, revoked source permission, timeouts and malformed model output.

### Milestone P3 — Accuracy, rights and cost sign-off
- [ ] Build a human-labelled sample of published price lists and compare extraction precision/recall by price type.
- [ ] Check that package prices, professional fees, disbursements, cremation and burial items are not conflated.
- [ ] Decide how to handle VAT, optional extras, local authority fees, regional differences and prices that apply only to selected branches.
- [ ] Review source terms, copyright/database rights, data minimisation and retention policy for the intended provider-source use.
- [ ] Set a monthly API budget, per-provider usage ceiling, rate limits and alerts.
- [ ] Define how a reviewer requests re-extraction when a website changes and how stale prices are expired.

### Milestone P4 — Limited pilot and operational monitoring
- [ ] Pilot with a small, explicitly approved cohort of providers.
- [ ] Compare extracted prices with direct manual source checks and provider confirmation.
- [ ] Monitor failure/blocked/no-price rates, costs, duplicate evidence and correction/rejection rates.
- [ ] Add controlled scheduled revalidation only after the pilot and a separate operational sign-off.
- [ ] Expand the cohort gradually; retain reviewer verification as the only route to the “verified” label.

### Milestone P5 — Release and production readiness
- [ ] Finish role-based reviewer permissions, secret rotation, retention, backup/restore, rollback and monitoring runbooks.
- [ ] Complete the 256-record coordinate-conflict group audit.
- [ ] Complete target-host release packaging and migration/backup rehearsal.
- [ ] Obtain explicit approval for PR merge, deployment and any runtime-switch changes.

## 7. Known limitations and open decisions

- Price extraction currently supports explicit GBP amounts in bounded same-host HTML pages. PDF price lists, image-only documents, external third-party pages and prices without an explicit GBP amount are not covered.
- Page discovery uses the provider homepage and same-host links with price-related URL or anchor text. Some providers may keep their price list behind a navigation pattern this crawler will not discover.
- No price is inferred when none is found. A candidate can finish as `no_prices_found`, `needs_source`, `awaiting_permission`, `blocked` or `failed`.
- A candidate without a verified provider-owned website cannot have price information automatically extracted by this pathway.
- Source registration and reviewer approval are a prerequisite for price extraction. Robots.txt is only a crawler instruction and is not legal permission or a licence.
- The AI confidence value is not a calibrated probability and must not be presented as one.
- The current model call sets Responses API `store=false`; organisation-level data controls and retention terms still need to be checked before the API key is configured for real provider data.
- Automated retries are bounded. A reviewer-facing requeue/re-extraction flow, price history/difference detection and scheduled expiry/revalidation remain next-stage work.
- The public API currently exposes price rows on search results. A dedicated provider profile page and richer comparisons remain future UI work.

## 8. Operational handover rules

- Keep the PR as draft/unmerged until code, tests and product acceptance are complete.
- Never commit API keys, reviewer tokens, local `.env`, database dumps or local data.
- Do not publish or merge data records as part of code testing.
- Do not run the actual website/AI enrichment task against the existing local database without a separately authorised, bounded plan.
- Preserve all Overture source records. Do not merge, delete or overwrite ambiguous candidates or conflicting coordinates automatically.
- Do not enable automatic approval, Overture feed processing or scheduled tasks during development validation.
- Rebuild only the required application containers; preserve PostgreSQL and cache volumes.

Useful local commands (Git Bash, from `/c/projects/everguide`):

```bash
git status --short
git branch --show-current
git log -5 --oneline

docker compose -f platform/docker-compose.yml -f platform/.stage1-api-override.yml ps
docker compose -f platform/docker-compose.yml -f platform/.stage1-api-override.yml exec -T api alembic current
```

The commands above are inspection-only. Do not start a live enrichment task or enable feature flags as part of the handover inspection.
