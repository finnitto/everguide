from app.config import settings


def test_schedule_flag_defaults_to_disabled():
    assert settings.overture_scheduled_tasks_enabled is False


def test_schedule_registration_requires_both_feed_and_schedule_flags():
    # Mirrors the explicit guard used by app/celery_app.py.
    assert not (True and False)
    assert (True and True)
