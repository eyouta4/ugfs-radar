"""
src/config/settings.py — Configuration centralisée.

Toute la config est typée via Pydantic Settings, chargée depuis
les variables d'environnement (.env en dev, Railway env en prod).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Configuration de l'application, chargée depuis .env / variables d'env."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # === Database ===
    database_url: str = Field(default="postgresql+asyncpg://ugfs:ugfs@localhost:5432/ugfs_radar")
    database_url_sync: str = Field(default="postgresql+psycopg2://ugfs:ugfs@localhost:5432/ugfs_radar")

    # === LLM ===
    groq_api_key: str = Field(default="")
    groq_model: str = Field(default="llama-3.3-70b-versatile")
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    # === Embeddings ===
    voyage_api_key: str = Field(default="")
    voyage_model: str = Field(default="voyage-3-lite")

    # === Email ===
    resend_api_key: str = Field(default="")
    email_from: str = Field(default="UGFS-Radar <radar@ugfs-na.com>")
    email_to: str = Field(default="")
    email_cc: str = Field(default="")

    # === Web search ===
    google_cse_api_key: str = Field(default="")
    google_cse_id: str = Field(default="")
    serpapi_key: str = Field(default="")

    # === Microsoft Teams ===
    teams_tenant_id: str = Field(default="")
    teams_client_id: str = Field(default="")
    teams_client_secret: str = Field(default="")
    teams_team_id: str = Field(default="")
    teams_channel_id: str = Field(default="")
    teams_enabled: bool = Field(default=False)

    # === Observability ===
    sentry_dsn: str | None = None
    log_level: str = Field(default="INFO")
    environment: str = Field(default="development")

    # === Scheduler ===
    timezone: str = Field(default="Africa/Tunis")
    weekly_run_day: str = Field(default="mon")
    weekly_run_hour: int = Field(default=7)
    weekly_run_minute: int = Field(default=0)

    # === Scoring ===
    urgent_deadline_days: int = Field(default=7)
    similarity_boost_threshold: float = Field(default=0.85)
    similarity_boost_points: int = Field(default=10)

    # === API ===
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    api_feedback_token: str = Field(default="change-me-in-prod")

    @property
    def email_recipients(self) -> list[str]:
        """Liste des destinataires de l'email hebdo."""
        return [e.strip() for e in self.email_to.split(",") if e.strip()]

    @property
    def email_cc_list(self) -> list[str]:
        return [e.strip() for e in self.email_cc.split(",") if e.strip()]


@lru_cache
def get_settings() -> Settings:
    """Singleton settings (cache)."""
    return Settings()


# === Profil UGFS (YAML) ===

@lru_cache
def get_ugfs_profile() -> dict[str, Any]:
    """Charge le profil structuré UGFS depuis data/ugfs_profile.yaml."""
    profile_path = PROJECT_ROOT / "data" / "ugfs_profile.yaml"
    with profile_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)
