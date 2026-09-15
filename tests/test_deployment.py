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
    assert 'SEED_SAMPLE_DATA: "1"' in compose


def test_render_blueprint_connects_web_database_and_health_check():
    blueprint = _read("render.yaml")

    assert "runtime: docker" in blueprint
    assert "healthCheckPath: /api/v1/health" in blueprint
    assert "preDeployCommand:" not in blueprint
    assert 'value: "1"' in blueprint
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
    assert 'CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:app"]' in dockerfile
    assert os.access(entrypoint, os.X_OK)
