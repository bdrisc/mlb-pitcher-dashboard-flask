"""Guard the startup maintenance order and opt-out for verified snapshots."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parents[1] / "scripts" / "docker-entrypoint.sh"


def test_snapshot_opt_out_precedes_background_writers():
    script = ENTRYPOINT.read_text()
    guard = script.index('if [ "${APP_ENV:-development}" != "development" ]')
    assert '[ "${STARTUP_MAINTENANCE_ENABLED:-0}" != "1" ]' in script
    assert script.index("flask --app wsgi db upgrade") < guard
    assert script.index('exec "$@"', guard) < script.index("statcast seed-if-needed")


def test_adjusted_angles_follow_ingestion_and_classification_refresh():
    script = ENTRYPOINT.read_text()
    ingestion = script.index("statcast sync-recent")
    classification = script.index("statcast refresh-pitch-types")
    for command in ("statcast backfill-vaa-adj", "statcast backfill-haaaa"):
        assert script.count(command) == 1
        assert script.index(command) > max(ingestion, classification)


@pytest.mark.skipif(os.name == "nt" or shutil.which("sh") is None, reason="POSIX entrypoint")
def test_production_cannot_opt_in_to_legacy_startup_writers(tmp_path):
    fake_flask = tmp_path / "flask"
    fake_flask.write_text("#!/bin/sh\necho UNEXPECTED_WRITER\n", encoding="utf-8")
    fake_flask.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "APP_ENV": "production",
        "STARTUP_MAINTENANCE_ENABLED": "1",
        "RUN_MIGRATIONS": "0",
        "STARTUP_MAINTENANCE_DELAY_SECONDS": "0",
        "SEED_DATABASE": "1",
    }
    result = subprocess.run(
        ["sh", str(ENTRYPOINT), "sh", "-c", "echo serving"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert "serving" in result.stdout
    assert "Background data maintenance disabled" in result.stdout
    assert "UNEXPECTED_WRITER" not in result.stdout
