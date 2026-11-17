from pathlib import Path

route_changes = {
    "apps/api/app/routers/discovery.py": [
        ("def start_discovery(db: Session = Depends(get_db)):",
         "def start_discovery():"),
    ],
    "apps/api/app/routers/companies_house.py": [
        ("def start_import(db: Session = Depends(get_db)):",
         "def start_import():"),
        ("def start_profile_enrichment(db: Session = Depends(get_db)):",
         "def start_profile_enrichment():"),
    ],
    "apps/api/app/routers/company_websites.py": [
        ("def start_run(db: Session = Depends(get_db)):",
         "def start_run():"),
        ("def resume_run(run_id: int, db: Session = Depends(get_db)):",
         "def resume_run(run_id: int):"),
    ],
    "apps/api/app/routers/website_discovery.py": [
        ("def start_verification_run(db: Session = Depends(get_db)):",
         "def start_verification_run():"),
    ],
}

task_changes = {
    "apps/api/app/tasks.py": [
        (
            "def run_provider_discovery(self, run_id: int):\n    db = SessionLocal()",
            "def run_provider_discovery(self, run_id: int):\n"
            '    return {"status": "disabled", "reason": "overture_first_source_policy", "run_id": run_id}\n'
            "    db = SessionLocal()"
        ),
        (
            "def discover_provider_websites():\n    \"\"\"Search independently for provider-owned website candidates by England region.\"\"\"\n"
            "    from urllib.parse import urlparse\n"
            "    from app.models import WebsiteDiscoveryResult\n"
            "    from app.search_providers import search_web, SearchProviderError\n"
            "    db = SessionLocal()",
            "def discover_provider_websites():\n    \"\"\"Search independently for provider-owned website candidates by England region.\"\"\"\n"
            "    return {\"status\": \"disabled\", \"reason\": \"overture_first_source_policy\"}\n"
            "    from urllib.parse import urlparse\n"
            "    from app.models import WebsiteDiscoveryResult\n"
            "    from app.search_providers import search_web, SearchProviderError\n"
            "    db = SessionLocal()"
        ),
        (
            "def weekly_discovery_cycle():\n    \"\"\"Run regional web discovery, then queue one bounded verification batch.\"\"\"\n",
            "def weekly_discovery_cycle():\n    \"\"\"Run regional web discovery, then queue one bounded verification batch.\"\"\"\n"
            "    return {\"status\": \"disabled\", \"reason\": \"overture_first_source_policy\"}\n"
        ),
        (
            "def enqueue_scheduled_verification(discovery_result):\n    from app.models import WebsiteVerificationRun\n    db = SessionLocal()",
            "def enqueue_scheduled_verification(discovery_result):\n"
            "    return {\"status\": \"disabled\", \"reason\": \"overture_first_source_policy\"}\n"
            "    from app.models import WebsiteVerificationRun\n"
            "    db = SessionLocal()"
        ),
        (
            "def verify_website_candidates(limit=50, run_id=None):\n"
            "    \"\"\"Run conservative robots-aware technical checks on a bounded candidate batch.\"\"\"\n"
            "    from app.models import WebsiteDiscoveryResult, WebsiteVerification, Provider, Branch, SourceObservation, AuditEvent\n"
            "    from app.website_checks import verify_candidate\n"
            "    from app.routers.website_discovery import _classify\n"
            "    db = SessionLocal()",
            "def verify_website_candidates(limit=50, run_id=None):\n"
            "    \"\"\"Run conservative robots-aware technical checks on a bounded candidate batch.\"\"\"\n"
            "    return {\"status\": \"disabled\", \"reason\": \"overture_first_source_policy\", \"run_id\": run_id}\n"
            "    from app.models import WebsiteDiscoveryResult, WebsiteVerification, Provider, Branch, SourceObservation, AuditEvent\n"
            "    from app.website_checks import verify_candidate\n"
            "    from app.routers.website_discovery import _classify\n"
            "    db = SessionLocal()"
        ),
        (
            "    from app.website_checks import verify_candidate\n"
            "    from app.provider_approval import assess_auto_approval\n"
            "    db=SessionLocal()",
            "    from app.website_checks import verify_candidate\n"
            "    from app.provider_approval import assess_auto_approval\n"
            "    return {\"status\": \"disabled\", \"reason\": \"overture_first_source_policy\", \"run_id\": run_id}\n"
            "    db=SessionLocal()"
        ),
    ],
    "apps/api/app/companies_house.py": [
        (
            "def import_companies_house_sic(self, run_id: int):\n    db = SessionLocal()",
            "def import_companies_house_sic(self, run_id: int):\n"
            '    return {"status": "disabled", "reason": "overture_first_source_policy", "run_id": run_id}\n'
            "    db = SessionLocal()"
        ),
        (
            "def enrich_company_profiles(self, run_id: int):\n"
            "    \"\"\"Enrich active legal entities using the official company profile resource.\"\"\"\n"
            "    db = SessionLocal()",
            "def enrich_company_profiles(self, run_id: int):\n"
            "    \"\"\"Enrich active legal entities using the official company profile resource.\"\"\"\n"
            '    return {"status": "disabled", "reason": "overture_first_source_policy", "run_id": run_id}\n'
            "    db = SessionLocal()"
        ),
    ],
}

def apply_changes(changes):
    for filename, replacements in changes.items():
        path = Path(filename)
        original = path.read_text(encoding="utf-8")
        updated = original

        for old, new in replacements:
            count = updated.count(old)
            if count != 1:
                raise SystemExit(
                    f"STOP: expected one match in {filename}, found {count}: {old.splitlines()[0]}"
                )
            updated = updated.replace(old, new, 1)

        path.write_text(updated, encoding="utf-8")
        print(f"Patched: {filename}")

apply_changes(route_changes)
apply_changes(task_changes)
print("Stage 1 route dependency and Celery task guards applied.")
