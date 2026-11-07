from celery import Celery, chain
from celery.schedules import crontab
from app.config import settings

celery_app = Celery("everguide", broker=settings.celery_broker_url,
                    backend=settings.celery_result_backend, include=["app.tasks"])
celery_app.conf.update(task_serializer="json", accept_content=["json"],
                       result_serializer="json", timezone="Europe/London",
                       enable_utc=True, task_acks_late=True, worker_prefetch_multiplier=1)


# Weekly England-wide discovery cycle. It searches first, then queues a bounded
# verification run for the resulting backlog.
celery_app.conf.beat_schedule = {
    "weekly-england-provider-discovery": {
        "task": "everguide.automation.weekly_discovery_cycle",
        "schedule": crontab(minute=0, hour=2, day_of_week="sunday"),
        "options": {"expires": 60 * 60 * 3},
    }
}
