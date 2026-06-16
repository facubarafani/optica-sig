"""Application settings, loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Application
    app_name: str = "SGI Optica"
    environment: str = "local"
    debug: bool = True

    # Database
    database_url: str = "postgresql+psycopg2://sgi:sgi@localhost:5432/sgi"

    # Security
    secret_key: str = "change-me-in-production-please-0123456789abcdef"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    # Single-tenant MVP: active company id. Multi-tenant ready (every row has
    # company_id); this is the resolution shortcut until real tenancy lands.
    default_company_id: int = 1


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
