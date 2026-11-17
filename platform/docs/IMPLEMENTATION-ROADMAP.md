# Everguide implementation roadmap

## Release 0.1.0 – Development foundation
- [x] Next.js application scaffold
- [x] FastAPI service scaffold
- [x] PostgreSQL/PostGIS container
- [x] SQLAlchemy/Alembic foundation
- [x] Redis/Celery worker scaffold
- [x] Docker Compose
- [x] Local deployment and packaging scripts
- [x] Basic API tests and health checks

## Release 0.2.0 – Core provider directory (implemented)
- [x] Parent provider and branch entities
- [x] Branch contact details, service fields and coordinates
- [x] Source observations with attribution, retrieval time and confidence
- [x] Audit events for provider and evidence actions
- [x] Versioned database migration
- [x] Provider CRUD, status management and directory search API
- [x] Local admin provider creation and review-status controls
- [x] Public search limited to published providers and branches
- [x] API smoke tests for core directory workflows

## Subsequent releases
- Public directory search and profiles
- Admin authentication and role-based access
- England-wide discovery and candidate review
- Provider enrichment and verification
- Pricing discovery, extraction and approval
- Scheduled revalidation and exception workflows
- AWS deployment and infrastructure as code

## v2.6.1 – Automation-first provider approval (implemented first pathway)
- [x] Configurable automatic approval switch and confidence threshold.
- [x] High-precision first-party website approval using explicit Schema.org `FuneralHome`, complete UK address, telephone, matching website domain, Companies House name relationship and duplicate checks.
- [x] Automatic creation/publication of eligible provider and first branch, with accepted source observation and audit events.
- [x] Exception routing for incomplete, conflicting, low-confidence, duplicate or ambiguous candidates.
- [x] Exclude auto-approved records from the manual identity/branch exception workflow.
- [ ] Extend independent evidence pathways to providers not represented in Companies House (sole traders and partnerships).
- [ ] Automate multi-branch discovery and branch-level revalidation.
- [ ] Automate NAFD, SAIF/SAIFCharter and FCA checks with independent status records.
- [ ] Add source-permission policy configuration and legal review before commercial rollout.
- [ ] Expand the ruleset with calibrated validation data and false-positive/false-negative monitoring.


## Five-stage implementation acceptance

The current five-stage status, exit criteria, evidence requirements and operating
safeguards are maintained in [FIVE-STAGE-ACCEPTANCE-PLAN.md](FIVE-STAGE-ACCEPTANCE-PLAN.md).
The plan preserves the Overture-first policy and separates implemented code,
CI validation, product acceptance and operational sign-off.
