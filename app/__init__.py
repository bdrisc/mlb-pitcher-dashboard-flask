"""Application factory for the MLB Pitch Intelligence Flask app."""

from __future__ import annotations

from flask import Flask, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix

from app.blueprints.api import api_blueprint
from app.blueprints.main import main_blueprint
from app.commands.statcast import statcast_cli
from app.config import DEVELOPMENT_SECRET, Config
from app.extensions import db, migrate
from app.services.pitch_data import PitchDataStore


def create_app(test_config: dict | None = None) -> Flask:
    """Create and configure one Flask application instance."""
    app = Flask(__name__)
    app.config.from_object(Config)

    if test_config:
        app.config.from_mapping(test_config)

    if app.config["APP_ENV"] == "production":
        if not app.config.get("SECRET_KEY") or app.config["SECRET_KEY"] == DEVELOPMENT_SECRET:
            raise RuntimeError("SECRET_KEY must be set to a non-default value in production.")
        app.config.update(
            PREFERRED_URL_SCHEME="https",
            SESSION_COOKIE_SECURE=True,
        )

    if app.config.get("BEHIND_PROXY"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    app.json.sort_keys = False

    db.init_app(app)
    migrate.init_app(app, db)

    # Import after extension initialization so migration discovery sees all models.
    from app import models  # noqa: F401

    store = PitchDataStore(app.config["PITCH_DATA_PATH"])
    store.load()
    app.extensions["pitch_data_store"] = store

    app.register_blueprint(main_blueprint)
    app.register_blueprint(api_blueprint, url_prefix="/api/v1")
    app.cli.add_command(statcast_cli)

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify({"error": "not_found", "message": "The requested route was not found."}), 404

    @app.errorhandler(500)
    def internal_error(_error):
        return (
            jsonify(
                {
                    "error": "internal_server_error",
                    "message": "The server could not complete the request.",
                }
            ),
            500,
        )

    return app
