# Everguide v2.6.0 — Provider Verification and Branch Review

## Purpose

This milestone starts the controlled Thurrock verification pilot. It converts the completed ONS-boundary candidate-quality review into human-reviewable provider and branch registers with an evidence trail and a conservative decision gate.

## Included

- `google_analysis/verification_pilot/thurrock_verification_workbook.xlsx`
- Provider verification register: 9 suggested groups, including one group held for a location conflict
- Branch verification register: 13 funeral-director candidate observations
- Evidence log and decision log templates
- Reviewer guide and evidence standards
- Offline scripts to rebuild registers/workbook and validate proposed decisions
- Original candidate quality CSV, summary and pilot report for traceability

## Pilot findings carried forward

- 16 candidate observations reviewed.
- 13 funeral-director candidate observations fall inside the ONS Thurrock boundary.
- 12 rows are geographically eligible pending provider verification; Desmond Maguire Funeral Directors remains held because postcode `G73 2AW` conflicts with the Thurrock point location.
- 3 adjacent-service observations remain excluded from the funeral-director category: memorial/masonry, celebrant and cemetery.
- Fenix Funeral has two addresses sharing phone/domain and requires an explicit branch relationship decision.
- Todd Funeral Services has two possible same-branch observations with coordinate variance and requires duplicate/address review.
- West & Coe and Co-op Funeralcare each have multiple candidate addresses; each address must be verified separately.

## Safety and scope

- No new Alembic migration.
- No production database access from pilot scripts.
- No providers or branches created, merged, deleted or published.
- No Google Places business details used.
- Source licence/terms must be cleared before operational reuse or publication of Overture-derived data.
- The workbook's initial decisions are pending/not checked. No candidate is pre-approved.

## Validation

- Register generation: 16 input rows, 9 provider groups, 13 branch candidate rows.
- Workbook generation completed.
- Validator smoke test correctly reports `NO_VERIFICATION_DECISIONS` for untouched templates.
- Full API suite not rerun; application changes are limited to version metadata and admin release label, with no API/model/migration changes.
