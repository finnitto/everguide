# Thurrock Provider Verification Pilot

This is the Thurrock **exception-review and source-permission** pack for Everguide v2.6.1. Everguide's normal operating model is automation-first: high-confidence candidates from eligible first-party provider website evidence are automatically verified and published under `provider-auto-approval-v1.1`; administrators handle exceptions only.

The Overture-derived Thurrock observations are not currently eligible for that automatic path because their upstream licence and source-level permitted use have not been confirmed. This workbook therefore helps resolve source rights, address conflicts, branch ambiguity and other exceptions. It is intentionally separate from the production directory.

## Included files

- `thurrock_verification_workbook.xlsx` — formatted review workbook with Provider Review, Branch Review, Evidence Log, Decision Log and Evidence Standards tabs.
- `provider_verification_register.csv` — one row per suggested provider group (including the group held for a postcode/location conflict).
- `branch_verification_register.csv` — one row per funeral-director candidate observation; source observations are preserved.
- `evidence_log.csv` — blank multi-evidence log template.
- `decision_log.csv` — blank decision history template.
- `candidate_quality_review.csv`, `source_quality_review_summary.json`, `source_pilot_report.md` — original quality-review outputs for reference.
- `build_registers.py`, `build_workbook.py` — reproducible register/workbook generation.
- `validate_review_registers.py` — completeness gate for proposed verified decisions.
- `export_workbook_to_csv.py` — exports edited workbook tabs back to the four CSV files used by the validator.
- `REVIEW_GUIDE.md` — reviewer procedure and acceptance criteria.

## Start here

1. Read `REVIEW_GUIDE.md` and the Evidence Standards tab.
2. Check the upstream Overture licence and source-level terms before retaining, operationally reusing or publishing source-derived information. The candidate CSV's licence note is not itself a grant of permission.
3. Open `thurrock_verification_workbook.xlsx` and work through Provider Review first, then Branch Review.
4. Add every item of evidence to Evidence Log and reference its `evidence_id` in the relevant review row. Preserve conflicting evidence rather than choosing silently.
5. Record every material outcome in Decision Log, with reviewer and UTC timestamp.
6. Save the workbook, then export its editable tabs to CSV:

```powershell
python google_analysis\verification_pilot\export_workbook_to_csv.py
```

7. Run:

```powershell
python google_analysis\verification_pilot\validate_review_registers.py
```

The validator blocks a provider marked `verified_ready_for_setup` unless the source licence, service activity, trading status, identity, official website and evidence references meet the required statuses. It blocks a branch marked `verified_operating_branch` unless the parent provider is verified, the branch is confirmed public-facing, address/postcode/identity evidence is complete and evidence references exist.

A successful validation is a completeness check only. It does not grant source permission or publish anything. For eligible first-party website candidates, the separate automated approval service creates/publishes records when every configured rule passes; this workbook remains an exception workflow.

## Rebuild from updated quality review output

```powershell
python google_analysis\verification_pilot\build_registers.py --input path\to\candidate_quality_review.csv --out google_analysis\verification_pilot
python google_analysis\verification_pilot\build_workbook.py
```

The scripts are offline. They do not contact providers, use Google Places, or access Everguide's database.
