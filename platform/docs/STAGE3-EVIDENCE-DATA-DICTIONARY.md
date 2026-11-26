# Stage 3 — Evidence data dictionary and operating boundary

**Status:** Initial implementation; source policy and automated retrieval are not signed off.  
**Migration:** `0023_stage3_evidence`  
**API:** reviewer-authenticated `/api/v1/evidence`

## Design rules

Pricing, association membership, regulatory status and provider legal form are separate facts. None of these records is an Overture identity source, an Overture branch-location replacement, or an instruction to publish a provider. Newly captured evidence starts as `pending`; a reviewer decision applies only to that evidence item.

The current API is reviewer-entry only. It does not scrape, search, call the NAFD/SAIF/FCA services, infer an association from a company name, or infer FCA applicability. External retrieval must not be enabled until the source, terms, permitted purpose, retention and refresh policy have been reviewed and accepted.

## Provider business form

`providers.business_form` supports:

- `limited_company`
- `llp`
- `partnership`
- `sole_trader`
- `other`
- `unknown` (default)

The field is descriptive provider metadata and is audited when changed. A sole trader or partnership does not need a Companies House candidate or Overture-to-Companies House link. The field does not create, imply or verify a legal-entity relationship. A linked Companies House candidate remains governed by the separate reviewer-verified provenance workflow.

## Evidence domains

| Domain | Table | Scope | Domain-specific fields |
|---|---|---|---|
| Pricing | `pricing_evidence` | Provider-wide or branch-specific | Service category/name, fee type, amount, optional upper amount, currency, fixed/from/range/estimate basis, inclusions, exclusions, applicability and effective dates |
| Membership | `membership_evidence` | Provider-wide or branch-specific | Scheme code (NAFD, SAIF, SAIFCharter or other), membership number/name, reported status, applicability and validity dates |
| Regulatory | `regulatory_evidence` | Provider-wide or branch-specific | Regulator code (FCA or other), reference number, permissions, reported status, applicability and validity dates |

Branch-specific records must reference a branch belonging to the selected provider. A null branch means the evidence is provider-wide; it does not assert that all branches have separately been checked.

## Shared evidence provenance

Each domain record stores:

- Source name and URL.
- A reviewer-entered source-rights basis; an optional `source_permission_id` must reference an approved permission for the same provider.
- Source retrieval timestamp.
- SHA-256 digest of the evidence artefact or retained extract.
- Optional bounded text excerpt and structured extraction payload.
- Effective-from/effective-to dates and an explicit expiry timestamp.
- Review status, reviewer ID, review timestamp and notes.
- Last checked timestamp and normal created/updated timestamps.

Raw page bodies are not requested or stored by these endpoints. Operators must retain only evidence permitted by the recorded source-rights basis and the approved retention policy.

## Status semantics

Evidence review status is separate from the domain's reported status:

- `pending`: captured and awaiting human review.
- `approved`: reviewer accepts this particular evidence item.
- `rejected`: reviewer rejects this item.
- `requires_update`: reviewer requires clarification or refreshed evidence.

Membership and regulatory records separately store `reported_status` and `applicability_status`. An unknown or not-applicable result is not converted into an inactive membership or negative regulator decision. A reported register status is not accepted evidence until a reviewer approves the record.

Pricing `approved` means the recorded price line and supporting evidence were reviewed. It does not assert that the price applies to every branch or funeral arrangement; use branch scope and the `applicability` payload.

## Revalidation request ledger

A reviewer can create an idempotent revalidation request against one evidence item. Request and attempt records preserve:

- Caller-supplied idempotency keys.
- Evidence domain and evidence record identity.
- Requesting/reviewing actor.
- Request status, attempt count and maximum attempts (hard-limited to four).
- Attempt outcome, check timestamp, source URL, evidence digest and failure class.
- Retry dates after transient failures (2, 7 and 21 days).
- Completion or bounded retry-exhaustion state.

A transient retrieval failure changes only the revalidation request state. It does not change the underlying evidence's reported membership/regulatory status or its review decision. A successful check is recorded as an attempt; refreshed domain evidence must be captured as a new evidence record and reviewed separately.

The current revalidation API is deliberately manual. It records reviewer-performed attempts; it does not execute a scheduled fetch or automatically perform retries. The persistent request ledger allows a later, separately approved worker to resume due requests without re-creating them.

## API outline

- `GET /api/v1/evidence/summary`
- `GET|POST /api/v1/evidence/pricing`
- `POST /api/v1/evidence/pricing/{id}/decision`
- `GET|POST /api/v1/evidence/membership`
- `POST /api/v1/evidence/membership/{id}/decision`
- `GET|POST /api/v1/evidence/regulatory`
- `POST /api/v1/evidence/regulatory/{id}/decision`
- `PATCH /api/v1/evidence/providers/{id}/business-form`
- `GET|POST /api/v1/evidence/revalidation-requests`
- `POST /api/v1/evidence/revalidation-requests/{id}/attempts`

Every route requires a configured reviewer bearer credential. Authenticated reviewer IDs, not caller-supplied identity strings, are recorded as actors.

## Remaining Stage 3 acceptance

1. Review and sign off source-specific rights, access, purpose, retention and refresh policies for each evidence domain.
2. Agree a canonical pricing taxonomy, fee breakdown, VAT/tax treatment, package inclusions and branch applicability.
3. Agree which NAFD/SAIF membership checks and FCA checks apply, including positive and negative result semantics.
4. Implement source-specific, permission-aware retrieval workers only after the above policy decisions.
5. Add worker locking, due-request selection, resume/retry handling, rate limits and failure-injection tests.
6. Add full lifecycle tests for stale, missing, conflicting and expired evidence, and product acceptance of representative branch scenarios.
