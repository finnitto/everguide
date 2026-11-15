from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "Everguide"
    app_env: str = "development"
    app_version: str = "2.7.3"
    database_url: str = "postgresql+psycopg://everguide:change-this-local-password@db:5432/everguide"
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"
    companies_house_api_key: str = ""
    companies_house_sic_codes: str = "96030"
    google_places_api_key: str = ""
    brave_search_api_key: str = ""
    search_provider: str = "brave"
    auto_approve_providers: bool = True
    auto_approval_min_confidence: float = 0.94
    overture_auto_process: bool = True
    overture_feed_enabled: bool = True
    overture_feed_daily_hour: int = 4
    overture_feed_daily_minute: int = 30
    overture_feed_batch_size: int = 500
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

settings = Settings()
