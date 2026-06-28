"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the monitor service."""

    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = Field(
        default="sqlite:///./service_monitor.db",
        alias="DATABASE_URL",
    )
    admin_api_key: str | None = Field(default=None, alias="ADMIN_API_KEY")
    demo_mode: bool = Field(default=False, alias="DEMO_MODE")
    web_cors_origins: str = Field(default="", alias="WEB_CORS_ORIGINS")
    check_timeout_seconds: int = Field(default=5, alias="CHECK_TIMEOUT_SECONDS")
    max_monitors: int = Field(default=25, alias="MAX_MONITORS")
    scheduler_enabled: bool = Field(default=False, alias="SCHEDULER_ENABLED")
    max_concurrent_checks: int = Field(default=10, alias="MAX_CONCURRENT_CHECKS")
    data_retention_days: int = Field(default=7, alias="DATA_RETENTION_DAYS")
    alerts_enabled: bool = Field(default=False, alias="ALERTS_ENABLED")
    alert_send_resolved: bool = Field(default=True, alias="ALERT_SEND_RESOLVED")
    alert_email_to: str | None = Field(default=None, alias="ALERT_EMAIL_TO")
    smtp_host: str | None = Field(default=None, alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str | None = Field(default=None, alias="SMTP_USERNAME")
    smtp_password: str | None = Field(default=None, alias="SMTP_PASSWORD")
    smtp_from: str | None = Field(default=None, alias="SMTP_FROM")
    frontend_public_url: str | None = Field(default=None, alias="FRONTEND_PUBLIC_URL")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()


def cors_origins_from_settings(settings: Settings | None = None) -> list[str]:
    """Return exact browser origins allowed for cross-origin API access."""
    resolved = settings or get_settings()
    raw = resolved.web_cors_origins.strip()
    if not raw:
        return ["http://localhost:5173", "http://127.0.0.1:5173"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
