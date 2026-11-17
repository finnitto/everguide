import pytest

from app import tasks, companies_house


def fail_if_database_is_opened():
    raise AssertionError("Disabled legacy task attempted to open a database session")


@pytest.mark.parametrize(
    "module,task_name,args,expected",
    [
        (tasks, "run_provider_discovery", (123,), {"status": "disabled", "reason": "overture_first_source_policy", "run_id": 123}),
        (tasks, "discover_provider_websites", (), {"status": "disabled", "reason": "overture_first_source_policy"}),
        (tasks, "weekly_discovery_cycle", (), {"status": "disabled", "reason": "overture_first_source_policy"}),
        (tasks, "enqueue_scheduled_verification", ({"status": "complete"},), {"status": "disabled", "reason": "overture_first_source_policy"}),
        (tasks, "verify_website_candidates", (50, 456), {"status": "disabled", "reason": "overture_first_source_policy", "run_id": 456}),
        (tasks, "discover_company_websites", (789,), {"status": "disabled", "reason": "overture_first_source_policy", "run_id": 789}),
        (companies_house, "import_companies_house_sic", (123,), {"status": "disabled", "reason": "overture_first_source_policy", "run_id": 123}),
        (companies_house, "enrich_company_profiles", (123,), {"status": "disabled", "reason": "overture_first_source_policy", "run_id": 123}),
    ],
)
def test_legacy_discovery_tasks_exit_without_database_access(
    monkeypatch, module, task_name, args, expected
):
    monkeypatch.setattr(module, "SessionLocal", fail_if_database_is_opened)
    result = getattr(module, task_name).run(*args)
    assert result == expected
