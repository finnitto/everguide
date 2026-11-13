from celery import Celery, chain
from celery.schedules import crontab
from app.config import settings

celery_app = Celery("everguide", broker=settings.celery_broker_url,
                    backend=settings.celery_result_backend, include=["app.tasks", "app.companies_house", "app.identity_tasks", "app.overture_tasks", "app.overture_feed"])
celery_app.conf.update(task_serializer="json", accept_content=["json"],
                       result_serializer="json", timezone="Europe/London",
                       enable_utc=True, task_acks_late=True, worker_prefetch_multiplier=1)


# Weekly England-wide discovery cycle. It searches first, then queues a bounded
# verification run for the resulting backlog.
celery_app.conf.beat_schedule = {
    "overture-latest-release-check-daily": {
        "task": "everguide.overture.poll_latest_release",
        "schedule": crontab(hour=settings.overture_feed_daily_hour, minute=settings.overture_feed_daily_minute),
        "options": {"expires": 60 * 60 * 20},
    },
} if settings.overture_feed_enabled else {}
