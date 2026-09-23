"""Application-factory, API, filtering, and plot route tests."""


def test_factory_serves_the_jinja_homepage(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"MLB Pitch Intelligence" in response.data
    assert b"3" in response.data


def test_homepage_links_to_the_savant_card(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b'href="/savant-card"' in response.data


def test_savant_card_serves_the_database_backed_dashboard_shell(client):
    response = client.get("/savant-card")

    assert response.status_code == 200
    assert b"Savant Card" in response.data
    assert b'data-pitchers-url="/api/v1/pitchers"' in response.data
    assert b'id="profile-filters"' in response.data
    assert b'id="pitcher-select"' in response.data
    assert b'id="database-freshness"' in response.data
    assert b'id="arsenal-body"' in response.data
    assert b'id="platoon-splits"' in response.data
    assert response.data.count(b'data-metric="') == 10
    assert response.data.count(b'class="plotly-chart"') == 5
    assert b"Avg exit velo" in response.data
    assert b"Pitch-type performance" not in response.data
    assert b"Metric definitions and sample notes" not in response.data
    assert b'data-charts-url-template="/api/v1/pitchers/0/charts"' in response.data
    assert b"plotly-4.0.0.min.js" in response.data


def test_savant_card_javascript_is_served_as_a_static_asset(client):
    response = client.get("/static/savant-card.js")

    assert response.status_code == 200
    assert response.mimetype in {"application/javascript", "text/javascript"}
    assert b"/profile" in response.data
    assert b"URLSearchParams" in response.data

    charts_response = client.get("/static/savant-card-charts.js")
    assert charts_response.status_code == 200
    assert charts_response.mimetype in {"application/javascript", "text/javascript"}
    assert b"window.Plotly.react" in charts_response.data


def test_health_reports_the_loaded_dataset(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json["status"] == "ok"
    assert response.json["database_status"] == "ok"
    assert response.json["database_pitch_count"] == 0
    assert response.json["environment"] == "test"
    assert response.json["version"] == "test"
    assert response.json["pitch_count"] == 3
    assert response.json["source_pitch_count"] == 3


def test_pitcher_directory_is_database_backed(client):
    response = client.get("/api/v1/pitchers")

    assert response.status_code == 200
    assert response.json == {
        "pitchers": [],
        "query": {},
        "data_freshness": {
            "latest_game_date": None,
            "last_ingested_at": None,
        },
    }


def test_pitch_summary_applies_combined_filters(client):
    response = client.get(
        "/api/v1/pitches",
        query_string={"pitcher": "sample", "pitch_type": "Four-Seam Fastball"},
    )

    assert response.status_code == 200
    assert response.json["matching_pitches"] == 2
    assert response.json["results"][0]["avg_velocity"] == 96.0
    assert response.json["results"][0]["horizontal_break"] == -10.2


def test_pitch_summary_uses_normalized_multivalue_filters(client):
    response = client.get(
        "/api/v1/pitches",
        query_string={
            "team": "bos",
            "pitch_type": "FF, slider",
            "batter_side": "left",
            "season": "2026",
            "balls": "0",
            "strikes": "2",
            "home_away": "H",
        },
    )

    assert response.status_code == 200
    assert response.json["matching_pitches"] == 1
    assert response.json["query"] == {
        "team": "BOS",
        "pitch_type": ["FF", "SL"],
        "batter_side": ["L"],
        "season": 2026,
        "balls": 0,
        "strikes": 2,
        "home_away": "home",
    }


def test_pitch_summary_rejects_unknown_filters(client):
    response = client.get("/api/v1/pitches?pitc_type=FF")

    assert response.status_code == 400
    assert response.json == {
        "error": "validation_error",
        "message": "Invalid query parameters.",
        "details": {"pitc_type": ["is not a supported filter"]},
    }


def test_pitch_summary_rejects_an_invalid_date_range(client):
    response = client.get("/api/v1/pitches?date_from=2026-08-01&date_to=2026-04-01")

    assert response.status_code == 400
    assert response.json["details"] == {"date_range": ["date_from must be on or before date_to"]}


def test_pitch_summary_applies_inclusive_date_filters(client):
    response = client.get("/api/v1/pitches?date_from=2026-04-15&date_to=2026-05-01")

    assert response.status_code == 200
    assert response.json["matching_pitches"] == 1
    assert response.json["query"] == {
        "date_from": "2026-04-15",
        "date_to": "2026-05-01",
    }


def test_movement_plot_requires_a_pitcher(client):
    response = client.get("/api/v1/plots/movement")

    assert response.status_code == 400
    assert response.json["error"] == "validation_error"
    assert response.json["details"] == {"pitcher": ["is required"]}


def test_movement_plot_returns_png_bytes(client):
    response = client.get(
        "/api/v1/plots/movement",
        query_string={"pitcher": "Sample, Pitcher"},
    )

    assert response.status_code == 200
    assert response.content_type == "image/png"
    assert response.data.startswith(b"\x89PNG")
