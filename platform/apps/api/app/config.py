from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "Everguide"
    app_env: str = "development"
    app_version: str = "0.8.0"
    database_url: str = "postgresql+psycopg://everguide:change-this-local-password@db:5432/everguide"
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"
    google_places_api_key: str = ""
    brave_search_api_key: str = ""
    search_provider: str = "brave"
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

settings = Settings()
