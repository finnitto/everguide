# Everguide 2.7.6 — Manual-first validation controls

## Changes
- Added `OVERTURE_SCHEDULED_TASKS_ENABLED`, defaulting to `false`, to independently control Celery Beat registration.
- Kept manual/on-demand Overture API actions separate from scheduled execution.
- Exposed scheduled-task state in the Overture status endpoint.
- Updated Compose, environment example and operating documentation.
- Updated API application version default and Compose override to 2.7.6.

## Intended validation configuration
- `OVERTURE_FEED_ENABLED=true`: manual feed check remains available.
- `OVERTURE_SCHEDULED_TASKS_ENABLED=false`: no Overture Beat schedules registered.
- `OVERTURE_AUTO_PROCESS=true`: a manually completed import can automatically queue candidate processing.
- `AUTO_APPROVE_PROVIDERS=false`: normal development does not publish automatically.

No database schema changes or migrations are included. Existing `.env` and Docker volumes must be preserved.
