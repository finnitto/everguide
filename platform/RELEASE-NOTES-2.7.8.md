# Everguide 2.7.8 — Website discovery provenance and evidence repair

## What changed

- Preserves the original Overture website as a distinct discovery lead; discovered alternatives are recorded separately and never overwrite the source record.
- Expands rejection of obvious third-party sources as provider-owned website candidates, including social networks, public company registers, news and notice pages, job/careers pages, directories and document URLs.
- Records each attempted website with its URL, discovery source, search query (where applicable), technical verification status, final URL, page title, content digest, robots result and any extracted structured identity fields.
- Persists selected structured identity evidence (business name, address components, postcode, telephone, email, schema type, service signals and confidence) for review. Full page bodies remain discarded.
- Retains mismatched search results as audit evidence only; they are not promoted as the candidate's official website. A mismatched original Overture website remains explicitly reason-coded for human review.
- Clarifies that technical reachability alone is not business identity verification.
- Adds regression tests for third-party URL filtering, mismatched search-result provenance and original Overture identity mismatches.

## Approval and safety

- No automatic approval threshold or publication gate has been relaxed.
- Name, postcode and telephone identity matching remains strict for first-party website acceptance.
- Automatic approval remains disabled by default; existing deployment settings are not changed by this release.
- No database migration is required; additional evidence is stored in the existing JSON evidence field.
- No imports, enrichment jobs, publication actions or production database operations were run while building this archive.

## Validation status

- Python `compileall`: passed.
- Three regression tests added but not executed in this build container because `celery`, `redis` and `psycopg` are unavailable and package installation was blocked by network restrictions.
- Full API test suite, frontend build and Docker build: not run in this build container.
- The 121 API tests previously reported for v2.7.7 do not constitute validation of v2.7.8. Run the full suite in the project's dependency environment before deployment.

## Recommended validation sequence

1. Run the full API suite in the existing project virtual environment.
2. Review the new `website_discovery_attempts` and `extracted_identity_evidence` fields on synthetic test candidates.
3. Reassess a small, manually selected sample of existing Overture candidates in a non-production database, without publication.
4. Compare URL provenance, official-site match rate, branch identity evidence and reason-code distribution against the v2.7.7 baseline.
5. Only after sign-off, consider a controlled re-enrichment run with automatic approval and scheduled ingestion still disabled.
