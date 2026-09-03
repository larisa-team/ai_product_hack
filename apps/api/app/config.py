"""Настройки приложения из ENV (см. .env.example)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    database_url: str = "postgresql+psycopg://app:app@postgres:5432/app"
    redis_url: str = "redis://redis:6379/0"
    cors_origins: str = "http://localhost"

    llm_provider: str = "mock"          # mock | openai_compat
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    tg_fetch_limit: int = 100
    tg_fetch_days: int = 7
    filter_batch: int = 30
    newsmaker_cap: int = 100

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
