#!/bin/sh
set -eu

# New code must never query new columns before the schema migration completes.
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    echo "Applying database migrations before starting the web server."
    flask --app wsgi db upgrade
fi

echo "Starting web server on port ${PORT:-10000}."

(
    delay="${STARTUP_MAINTENANCE_DELAY_SECONDS:-15}"
    echo "Background maintenance will start in ${delay} seconds."
    sleep "$delay"

    maintenance_ok=1

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

    if [ "$maintenance_ok" = "1" ] && [ "${SYNC_XSLG_ON_STARTUP:-1}" = "1" ]; then
        slg_source="${STATCAST_SEED_PATH:-data/production_statcast_2026.csv.gz}"
        if [ -f "$slg_source" ]; then
            echo "Backfilling xSLG from the existing deployable Statcast sample."
            if ! flask --app wsgi statcast backfill-xslg --season 2026 --csv-path "$slg_source"; then
                echo "xSLG could not be backfilled from the bundled sample; existing data retained." >&2
            fi
        fi
    fi

    if [ "$maintenance_ok" = "1" ] && [ "${SYNC_WOBA_ON_STARTUP:-1}" = "1" ]; then
        if ! flask --app wsgi statcast backfill-woba; then
            echo "Some Savant wOBA outcomes remain unverified; saved data retained." >&2
        fi
    fi

    if [ "$maintenance_ok" = "1" ] && [ "${SYNC_BARRELS_ON_STARTUP:-1}" = "1" ]; then
        if ! flask --app wsgi statcast backfill-barrels; then
            echo "Some barrel classifications remain unavailable; saved data retained." >&2
        fi
    fi

    if [ "$maintenance_ok" = "1" ] && [ "${SYNC_APPROACH_ANGLES_ON_STARTUP:-1}" = "1" ]; then
        angle_source="${STATCAST_SEED_PATH:-data/production_statcast_2026.csv.gz}"
        if [ -f "$angle_source" ]; then
            if ! flask --app wsgi statcast backfill-approach-angles --csv-path "$angle_source"; then
                echo "Some approach angles could not be backfilled; saved values retained." >&2
            fi
        elif ! flask --app wsgi statcast backfill-approach-angles; then
            echo "Some approach angles could not be backfilled; saved values retained." >&2
        fi
    fi

    if [ "$maintenance_ok" = "1" ] && [ "${SYNC_VAA_ADJ_ON_STARTUP:-1}" = "1" ]; then
        if ! flask --app wsgi statcast backfill-vaa-adj; then
            echo "VAAAdj backfill unavailable; saved values retained." >&2
        fi
    fi

    if [ "$maintenance_ok" = "1" ] && [ "${SYNC_HAAAA_ON_STARTUP:-1}" = "1" ]; then
        if ! flask --app wsgi statcast backfill-haaaa; then
            echo "HAAAA backfill unavailable; saved values retained." >&2
        fi
    fi

    if [ "$maintenance_ok" = "1" ] && [ "${SYNC_RUN_VALUE_ON_STARTUP:-1}" = "1" ]; then
        if ! flask --app wsgi statcast refresh-run-values; then
            echo "Some Savant run values could not be refreshed; saved values retained." >&2
        fi
    fi

    if [ "$maintenance_ok" = "1" ] && [ "${SYNC_FANGRAPHS_ON_STARTUP:-1}" = "1" ]; then
        if ! flask --app wsgi fangraphs seed-if-needed; then
            echo "FanGraphs snapshot import unavailable." >&2
        fi
        if ! flask --app wsgi fangraphs sync --timeout 120; then
            echo "FanGraphs refresh unavailable; existing grades retained." >&2
        fi
    fi

    if [ "$maintenance_ok" = "1" ] && [ "${SYNC_PUBLISHED_ON_STARTUP:-1}" = "1" ]; then
        echo "Refreshing independently published FanGraphs and Baseball Savant pitching metrics."
        if ! flask --app wsgi published sync --season "${PUBLISHED_SEASON:-2026}" --timeout 90; then
            echo "One or more published pitching sources were unavailable; cached results retained." >&2
        fi
    fi

    if [ "$maintenance_ok" = "1" ] && [ "${SYNC_RECENT_ON_STARTUP:-0}" = "1" ]; then
        echo "Starting recent Statcast sync in the background."
        if flask --app wsgi statcast sync-recent \
            --lookback-days "${SYNC_RECENT_LOOKBACK_DAYS:-4}"; then
            echo "Background Statcast sync finished successfully."
            if [ "${SYNC_WOBA_ON_STARTUP:-1}" = "1" ]; then
                if ! flask --app wsgi statcast backfill-woba; then
                    echo "Some new Savant wOBA outcomes remain unverified." >&2
                fi
            fi
        else
            echo "Background Statcast sync failed; the web service will remain available." >&2
        fi
    fi
) &

exec "$@"
