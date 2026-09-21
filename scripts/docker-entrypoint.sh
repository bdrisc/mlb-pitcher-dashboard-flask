#!/bin/sh
set -eu

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    flask --app wsgi db upgrade
fi

if [ "${SEED_DATABASE:-${SEED_SAMPLE_DATA:-0}}" = "1" ]; then
    flask --app wsgi statcast seed-if-needed \
        "${STATCAST_SEED_PATH:-${PITCH_DATA_PATH:-data/sample_statcast.csv}}"
fi

if [ "${SYNC_RECENT_ON_STARTUP:-0}" = "1" ]; then
    flask --app wsgi statcast sync-recent \
        --lookback-days "${SYNC_RECENT_LOOKBACK_DAYS:-4}"
fi

exec "$@"
