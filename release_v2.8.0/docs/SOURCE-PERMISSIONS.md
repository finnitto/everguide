# Source research and reuse policy — v0.5.2

## Operating principle
Everguide is designed to independently identify funeral directors and research their own public-facing websites. It does not require an individual written permission record from every provider merely to identify the provider or register its official website for technical screening.

This is not blanket permission to copy, retain or republish website content. Public accessibility and robots.txt are not licences. Each collection and use must respect applicable website terms, technical access controls, copyright, database rights, privacy and data-protection obligations.

## Source classes
- **Provider-owned website:** eligible for automatic technical screening. Factual business information may be considered for extraction only under the source-use policy and applicable law.
- **Restricted / uncertain source:** pause collection beyond the minimum technical checks and send for policy review.
- **Blocked source:** do not fetch or reuse.
- **Third-party curated directory:** do not bulk ingest or reproduce without an appropriate licence or other confirmed legal basis. SAIF and NAFD directory datasets remain excluded pending permission/licensing.

## Automation safeguards
- HTTPS only; reject URLs with embedded credentials.
- Check robots.txt as a crawler instruction, not as legal permission.
- Use identifiable, rate-limited requests, timeouts and response-size limits.
- Do not bypass authentication, paywalls, CAPTCHAs or technical controls.
- Record source URL, check time, status and evidence provenance.
- Do not copy photographs, logos, marketing prose or articles absent appropriate rights.
- Treat personal contact information under applicable data-protection requirements.
- Keep source evidence separate from approved provider/branch records.
- Do not auto-merge or publish uncertain records.

## Current release boundary
v0.5.2 updates registration and admin policy language and removes the mandatory individual source-use-basis field. The existing worker remains a metadata-only technical checker; it does not yet extract business facts or automatically enrich the 776 Google Place ID observations. Those are subsequent implementation stages requiring source-specific policy controls.
