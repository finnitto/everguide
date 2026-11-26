from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    app_name: str = "Everguide"
    app_env: str = "development"
    app_version: str = "2.8.0"
    database_url: str = "postgresql+psycopg://everguide:change-this-local-password@db:5432/everguide"
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"
    companies_house_api_key: str = ""
    companies_house_sic_codes: str = "96030"
    google_places_api_key: str = ""
    brave_search_api_key: str = ""
    search_provider: str = "brave"
    auto_approve_providers: bool = False
    auto_approval_min_confidence: float = 0.94
    # Process each completed Overture import; this does not publish providers
    # while auto_approve_providers remains false.
    overture_auto_process: bool = True
    overture_feed_enabled: bool = True
    overture_scheduled_tasks_enabled: bool = False
    overture_feed_daily_hour: int = 4
    overture_feed_daily_minute: int = 30
    overture_feed_batch_size: int = 500
    # Deterministic extraction of prices from verified provider-owned websites.
    # Deterministic source-backed extraction has no external AI/API key cost.
    price_enrichment_enabled: bool = True
    price_enrichment_max_pages: int = 6
    # Follow a short chain of safe, same-provider HTTPS redirects while checking sites.
    website_max_redirects: int = Field(default=3, ge=0, le=5)
    # JSON object mapping reviewer IDs to SHA-256 hashes of bearer tokens.
    identity_review_credentials: str = "{}"
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

settings = Settings()
