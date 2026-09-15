"""Server-rendered browser routes."""

from datetime import date

from flask import Blueprint, current_app, render_template

from app.services.pitch_data import PITCH_NAME_MAP

main_blueprint = Blueprint("main", __name__)


@main_blueprint.get("/")
def index():
    store = current_app.extensions["pitch_data_store"]
    return render_template(
        "index.html",
        data_status=store.status,
        pitch_count=store.row_count,
        data_source=store.source_name,
        load_error=store.error,
    )


@main_blueprint.get("/savant-card")
def savant_card():
    return render_template(
        "savant_card.html",
        current_year=date.today().year,
        pitch_types=sorted(PITCH_NAME_MAP.items(), key=lambda item: item[1]),
    )
