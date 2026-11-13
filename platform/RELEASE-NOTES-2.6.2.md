# Everguide v2.6.2 - Overture evidence-led approval

## Included

- Overture first-class candidate assessment ruleset (`overture-auto-approval-v1.0`).
- Independent first-party evidence, source contributor licence, official boundary, identity and branch safeguards.
- Assessment CLI and generated Thurrock CSV/JSON assessment reports.
- Seven regression tests covering confidence-only rejection, successful evidence pass, adjacent-service exclusion, out-of-area postcode, unknown licence, duplicate conflict and missing boundary.

## Current Thurrock snapshot result

Sixteen records assessed: 10 awaiting enrichment, 3 exceptions and 3 excluded. Zero auto-approved. This is expected because the supplied snapshot does not include independent first-party verification evidence or official point-in-boundary confirmation. The Overture confidence score alone cannot approve records.

## Important integration limitation

This release implements the decision rules and assessment tooling, but does not yet connect Overture ingestion and approval to the production database publication transaction. A report outcome of `auto_approved_eligible` is not a live published record. No production records are created or changed by the assessment tool.

## Upgrade safety

- No database migration is included.
- No `.env`, database files, backups or Docker volumes are included.
- Extract over the existing project without replacing `.env`.
- Do not run `docker compose down -v`.
