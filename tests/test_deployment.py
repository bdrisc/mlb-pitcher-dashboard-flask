"""Static validation for the checked-in deployment assets."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (PROJECT_ROOT / name).read_text(encoding="utf-8")


def test_compose_defines_healthy_web_and_postgres_services():
    compose = _read("docker-compose.yml")

    assert "database:" in compose
    assert "web:" in compose
    assert "image: postgres:17-alpine" in compose
    assert "condition: service_healthy" in compose
    assert 'RUN_MIGRATIONS: "1"' in compose
    assert 'SEED_DATABASE: "1"' in compose


def test_render_blueprint_connects_web_database_and_health_check():
    blueprint = _read("render.yaml")

    assert "runtime: docker" in blueprint
    assert "healthCheckPath: /api/v1/health" in blueprint
    assert "preDeployCommand:" not in blueprint
    assert "initialDeployHook:" not in blueprint
    assert '      - key: RUN_MIGRATIONS\n        value: "1"' in blueprint
    assert '      - key: SEED_DATABASE\n        value: "1"' in blueprint
    assert '      - key: SYNC_RECENT_ON_STARTUP\n        value: "1"' in blueprint
    assert '      - key: SYNC_RECENT_LOOKBACK_DAYS\n        value: "4"' in blueprint
    assert "key: STATCAST_SEED_PATH" in blueprint
    assert "value: data/production_statcast_2026.csv.gz" in blueprint
    assert "      - key: PITCH_DATA_PATH\n        value: data/sample_statcast.csv" in blueprint
    assert "autoDeployTrigger: checksPass" in blueprint
    assert "fromDatabase:" in blueprint
    assert "property: connectionString" in blueprint
    assert 'postgresMajorVersion: "17"' in blueprint


def test_ci_runs_supported_python_versions_postgres_and_docker_build():
    workflow = _read(".github/workflows/ci.yml")

    assert 'python-version: ["3.10", "3.12"]' in workflow
    assert "image: postgres:17-alpine" in workflow
    assert "flask --app wsgi db upgrade" in workflow
    assert "docker build --tag mlb-pitch-intelligence:ci ." in workflow
    assert "needs: test" in workflow


def test_docker_image_uses_non_root_user_healthcheck_and_gunicorn():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = PROJECT_ROOT / "scripts" / "docker-entrypoint.sh"

    assert "FROM python:3.10-slim" in dockerfile
    assert "USER app" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "requirements-data.txt" in dockerfile
    assert 'CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:app"]' in dockerfile
    assert "statcast seed-if-needed" in entrypoint.read_text(encoding="utf-8")
    assert "statcast sync-recent" in entrypoint.read_text(encoding="utf-8")
    assert os.access(entrypoint, os.X_OK)


def test_daily_sync_workflow_uses_a_secret_render_deploy_hook():
    workflow = _read(".github/workflows/daily-data-sync.yml")

    assert 'cron: "0 15 15-31 3 *"' in workflow
    assert 'cron: "0 15 * 4-10 *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "secrets.RENDER_DEPLOY_HOOK_URL" in workflow
    assert 'curl --fail --show-error --silent --request POST "$RENDER_DEPLOY_HOOK_URL"' in workflow
