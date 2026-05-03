"""
Global-Pulse – API Configuration
Reads settings from environment variables via pydantic-settings.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", protected_namespaces=())

    # DB
    postgres_user: str = "globalpulse"
    postgres_password: str = "changeme"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "globalpulse"

    # Auth / API keys
    api_secret_key: str = "super-secret-change-me"
    api_algorithm: str = "HS256"
    api_key_expire_days: int = 365

    # Forecasting
    forecast_horizon_days: int = 7
    model_store_path: str = "/app/model_store"

    # Server
    api_host: str = "0.0.0.0"
    api_port: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings()
