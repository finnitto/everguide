import app.overture_tasks as overture_tasks
from app.config import settings


def test_scheduled_overture_retry_is_inert_when_scheduling_disabled(monkeypatch):
    monkeypatch.setattr(settings, "overture_scheduled_tasks_enabled", False)

    def unexpected_database_access():
        raise AssertionError("Disabled scheduled retry must not open the database")

    monkeypatch.setattr(overture_tasks, "SessionLocal", unexpected_database_access)
    result = overture_tasks.retry_awaiting_enrichment.run()

    assert result == {"status": "disabled", "requeued": 0, "retry_limits_reached": 0}


def test_stale_overture_recovery_is_inert_when_scheduling_disabled(monkeypatch):
    monkeypatch.setattr(settings, "overture_scheduled_tasks_enabled", False)

    def unexpected_database_access():
        raise AssertionError("Disabled stale-run recovery must not open the database")

    monkeypatch.setattr(overture_tasks, "SessionLocal", unexpected_database_access)
    result = overture_tasks.reconcile_stale_overture_import_runs.run()

    assert result == {
        "status": "disabled",
        "resumed_runs": [],
        "completed_runs": [],
        "failed_runs": [],
    }
