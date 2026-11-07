# Everguide v1.4.0

## Published directory coverage, quality reporting and scheduled discovery

This release adds an admin reporting endpoint and dashboard for distinct published providers and branches, automatic-approval audit events, county-level published branch coverage, potential duplicate signals and source-observation totals.

It also adds a Celery Beat service that schedules an England-wide independent website discovery cycle every Sunday at 02:00 Europe/London. After search completes, it queues a bounded verification run (up to 250 candidates); the existing worker continues through the eligible backlog in bounded batches. The schedule is a discovery/verification cadence, not yet a full revalidation of every already-published provider website.

## Install

1. Extract this release over the existing project files. Keep `.env` unchanged.
2. From Git Bash:

```bash
cd /c/projects/everguide/platform
bash scripts/deploy-local.sh
```

No database migration is required. Do not delete Docker volumes.

## Operational notes

- The admin API remains unauthenticated in this local development release. Do not expose it to the public internet.
- Weekly discovery uses the configured search provider and existing credentials.
- Duplicate groups are signals only. No records are merged or deleted.
- County reporting depends on branch county fields being populated; missing county values are counted separately.
- Provider and branch counts are distinct database records, not search-result or approval-event totals.
