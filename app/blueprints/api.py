"""Versioned JSON and chart routes for pitch analysis."""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models import Game, IngestionRun, Pitch
from app.services.filters import FilterValidationError, parse_pitch_filters
from app.services.pitch_data import PitchDataStore
from app.services.pitcher_charts import build_pitcher_chart_data
from app.services.pitcher_profiles import (
    NoMatchingPitchesError,
    PitcherNotFoundError,
    build_pitcher_profile,
    list_pitchers,
)
from app.services.plots import render_movement_plot

api_blueprint = Blueprint("api", __name__)


def _store() -> PitchDataStore:
    return current_app.extensions["pitch_data_store"]


def _unavailable_response(store: PitchDataStore):
    return (
        jsonify(
            {
                "error": "data_unavailable",
                "message": store.error or "Pitch data have not been loaded.",
            }
        ),
        503,
    )


@api_blueprint.errorhandler(FilterValidationError)
def invalid_filters(error: FilterValidationError):
    return (
        jsonify(
            {
                "error": "validation_error",
                "message": str(error),
                "details": error.errors,
            }
        ),
        400,
    )


@api_blueprint.errorhandler(PitcherNotFoundError)
def pitcher_not_found(error: PitcherNotFoundError):
    return (
        jsonify(
            {
                "error": "not_found",
                "message": str(error),
                "pitcher_id": error.pitcher_id,
            }
        ),
        404,
    )


@api_blueprint.errorhandler(NoMatchingPitchesError)
def no_matching_profile_pitches(error: NoMatchingPitchesError):
    return (
        jsonify(
            {
                "error": "not_found",
                "message": str(error),
                "pitcher_id": error.pitcher_id,
                "query": error.query,
            }
        ),
        404,
    )


@api_blueprint.get("/health")
def health():
    store = _store()
    database_status = "ok"
    database_error = None
    database_pitch_count = None
    try:
        db.session.execute(text("SELECT 1"))
        database_pitch_count = db.session.scalar(select(func.count(Pitch.pitch_id)))
    except SQLAlchemyError:
        db.session.rollback()
        database_status = "unavailable"
        database_error = "The database connection is unavailable."
        current_app.logger.exception("Database readiness check failed")

    ready = store.available and database_status == "ok"
    status_code = 200 if ready else 503
    database_has_pitches = bool(database_pitch_count)
    active_source = (
        Path(current_app.config["STATCAST_SEED_PATH"]).name
        if database_has_pitches
        else store.source_name
    )
    active_pitch_count = database_pitch_count if database_has_pitches else store.row_count
    return (
        jsonify(
            {
                "status": "ok" if ready else "degraded",
                "environment": current_app.config["APP_ENV"],
                "version": current_app.config["APP_VERSION"],
                "database_status": database_status,
                "database_pitch_count": database_pitch_count,
                "data_source": active_source,
                "source_pitch_count": active_pitch_count,
                "pitch_count": active_pitch_count,
                "error": database_error or store.error,
            }
        ),
        status_code,
    )


@api_blueprint.get("/pitchers")
def pitchers():
    filters = parse_pitch_filters(request.args)
    latest_game_date = db.session.scalar(select(func.max(Game.game_date)))
    latest_ingestion = db.session.scalar(
        select(func.max(IngestionRun.finished_at)).where(IngestionRun.status == "succeeded")
    )
    return jsonify(
        {
            "query": filters.to_dict(),
            "pitchers": list_pitchers(filters),
            "data_freshness": {
                "latest_game_date": (
                    latest_game_date.isoformat() if latest_game_date is not None else None
                ),
                "last_ingested_at": (
                    latest_ingestion.isoformat() if latest_ingestion is not None else None
                ),
            },
        }
    )


@api_blueprint.get("/pitchers/<int:pitcher_id>/profile")
def pitcher_profile(pitcher_id: int):
    filters = parse_pitch_filters(request.args, forbidden=frozenset({"pitcher"}))
    return jsonify(build_pitcher_profile(pitcher_id, filters))


@api_blueprint.get("/pitchers/<int:pitcher_id>/charts")
def pitcher_charts(pitcher_id: int):
    filters = parse_pitch_filters(request.args, forbidden=frozenset({"pitcher"}))
    return jsonify(build_pitcher_chart_data(pitcher_id, filters))


@api_blueprint.get("/pitches")
def pitch_summary():
    store = _store()
    if not store.available:
        return _unavailable_response(store)

    filters = parse_pitch_filters(request.args)
    filtered = store.filter(**filters.dataframe_kwargs())
    if filtered.empty:
        return (
            jsonify(
                {
                    "error": "not_found",
                    "message": "No pitches matched the supplied filters.",
                    "query": filters.to_dict(),
                }
            ),
            404,
        )

    summary = store.summarize(filtered)
    return jsonify(
        {
            "query": filters.to_dict(),
            "matching_pitches": int(len(filtered)),
            "results": summary,
        }
    )


@api_blueprint.get("/plots/movement")
def movement_plot():
    store = _store()
    if not store.available:
        return _unavailable_response(store)

    filters = parse_pitch_filters(request.args, require_pitcher=True)
    filtered = store.filter(**filters.dataframe_kwargs())
    filtered = filtered.dropna(subset=["horizontal_break", "vertical_break"])
    if filtered.empty:
        return (
            jsonify(
                {
                    "error": "not_found",
                    "message": "No movement data matched the supplied filters.",
                }
            ),
            404,
        )

    image = render_movement_plot(filtered, filters.pitcher)
    return send_file(
        image,
        mimetype="image/png",
        download_name="pitch-movement.png",
        max_age=0,
    )
