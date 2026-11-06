# Worker

The Celery worker runs `app.celery_app:celery_app` from the shared API image. A diagnostic task named `everguide.system.ping` proves that the worker can execute queued jobs. Business workflows will be added in later releases.
