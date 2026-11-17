# Automatic provider verification and approval

## Operating principle

Everguide is automation-first. Discovery, enrichment, matching, verification and publication are separate stages. Records that satisfy the configured deterministic rules are automatically approved and published. Administrators work an exception queue; they are not expected to approve every ordinary provider or branch.

This is the first deliberately high-precision automatic approval pathway. It is not intended to approve every funeral director discovered by the system. Coverage expands as additional reliable, lawful evidence pathways and tests are implemented.

## Current automatic approval pathway (ruleset `provider-auto-approval-v1.1`)

A candidate is automatically approved only when all of the following hold:

1. Automatic approval is enabled (`AUTO_APPROVE_PROVIDERS`, default `true`).
2. The candidate page is HTTPS, publicly reachable, robots.txt permits the fetch, returns HTTP 2xx and HTML, and passes the existing public-host, redirect and response-size safeguards.
3. The fetched page contains explicit Schema.org `FuneralHome` structured data. Generic `LocalBusiness`, `Organization` or `ProfessionalService` data is not sufficient for automatic publication.
4. The page itself contains explicit funeral-sector language and is not classified as a directory, comparison site, cemetery, crematorium, council or adjacent service.
5. The structured data supplies a non-generic provider name, complete UK street address and locality, syntactically valid UK postcode, and telephone number.
6. The structured website URL matches the discovered candidate's website domain.
7. The structured provider name has a meaningful token relationship with the linked Companies House candidate name; legal suffixes and generic funeral-sector terms do not count as identity evidence.
8. Extracted confidence meets `AUTO_APPROVAL_MIN_CONFIDENCE` (default `0.94`).
9. No existing provider has the same normalized name or website domain, and no existing branch has the same postcode or normalized telephone number.

When all checks pass, the system creates one published provider and one published branch, stores a linked accepted source observation, records the verification result and emits audit events for the provider, branch and candidate. The page body is discarded; only selected structured facts and a SHA-256 content digest are retained. Existing providers and branches are never overwritten, merged or deleted by this pathway.

## Exception handling

Any failed, incomplete, conflicting or ambiguous check prevents automatic publication. Positive but non-qualifying evidence is routed to `exception_review` with machine-readable reasons. Candidates without sufficient provider identity evidence are marked `reassessed_not_eligible`. Technical failures and robots restrictions remain non-approval outcomes. The admin candidate list and discovery summary expose these outcomes and the automatic-approval settings/counts.

Typical exceptions include:

- Generic structured-data types rather than explicit `FuneralHome`.
- Missing street, locality, valid postcode or telephone.
- Candidate and structured-data website domain mismatch.
- Existing provider/branch collision or possible duplicate.
- Low confidence or an explicit non-funeral/adjacent-service signal.
- Blocked, redirected, inaccessible or non-HTML pages.

Administrators may resolve exceptions with evidence and an auditable decision. Manual intervention is not the default approval route.

## Configuration

```dotenv
AUTO_APPROVE_PROVIDERS=true
AUTO_APPROVAL_MIN_CONFIDENCE=0.94
```

Set `AUTO_APPROVE_PROVIDERS=false` to pause automatic creation/publication without disabling discovery or evidence collection. The threshold is configurable; lowering it increases coverage but weakens the precision guardrail and should only follow measured validation.

## Independent verification statuses

Directory verification/publication, professional membership and accreditation (NAFD, SAIF, SAIFCharter), FCA regulatory status and pricing verification/publication are separate decisions. Automatic directory approval does not imply membership, statutory authorisation, FCA status or price approval.

## Source permission and legal safeguards

robots.txt is a crawler instruction, not a licence or permission to reuse information. This pathway is limited to first-party provider website structured facts and discards page bodies, but those technical safeguards do not establish legal permission, accuracy or compliance with website terms, database rights, privacy law or data protection obligations. Source terms and legal basis must be reviewed before commercial rollout. If a source's permitted use is unclear or restrictive, treat it as an exception and do not publish from it.

Google Places business details are not used as the content source for this pathway. Google Place IDs may be retained as references subject to the applicable Google terms. Overture-derived Thurrock observations remain outside automatic publication until the applicable upstream licence and source-level rights are confirmed.

## Audit and maintenance

Each automatic approval records the ruleset version, confidence and threshold, source URL, verification ID, source-observation ID, provider/branch IDs, UTC timestamps and responsible system actor. Scheduled revalidation must not overwrite higher-confidence verified facts with lower-confidence observations. Changes that fail the rules are routed to exceptions; historical observations and prior decisions remain available.
