# Superseded Everguide v2.8.0 release snapshot

**Do not install or distribute this directory as the current release.**

This checked-in package snapshot predates the current Overture-first approval
policy and does not include the complete current implementation or migration
chain. It is retained for historical comparison only.

The authoritative working source is the `platform/` directory on branch
`stage1-overture-identity-provenance`, currently reviewed at commit
`0958c66a2ec6b6b387accde2b802f84ec927faf1`.

Overture Places is the sole initial discovery source and the authoritative source
for published branch identity/location fields. Companies House and official
provider websites are optional corroboration and material-conflict signals, not
mandatory approval gates. Direct Overture-first publication does not require a
Companies House link.

Current migrations are `0021_overture_company_links` and
`0022_branch_overture_provenance`. Migration 0022 concerns optional provenance
on website-derived branch proposals, not a prerequisite for direct Overture
publication.

See `platform/README.md`,
`platform/docs/OVERTURE-AUTOMATIC-APPROVAL.md` and
`platform/docs/VALIDATION.md` for maintained source and safeguards.
Automatic approval, post-import processing and scheduled Overture tasks remain
disabled by default.
