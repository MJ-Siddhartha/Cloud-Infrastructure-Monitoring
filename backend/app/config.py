"""Application configuration using pydantic-settings."""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://monitor:monitor@localhost:5432/monitoring"

    # Telegram notifications
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_CHAT_ID: str | None = None

    # SMTP / Email notifications
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM_EMAIL: str = "alerts@monitoring.local"
    SMTP_TO_EMAIL: str | None = None

    # SSH for recovery
    SSH_KEY_PATH: str = "~/.ssh/id_rsa"
    SSH_USERNAME: str = "monitor"
    SSH_TIMEOUT: int = 30

    # Recovery engine
    RECOVERY_ENABLED: bool = False
    RECOVERY_DRY_RUN: bool = True
    RECOVERY_COOLDOWN_SECONDS: int = 300
    ALLOWED_RECOVERY_HOSTS: str | list[str] = []
    ALLOWED_RECOVERY_SERVICES: str | list[str] = [
        "nginx",
        "apache2",
        "postgresql",
        "mysql",
        "redis-server",
    ]

    # Logging
    LOG_LEVEL: str = "INFO"

    @field_validator("ALLOWED_RECOVERY_HOSTS", "ALLOWED_RECOVERY_SERVICES", mode="before")
    @classmethod
    def parse_comma_separated(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v


def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()


settings = get_settings()

