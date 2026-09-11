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

    # The demo tenant the seed pins itself to. Login no longer reads this —
    # a session's company comes from the authenticated user (app/core/deps.py)
    # — it only tells `python -m scripts.seed` which company to build.
    default_company_id: int = 1

    # Provider (platform) bootstrap account, created by the seed. These are the
    # credentials for /admin, not for a shop. Override both anywhere that is
    # not a local demo.
    platform_admin_email: str = "owner@sgi.com"
    platform_admin_password: str = "owner1234"

    # --- Email -----------------------------------------------------------
    # Where the app lives, as a user's browser sees it. Invitation and reset
    # links are built from this, so getting it wrong sends people to localhost.
    public_base_url: str = "http://localhost:8000"

    # console | memory (tests) | smtp (any provider) | resend | brevo
    email_backend: str = "console"
    email_from: str = "Mi Óptica Digital <no-reply@miopticadigital.com.ar>"

    # SMTP. Port 587 + STARTTLS: port 25 is blocked outbound on most PaaS.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True

    resend_api_key: str = ""
    brevo_api_key: str = ""

    # An invitation is handed out deliberately and may sit unopened over a
    # weekend; a reset is requested by someone waiting at their screen.
    invitation_ttl_hours: int = 168  # 7 days
    password_reset_ttl_hours: int = 1


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
