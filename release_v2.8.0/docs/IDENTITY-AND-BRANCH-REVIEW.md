# Website identity and branch review (v2.4.0)

## Purpose

Convert existing company-linked website leads into reviewable identity suggestions and branch-address proposals without creating directory records.

## Identity consolidation

`POST /api/v1/identity-review/prepare` groups leads by Companies House candidate and collapses repeated leads by canonical domain for the review summary. Original `company_website_candidates` rows, source URLs and verification attempts remain unchanged. The highest-confidence lead supplies the suggested identity; this is a proposal, not a verified trading identity.

## Branch proposals

A branch proposal is created only when the extracted website evidence explicitly includes `has_complete_branch_address` and non-empty street, town and postcode values. The registered office is never used as branch evidence. These proposals are not `branches` rows and cannot appear in public listings.

## Review statuses

- `pending`
- `accepted_for_provider_setup`
- `rejected`
- `needs_more_evidence`

Accepting a proposal only records a review decision. It does not create a provider or branch. Every decision is audited.

## API

- `GET /api/v1/identity-review/summary`
- `POST /api/v1/identity-review/prepare` (idempotent)
- `GET /api/v1/identity-review/identities?status=pending&limit=50`
- `GET /api/v1/identity-review/branches?status=pending&limit=50`
- `PATCH /api/v1/identity-review/identities/{id}`
- `PATCH /api/v1/identity-review/branches/{id}`

The admin API remains a development-only surface and must not be exposed publicly without authentication and role-based authorization. Website evidence is subject to source terms, database rights, privacy and retention review.
