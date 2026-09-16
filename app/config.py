"""Environment-backed configuration for the Flask application."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEVELOPMENT_SECRET = "development-only-change-me"


def environment_flag(name: str, default: bool = False) -> bool:
    """Parse a conventional boolean environment variable."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def database_url() -> str:
    """Return a SQLAlchemy URL while accepting common hosted Postgres URLs."""
    configured = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/mlb_pitch_intelligence",
    )
    if configured.startswith("postgres://"):
        return configured.replace("postgres://", "postgresql+psycopg://", 1)
    if configured.startswith("postgresql://"):
        return configured.replace("postgresql://", "postgresql+psycopg://", 1)
    return configured


class Config:
    """Default development and production-safe configuration."""

    APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
    APP_VERSION = os.getenv("APP_VERSION", "development")
    SECRET_KEY = os.getenv("SECRET_KEY", DEVELOPMENT_SECRET)
    PITCH_DATA_PATH = os.getenv(
        "PITCH_DATA_PATH",
        str(PROJECT_ROOT / "data" / "sample_statcast.csv"),
    )
    STATCAST_SEED_PATH = os.getenv("STATCAST_SEED_PATH", PITCH_DATA_PATH)
    SQLALCHEMY_DATABASE_URI = database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 300}
    BEHIND_PROXY = environment_flag("BEHIND_PROXY", APP_ENV == "production")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = APP_ENV == "production"
    PREFERRED_URL_SCHEME = "https" if APP_ENV == "production" else "http"
    JSON_SORT_KEYS = False
