# Provider quality guardrails (v1.4.0)

## Publication policy

Automatic provider publication is disabled by default (`AUTO_APPROVE_PROVIDERS=false`). Website candidates that produce extractable identity evidence are retained in `held_quality_review`; they are not discarded and no provider/branch record is created automatically while the gate is off.

Do not enable automatic publication until a sample of held candidates has been checked and the false-positive rate is acceptable. If enabled later, the stricter extractor still requires explicit funeral-sector language on the fetched page plus independent contact or complete UK address evidence. Structured data alone is insufficient.

## Existing records

Migration `0010_provider_quality` adds `providers.quality_status`. Existing providers are retained. Obvious generic names and websites indicating directories, cemeteries, crematoria or councils are flagged `needs_review`; all other pre-existing rows remain `unassessed` until evaluated. This flag does not delete, merge, suspend or unpublish a provider.

## Branch geography

Missing county and postcode values are reported separately. County is not inferred from town names. Populate it only from a reliable postcode/address reference and retain the lookup source and date in evidence/audit records.

## Review signals

A flagged record is a prompt for source review, not a definitive finding. A council may operate a separate funeral business; a cemetery operator may also provide funeral-director services. Confirm the actual service and legal/trading entity before changing records.
