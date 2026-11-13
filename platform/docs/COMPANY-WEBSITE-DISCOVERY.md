# Company-linked website discovery and automatic approval (v2.6.1)

## Purpose
Find likely official provider websites for the Companies House candidate set, verify them and automatically approve/publish only those that pass the deterministic high-confidence gate. Ambiguous or incomplete cases are routed to an administrator exception queue.

## Scope
- Active Companies House candidates with completed profile enrichment and classification `likely_funeral_director` or `uncertain`.
- England-wide candidate pool, processed in batches of 25.
- One targeted search per company; up to three result leads retained and the top two are technically checked.
- Automatic continuation queues the next bounded batch. Search-provider errors pause the run for explicit resume.

## Evidence and safety
- Search results are linked to the Companies House candidate. Search rank/snippets alone never approve a provider.
- Only HTTPS URLs on standard port are considered. Directory, social, council and aggregator domains are excluded from the initial pass.
- Verification uses `website_checks.verify_candidate`: DNS public-IP validation, HTTPS-only, robots.txt check, no redirect following, response-size limit and response-body discard after transient extraction.
- Persisted data is limited to search metadata, source URL/domain, title/snippet, verification result, content digest and selected factual identity/contact/address signals. Page bodies are discarded.
- Registered-office location may be used to disambiguate search; it is never promoted into an operating branch.
- The auto-approval gate requires explicit Schema.org `FuneralHome`, provider/company name alignment, complete UK street/locality/postcode, telephone, matching candidate and declared website domain, confidence threshold and no existing provider/branch collision.
- Passing candidates create and publish one provider and one branch, with an accepted source observation and audit events. Existing records are never overwritten or merged.
- Incomplete, conflicting, low-confidence, duplicate or ambiguous candidates enter `exception_review`. Generic `LocalBusiness` evidence does not auto-publish.
- Search snippets and extracted details still require source/licence/terms review before commercial reuse. robots.txt is a crawl instruction, not a copyright or database licence.

## Configuration
Set `SEARCH_PROVIDER=brave` and `BRAVE_SEARCH_API_KEY` in `.env`, then restart API and worker. Keys remain server-side. Automatic publication defaults on with `AUTO_APPROVE_PROVIDERS=true` and `AUTO_APPROVAL_MIN_CONFIDENCE=0.94`; set the switch to false to pause publication while continuing discovery and evidence collection.

## Operations
Admin endpoints: `/api/v1/company-websites/status`, `/runs`, `/runs/{id}/resume`, and `/candidates`. Start discovery from the admin dashboard. A run automatically continues in batches while the provider is available; on provider/API failure it pauses and can be resumed.
