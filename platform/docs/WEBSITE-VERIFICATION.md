# Website candidate verification (v0.8.0)

Everguide can run a bounded technical check on up to 50 likely provider candidates per batch. The check:

- accepts HTTPS URLs only and rejects embedded credentials, localhost/internal names and hostnames resolving to non-public IP addresses;
- checks `robots.txt` for the exact candidate URL using the EverguideEvidenceBot user agent before requesting the page;
- does not follow HTTP redirects automatically; redirect destinations are surfaced for a later independently checked pass;
- limits response bodies to 1 MB and request timeouts to 12 seconds;
- retains only status, final/candidate URL, HTTP status, content type, page title, robots decision, SHA-256 digest and a short diagnostic; response bodies are discarded;
- does not extract contact details, branch facts or prices, and does not alter provider records.

A `reachable` result confirms only technical reachability and robots permission for the checked URL at that time. It does not establish that a site is owned by the named funeral director, that its content is accurate, or that Everguide has permission to reuse or publish it. `robots.txt` is a crawl instruction, not a licence or legal permission. A human review and appropriate legal/source-rights assessment remain necessary before facts are approved for publication.

Use **Verify provider websites (up to 50)** in Admin. Re-run after new discovery results arrive. Batches include never-checked candidates and candidates previously checked by earlier releases so the current identity-extraction rules can reassess the backlog. Candidates that remain ineligible are marked reassessed and are not repeatedly selected; possible duplicates remain held. Reassessment is bounded to 50 candidates per batch.
