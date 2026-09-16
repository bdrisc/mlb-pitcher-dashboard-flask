"""Server-rendered browser routes."""

from datetime import date
from pathlib import Path

from flask import Blueprint, current_app, render_template
from sqlalchemy import func, select

from app.extensions import db
from app.models import Pitch
from app.services.pitch_data import PITCH_NAME_MAP

main_blueprint = Blueprint("main", __name__)


@main_blueprint.get("/")
def index():
    store = current_app.extensions["pitch_data_store"]
    database_pitch_count = db.session.scalar(select(func.count(Pitch.pitch_id))) or 0
    database_has_pitches = database_pitch_count > 0
    return render_template(
        "index.html",
        data_status=store.status,
        pitch_count=database_pitch_count if database_has_pitches else store.row_count,
        data_source=(
            Path(current_app.config["STATCAST_SEED_PATH"]).name
            if database_has_pitches
            else store.source_name
        ),
        load_error=store.error,
    )


@main_blueprint.get("/savant-card")
def savant_card():
    return render_template(
        "savant_card.html",
        current_year=date.today().year,
        pitch_types=sorted(PITCH_NAME_MAP.items(), key=lambda item: item[1]),
    )
