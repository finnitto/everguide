# Overture discovery and automatic approval

## Operating rule

Overture Places is a first-class discovery source, not proof that a place is a funeral director or that its branch details are correct. Overture `confidence` is retained as provenance and is **not** used as an approval probability or as a substitute for field verification.

The Overture approval ruleset (`overture-auto-approval-v1.0`) automatically approves a record only when all of these conditions pass:

1. The record is classified as a funeral-director candidate; adjacent services such as memorial masons, celebrants and cemeteries are excluded.
2. Its postcode is valid and in the configured Thurrock postcode area, and its point has been confirmed inside the official ONS Thurrock boundary.
3. No unresolved duplicate, parent/branch or existing-provider conflict exists. Separate branches at different addresses are assessed independently.
4. Every upstream contributor in `sources[]` has a recorded, recognised licence. Source names, contributor record IDs, licence strings, dataset versions and retrieval dates must be retained with the observation. The Overture umbrella licence must not be assumed to override contributor-specific terms.
5. A reachable first-party HTTPS website is independently checked, robots permission is confirmed, and the website explicitly confirms funeral-director services.
6. The first-party website confirms a complete branch address, the same postcode and the same telephone number as the candidate.
7. First-party evidence confidence meets the configured assessment threshold (default 0.94), and there is no conflicting identity or branch evidence.
8. Automatic approval is enabled.

When any condition is unresolved, the record remains in automated enrichment or is sent to the exception queue. It is not published simply because Overture confidence is high. No lower-confidence source observation may overwrite a verified field. Directory and price publication remain separate controls.

## Assess the supplied Thurrock dataset

From the project root:

```powershell
python google_analysis/assess_overture_auto_approval.py `
  --input google_analysis/overture_candidates.csv `
  --out google_analysis/overture_auto_approval_assessment
```

The tool writes CSV and JSON assessment reports. It does not modify the production database or publish records. Because the supplied snapshot does not include independent website-verification evidence or a locally available official boundary confirmation file, the current assessment deliberately approves zero records. The report shows which candidates need enrichment and which are exceptions/exclusions.

To evaluate completed evidence, provide a JSON object keyed by GERS ID using `--evidence`. Each value must contain `source_type: first_party_website`, `reachable`, `robots_allowed`, `explicit_funeral_director_service`, `website_url`, `complete_branch_address`, `postcode`, `telephone`, and `confidence`. The boundary-confirmed GERS IDs can be supplied as a newline-delimited text file using `--boundary-confirmed-ids`. The evidence file must be produced by a genuine verification run; do not manually assert checks that have not occurred.

Example evidence shape (illustrative only; not a real verification result):

```json
{
  "example-gers-id": {
    "source_type": "first_party_website",
    "reachable": true,
    "robots_allowed": true,
    "explicit_funeral_director_service": true,
    "website_url": "https://example.invalid",
    "complete_branch_address": true,
    "postcode": "RM17 5LS",
    "telephone": "01375 555000",
    "confidence": 0.97
  }
}
```

## Current integration boundary

This release adds the deterministic Overture approval ruleset, regression tests and a reproducible Thurrock assessment tool. It does **not yet** connect the Overture evidence assessment to the production database publication transaction or schedule Overture source ingestion. Until that integration is completed and tested, `auto_approved_eligible` in a report is an eligibility decision, not a live published provider. The current supplied snapshot has no independently verified eligible records, so no live provider or branch is created by this release.

This distinction is deliberate: an offline candidate list must never be mistaken for completed verification or production publication.
