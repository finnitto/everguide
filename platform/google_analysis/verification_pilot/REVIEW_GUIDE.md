# Reviewer guide — Thurrock exception pilot

## Objective

This is an exception workflow, not a manual approval queue for every discovered provider. Everguide automatically approves and publishes eligible high-confidence first-party website candidates. Use this workbook only to resolve the Overture source permission question and candidate-specific ambiguities that cannot safely pass automatic rules.

Establish, with dated and traceable evidence, whether each candidate represents:

1. a real provider that currently offers funeral-director services;
2. a trading provider whose identity is understood (legal entity, trading name and any parent/group relationship); and
3. one or more genuine public-facing operating branches in Thurrock.

Do not infer one of these facts from another. A provider can be real while an individual address is not a branch. A branch may exist while its candidate source record has a wrong postcode or coordinate.

## Review order

### A. Source permission gate

- Identify the upstream Overture release and the exact applicable licence/terms for the source fields used.
- Inspect the upstream `sources_json`/source attribution metadata if available.
- Record the licence text/URL, access date, reviewer and decision in Evidence Log.
- Until permission is clear, keep source-derived information in the restricted internal review context only. Do not publish it or use it to seed operational records.

### B. Provider verification

For each `provider_group_id`:

- Confirm the official website belongs to the provider, rather than a directory, unrelated group or redirect destination.
- Confirm the business explicitly provides funeral-director/funeral-arranging services. Do not treat celebrants, cemeteries, memorial/masonry services or general family-service taxonomy as funeral-director proof.
- Confirm the business appears to be trading now. Companies House active status, a live domain, source confidence and a search result snippet are not sufficient individually.
- Establish the relationship between the trading name and any registered legal entity or parent group. Shared website domain alone does not prove that two trading names are the same provider.
- Record evidence URLs, dates, exact claim supported and limitations. Prefer the provider's own pages and direct confirmation.

### C. Branch verification

For every candidate address independently:

- Establish that it is a public-facing funeral home/branch where families can contact or visit the provider, not merely a registered office, mailing address, storage site, private residence or cemetery.
- Confirm the complete address and postcode using an official branch page and an appropriate address/postcode reference.
- Confirm the branch is linked to the provider under review.
- Confirm telephone details from an official source or by direct call; record the date and result. Do not assume a provider-wide number is branch-specific.
- Treat coordinates as corroborative only. Point-in-polygon does not prove that a business operates at that point.
- Keep multiple genuine branches separate. Do not merge branches because the name, phone or domain is shared.

## Candidate-specific flags requiring explicit resolution

- **Fenix Funeral (PG003):** two postcodes/addresses share the same phone and website domain. Establish whether they are two operating branches, one branch plus an obsolete address, or an address relationship needing correction.
- **Todd Funeral Services (PG008):** two observations share name, postcode and normalized phone but coordinates differ by more than 250m. Determine the correct branch point/address and whether one is a duplicate observation. Do not delete either observation until reviewed.
- **Desmond Maguire Funeral Directors (PG005):** the point is inside Thurrock but postcode `G73 2AW` is outside the expected area. This group is held for manual location review and must not be treated as Thurrock-eligible until the conflict is resolved.
- **West & Coe (PG002):** two candidate addresses. Verify each independently as a branch.
- **Co-op Funeralcare (PG004):** two candidate addresses. Verify each independently as a branch.
- **D J Cotton & Sons:** the candidate has an `SS17` postcode. Its point is inside the ONS Thurrock boundary, but verify the full address and whether the location is a public-facing branch.

## Decision definitions

### Provider decision

- `pending` — not yet assessed.
- `verified_ready_for_setup` — provider identity, current trading, funeral-director activity, official website and operational source permission are all supported. This only makes the provider eligible for a separately authorised setup step.
- `needs_more_evidence` — evidence is incomplete, stale or conflicting.
- `reject_not_funeral_director` — evidence shows an adjacent service or unrelated business.
- `reject_not_trading` — evidence supports ceased/non-operating status.
- `exclude_source_licence` — source rights do not permit the intended use.

### Branch decision

- `pending` — not yet assessed.
- `verified_operating_branch` — public-facing branch and address relationship are confirmed, and parent provider is verified.
- `needs_more_evidence` — branch existence/address/relationship is unclear.
- `reject_not_operating_branch` — address is not a public-facing funeral-director branch.
- `duplicate_observation` — two source observations refer to the same physical branch; retain provenance and record the canonical observation rather than deleting history.
- `address_conflict` — postcode/address/coordinate evidence conflicts and requires correction or exclusion.

## Evidence and audit requirements

Every decision must include reviewer, UTC date/time, rationale and one or more evidence-log references. Each evidence item should record its URL/source, date accessed, the specific claim it supports, a short factual summary, strength and any limitations. Keep contradictory evidence visible. Do not record sensitive personal information from calls or website pages unless there is a clear lawful need.

## Publication and data handling

This is an exception review exercise, not permission to publish Overture-derived details. Check upstream licence and source terms first. Do not use Google Places business details as a substitute source for this register. Do not write candidate records to Everguide's production database or publish directory entries as part of this pilot. The separate first-party website approval pipeline automatically publishes only records that pass all configured rules; unresolved source rights and ambiguous cases remain exceptions.
