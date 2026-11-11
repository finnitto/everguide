# Company-linked website discovery (v2.3.0)

## Purpose
Find likely official website leads for the existing Companies House candidate set. This is an evidence-gathering stage, not provider approval or branch publication.

## Scope
- Active Companies House candidates with completed profile enrichment and classification `likely_funeral_director` or `uncertain`.
- England-wide candidate pool, processed in batches of 25.
- One targeted search per company; up to three result leads retained and the top two are technically checked.
- Automatic continuation queues the next bounded batch. Search-provider errors pause the run for explicit resume.

## Evidence and safety
- Search results are leads only and are linked to the Companies House candidate.
- Only HTTPS URLs on standard port are considered. Directory, social, council and aggregator domains are excluded from the initial pass.
- Verification uses `website_checks.verify_candidate`: DNS public-IP validation, HTTPS-only, robots.txt check, no redirect following, response-size limit and response-body discard after transient extraction.
- Persisted data is limited to search metadata, source URL/domain, title/snippet, verification result, content digest and extracted factual identity/contact/address signals.
- Registered-office location may be used to disambiguate search; it is never promoted into an operating branch.
- Search snippets and extracted details remain candidate evidence and require source/licence/terms review before commercial reuse. robots.txt is a crawl instruction, not a copyright or database licence.

## Non-publication invariant
This pipeline does not create or modify Provider, Branch, SourceObservation approval, pricing or public directory records. Every result remains a candidate for human review.

## Configuration
Set `SEARCH_PROVIDER=brave` and `BRAVE_SEARCH_API_KEY` in `.env`, then restart API and worker. Keys remain server-side.

## Operations
Admin endpoints: `/api/v1/company-websites/status`, `/runs`, `/runs/{id}/resume`, and `/candidates`. Start discovery from the admin dashboard. A run automatically continues in batches while the provider is available; on provider/API failure it pauses and can be resumed.
