"""Guard the startup maintenance order and opt-out for verified snapshots."""

from pathlib import Path


ENTRYPOINT = Path(__file__).resolve().parents[1] / "scripts" / "docker-entrypoint.sh"


def test_snapshot_opt_out_precedes_background_writers():
    script = ENTRYPOINT.read_text()
    guard = script.index('if [ "${STARTUP_MAINTENANCE_ENABLED:-1}" = "0" ]; then')
    assert script.index("flask --app wsgi db upgrade") < guard
    assert script.index('exec "$@"', guard) < script.index("statcast seed-if-needed")


def test_adjusted_angles_follow_ingestion_and_classification_refresh():
    script = ENTRYPOINT.read_text()
    ingestion = script.index("statcast sync-recent")
    classification = script.index("statcast refresh-pitch-types")
    for command in ("statcast backfill-vaa-adj", "statcast backfill-haaaa"):
        assert script.count(command) == 1
        assert script.index(command) > max(ingestion, classification)
