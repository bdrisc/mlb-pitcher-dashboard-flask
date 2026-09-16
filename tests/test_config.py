"""Production configuration and response-hardening tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app
from app.config import DEVELOPMENT_SECRET, database_url, environment_flag

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _app_config(tmp_path, **overrides):
    config = {
        "TESTING": True,
        "APP_ENV": "development",
        "PITCH_DATA_PATH": str(PROJECT_ROOT / "data" / "sample_statcast.csv"),
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{(tmp_path / 'config.db').as_posix()}",
        "SQLALCHEMY_ENGINE_OPTIONS": {},
        "BEHIND_PROXY": False,
    }
    config.update(overrides)
    return config


def test_database_url_normalizes_common_hosted_postgres_schemes(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://user:password@database:5432/baseball")
    assert database_url() == "postgresql+psycopg://user:password@database:5432/baseball"

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@database:5432/baseball")
    assert database_url() == "postgresql+psycopg://user:password@database:5432/baseball"


@pytest.mark.parametrize("value", ["1", "TRUE", "yes", "On"])
def test_environment_flag_accepts_conventional_true_values(monkeypatch, value):
    monkeypatch.setenv("FEATURE_ENABLED", value)
    assert environment_flag("FEATURE_ENABLED") is True


def test_production_rejects_the_development_secret(tmp_path):
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(
            _app_config(
                tmp_path,
                APP_ENV="production",
                SECRET_KEY=DEVELOPMENT_SECRET,
            )
        )


def test_production_enables_proxy_and_secure_cookie_settings(tmp_path):
    application = create_app(
        _app_config(
            tmp_path,
            APP_ENV="production",
            SECRET_KEY="a-production-only-test-secret",
            BEHIND_PROXY=True,
        )
    )

    assert isinstance(application.wsgi_app, ProxyFix)
    assert application.config["SESSION_COOKIE_SECURE"] is True
    assert application.config["PREFERRED_URL_SCHEME"] == "https"


def test_production_legacy_seed_path_uses_small_runtime_fallback(tmp_path):
    production_seed = tmp_path / "production_statcast_2026.csv.gz"
    application = create_app(
        _app_config(
            tmp_path,
            APP_ENV="production",
            SECRET_KEY="a-production-only-test-secret",
            PITCH_DATA_PATH=str(production_seed),
            STATCAST_SEED_PATH=str(production_seed),
        )
    )

    store = application.extensions["pitch_data_store"]
    assert store.source_name == "sample_statcast.csv"
    assert store.row_count == 6
    assert application.config["STATCAST_SEED_PATH"] == str(production_seed)


def test_application_adds_baseline_security_headers(client):
    response = client.get("/")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
