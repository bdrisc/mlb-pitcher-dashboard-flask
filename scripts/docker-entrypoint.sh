#!/bin/sh
set -eu

echo "Starting web server on port ${PORT:-10000}."

(
    delay="${STARTUP_MAINTENANCE_DELAY_SECONDS:-15}"
    echo "Background maintenance will start in ${delay} seconds."
    sleep "$delay"

    maintenance_ok=1

    if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
        echo "Starting database migrations in the background."
        if flask --app wsgi db upgrade; then
            echo "Background database migrations finished successfully."
        else
            echo "Background database migrations failed; skipping data maintenance." >&2
            maintenance_ok=0
        fi
    fi

    if [ "$maintenance_ok" = "1" ] && [ "${SEED_DATABASE:-${SEED_SAMPLE_DATA:-0}}" = "1" ]; then
        echo "Starting database seed check in the background."
        if flask --app wsgi statcast seed-if-needed \
            "${STATCAST_SEED_PATH:-${PITCH_DATA_PATH:-data/sample_statcast.csv}}"; then
            echo "Background database seed check finished successfully."
        else
            echo "Background database seed check failed; skipping Statcast refresh." >&2
            maintenance_ok=0
        fi
    fi

    if [ "$maintenance_ok" = "1" ] && [ "${SYNC_RECENT_ON_STARTUP:-0}" = "1" ]; then
        echo "Starting recent Statcast sync in the background."
        if flask --app wsgi statcast sync-recent \
            --lookback-days "${SYNC_RECENT_LOOKBACK_DAYS:-4}"; then
            echo "Background Statcast sync finished successfully."
        else
            echo "Background Statcast sync failed; the web service will remain available." >&2
        fi
    fi
) &

exec "$@"
