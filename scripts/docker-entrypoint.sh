#!/bin/sh
set -eu

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    flask --app wsgi db upgrade
fi

if [ "${SEED_SAMPLE_DATA:-0}" = "1" ]; then
    flask --app wsgi statcast seed-if-needed "${PITCH_DATA_PATH:-data/sample_statcast.csv}"
fi

exec "$@"
