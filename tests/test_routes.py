"""Application-factory, API, filtering, and plot route tests."""

import re


def test_factory_serves_the_jinja_homepage(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"MLB Pitcher Dashboard" in response.data
    assert b"3" in response.data


def test_homepage_links_to_the_savant_card(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b'href="/savant-card"' in response.data


def test_savant_card_serves_the_database_backed_dashboard_shell(client):
    response = client.get("/savant-card")

    assert response.status_code == 200
    assert b"<h1>MLB Pitcher Dashboard</h1>" in response.data
    assert (
        b"A filterable dashboard built from pitch-level Statcast data in PostgreSQL."
        not in response.data
    )
    assert b"Performance Metrics" in response.data
    assert b"K-BB%" in response.data
    assert b'data-metric="woba_against"' in response.data
    assert b"xwOBA" in response.data
    assert b'data-metric="xslg"' in response.data
    assert b'class="overview-groups"' in response.data
    assert b"Whiff and Finishing" in response.data
    assert b"Contact Quality Allowed" in response.data
    assert b"Plate-appearance results" not in response.data
    assert b"Movement is reported in inches." not in response.data
    assert b"Results against right- and left-handed batters." not in response.data
    assert b'class="eyebrow"' not in response.data
    assert b'data-pitchers-url="/api/v1/pitchers"' in response.data
    assert b'id="profile-filters"' in response.data
    assert b'id="pitcher-select"' in response.data
    assert b'id="database-freshness"' in response.data
    assert b'id="arsenal-body"' in response.data
    assert b'id="platoon-splits"' in response.data
    assert b"Times Through the Order Splits" in response.data
    assert b'id="tto-performance-body"' in response.data
    assert b'id="tto-mix-rows"' in response.data
    assert b'data-tto-view="performance"' in response.data
    assert b'data-tto-view="mix"' in response.data
    assert response.data.index(b'id="platoon-splits"') < response.data.index(
        b'id="tto-performance-body"'
    )
    assert b"3rd vs. 1st" not in response.data
    assert b'class="overview-values overview-rate-values"' in response.data
    assert b'class="overview-values overview-outcome-values"' in response.data
    assert b'class="overview-values overview-rv-values"' in response.data
    assert b'class="metric-card' not in response.data
    assert (
        response.data.index(b'data-metric="strikeout_pct"')
        < response.data.index(b'data-metric="walk_pct"')
        < response.data.index(b'data-metric="k_minus_bb_pct"')
    )
    assert response.data.count(b'data-metric="run_value_per_100"') == 1
    assert response.data.count(b'data-metric="expected_run_value_per_100"') == 1
    assert b"Run Value vs. Expected" not in response.data
    assert b'id="xrv-quality-note"' not in response.data
    assert b"methodology and validation" not in response.data
    assert b'data-metric="run_value_minus_expected"' not in response.data
    assert b'data-metric="run_value_minus_expected_per_100"' not in response.data
    assert b'data-metric="paired_actual_run_value_per_100"' not in response.data
    assert b">Paired RV/100</th>" not in response.data
    assert b">\xce\x94RV/100</th>" not in response.data
    assert b">xRV/100</th>" in response.data
    assert response.data.count(b'data-metric="') == 33
    for metric in (b"gb_pct", b"fb_pct", b"ld_pct", b"pu_pct"):
        assert b'data-metric="' + metric + b'"' in response.data
    assert b"Batted-Ball Profile" in response.data
    assert b">Spin Axis</th>" in response.data
    assert b'class="spin-efficiency-heading"' in response.data
    assert (
        b'<span class="spin-efficiency-line">Spin</span> '
        b'<span class="spin-efficiency-line">Efficiency</span>'
    ) in response.data
    assert b'data-mobile-label="Spin Efficiency"' in response.data
    assert (
        response.data.index(b">Spin Axis</th>")
        < response.data.index(b'class="spin-efficiency-heading"')
        < response.data.index(b">Arm Angle</th>")
    )
    assert b'class="perceived-velocity-heading"' in response.data
    assert b'data-mobile-label="Perceived Velocity"' in response.data
    assert b'<span class="perceived-velocity-line">Perceived</span>' in response.data
    assert b'<span class="perceived-velocity-line">Velocity</span>' in response.data
    assert b">Arm Angle</th>" in response.data
    assert b">Release Height</th>" in response.data
    assert b">Release Side</th>" in response.data
    assert b">Extension</th>" in response.data
    assert b">Release SD</th>" in response.data
    assert (
        response.data.index(b">Extension</th>")
        < response.data.index(b">Release Height</th>")
        < response.data.index(b">Release Side</th>")
    )
    assert response.data.count(b'class="plotly-chart') == 4
    assert b"Location by Pitch Type and Batter Handedness" in response.data
    assert b'id="location-heatmap-grid"' in response.data
    assert b"location-heatmap-column-headings" not in response.data
    assert b"<h3>Pitch Location</h3>" not in response.data
    assert b'id="location-chart"' not in response.data
    assert b"Velocity and Movement Changes by Inning" in response.data
    assert b'id="inning-metric"' in response.data
    assert b'<option value="velocity">Velocity</option>' in response.data
    assert b'<option value="hb">Horizontal Break (HB)</option>' in response.data
    assert b'<option value="ivb">Induced Vertical Break (IVB)</option>' in response.data
    assert b'id="inning-display-mode"' in response.data
    assert b'id="inning-chart-grid"' in response.data
    assert b'id="inning-pitch-type"' not in response.data
    assert b'id="inning-velocity-chart"' not in response.data
    assert b"Inning 1 is the pitcher" not in response.data
    assert b"Avg Exit Velo" in response.data
    assert b"Pitch-type performance" not in response.data
    assert b"Metric definitions and sample notes" not in response.data
    assert b'data-charts-url-template="/api/v1/pitchers/0/charts"' in response.data
    assert b"plotly-4.0.0.min.js" in response.data


def test_arsenal_shape_views_show_all_metrics_without_crowding(client):
    response = client.get("/savant-card")
    page = response.get_data(as_text=True)

    assert '<option value="shape-overview" selected>Pitch Shape Overview</option>' in page
    assert '<option value="shape-release">Release &amp; Spin</option>' in page
    assert '<option value="shape-movement">Movement &amp; Angles</option>' in page
    assert '<option value="grades">FanGraphs Grades</option>' in page
    assert '<option value="results">Results</option>' in page
    assert page.index('<option value="grades">') < page.index('<option value="results">')

    headings = re.findall(r"<th\b([^>]*)>(.*?)</th>", page, flags=re.S)
    membership = {}
    for attributes, content in headings:
        view = re.search(r'data-view="([^"]+)"', attributes)
        if view is None or "shape-" not in view.group(1):
            continue
        label = " ".join(re.sub(r"<[^>]+>", " ", content).split())
        membership[label] = set(view.group(1).split())

    expected = {
        "shape-overview": {
            "Velo",
            "Spin",
            "Release Height",
            "Release Side",
            "Extension",
            "HB",
            "IVB",
        },
        "shape-release": {
            "Velo",
            "Perceived Velocity",
            "Max",
            "Spin",
            "Spin Axis",
            "Spin Efficiency",
            "Arm Angle",
            "Release Height",
            "Release Side",
            "Extension",
            "Release SD",
        },
        "shape-movement": {
            "HB",
            "IVB",
            "HB vs. AVG",
            "IVB vs. AVG",
            "VAA",
            "VAAAdj",
            "HAA",
            "HAAAA",
        },
    }
    shared_order = [re.sub(r"<[^>]+>", "", content).strip() for _, content in headings[:3]]
    assert shared_order == ["Pitch", "#", "Usage"]
    assert len(membership) == 19
    for view, expected_labels in expected.items():
        assert {label for label, views in membership.items() if view in views} == expected_labels
    assert [label for label, views in membership.items() if "shape-overview" in views] == [
        "Velo",
        "Spin",
        "HB",
        "IVB",
        "Extension",
        "Release Height",
        "Release Side",
    ]

    # All 19 shape columns exist exactly once; the selector reorders Extension
    # by view. Shared Pitch / # / Usage, Results, and Grades stay intact.
    assert 'data-view="shape"' not in page
    assert len(re.findall(r'<th\b[^>]*data-view="results"', page)) == 11
    assert len(re.findall(r'<th\b[^>]*data-view="grades"', page)) == 3


def test_performance_metrics_use_uniform_cards_without_accent_strips(client):
    response = client.get("/static/styles.css")

    assert response.status_code == 200
    assert b".overview-rate-values" in response.data
    assert (
        b"grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr));" in response.data
    )
    assert b".location-pitch-panels {" in response.data
    assert b".plotly-chart.location-heatmap-plot {" in response.data
    assert b".arsenal-table.responsive-table th.spin-efficiency-heading" in response.data
    assert b".spin-efficiency-heading .spin-efficiency-line" in response.data
    assert b".perceived-velocity-heading .perceived-velocity-line" in response.data
    assert b"white-space: nowrap;" in response.data
    assert b".location-heatmap-panel {" in response.data
    assert b"max-width: 100%;" in response.data
    assert b"overflow: hidden;" in response.data
    assert b"height: 210px;" in response.data
    assert b"min-height: 210px;" in response.data
    assert b".location-heatmap-column-headings" not in response.data
    assert b".plotly-chart.inning-chart {" in response.data
    assert b"height: 280px;" in response.data
    assert b"min-height: 280px;" in response.data
    assert b".inning-chart-grid > .chart-card:last-child:nth-child(odd)" in response.data
    assert b".overview-outcome-values" in response.data
    assert b".overview-rv-values" in response.data
    assert b".compact-metric strong" in response.data
    assert b".metric-card::before" not in response.data
    assert b"min-height: 108px;" not in response.data
    assert b"grid-template-rows: 2.25rem" not in response.data
    assert b"flex-direction: column;" in response.data


def test_savant_card_javascript_is_served_as_a_static_asset(client):
    response = client.get("/static/savant-card.js")

    assert response.status_code == 200
    assert response.mimetype in {"application/javascript", "text/javascript"}
    assert b"/profile" in response.data
    assert b"URLSearchParams" in response.data
    assert b"heading.dataset.view.split(/\\s+/).includes(view)" in response.data
    assert b'formatMetric("release_point_sd_inches"' in response.data
    assert b'formatMetric("release_extension"' in response.data
    assert response.data.index(b'formatMetric("release_extension"') < response.data.index(
        b'formatMetric("avg_release_height"'
    ) < response.data.index(b'formatMetric("avg_release_side"')
    assert b'moveArsenalColumnBefore("Extension", "Arm Angle")' in response.data
    assert b'moveArsenalColumnBefore("Extension", "Release Height")' in response.data
    assert b'formatMetric("avg_spin_axis"' in response.data
    assert b'formatMetric("avg_effective_velocity"' in response.data
    assert b"function renderTtoSplits(tto)" in response.data
    assert b"function selectTtoView(view)" in response.data
    assert b"renderTtoSplits(profile.times_through_order_splits)" in response.data
    assert b"ArrowRight" in response.data
    assert response.data.index(b'formatMetric("avg_velocity"') < response.data.index(
        b'formatMetric("avg_effective_velocity"'
    )
    assert b'formatMetric("spin_efficiency_pct"' in response.data
    assert response.data.index(b"tableCell(row, Number(pitch.pitch_count)") < response.data.index(
        b'tableCell(row, formatMetric("usage_pct"'
    )
    assert response.data.index(
        b'tableCell(row, formatMetric("horizontal_break"'
    ) < response.data.index(b'tableCell(row, formatMetric("avg_release_height"')
    assert b"Full-season reference, NOT recalculated" in response.data

    charts_response = client.get("/static/savant-card-charts.js")
    assert charts_response.status_code == 200
    assert charts_response.mimetype in {"application/javascript", "text/javascript"}
    assert b"window.Plotly.react" in charts_response.data
    assert b"renderLocationHeatmaps" in charts_response.data
    assert b"autosize: false" in charts_response.data
    assert b"width: panelWidth" in charts_response.data
    assert b"new ResizeObserver(" in charts_response.data
    assert b"window.Plotly.relayout(plot, { width })" in charts_response.data
    assert b"height: 210" in charts_response.data
    assert b"caption.append(batterSide, sample)" in charts_response.data
    assert b"location_heatmaps" in charts_response.data
    assert b"locationTraces(" not in charts_response.data
    assert b"inning_progression" in charts_response.data
    assert b"renderInningCharts" in charts_response.data
    assert b"orderedPitches.map" in charts_response.data
    assert b"b.pitch_count - a.pitch_count" in charts_response.data
    assert b"height: 280" in charts_response.data
    assert b"t: 14, b: 38" in charts_response.data
    assert b"const maxInning = inningData.rows.reduce(" in charts_response.data
    assert b"range: [0.5, maxInning + 0.5]" in charts_response.data
    assert b"inningMetricSelect.addEventListener" in charts_response.data
    assert b"inningPitchSelect" not in charts_response.data


def test_health_reports_the_loaded_dataset(client):
    response = client.get("/api/v1/ready")

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


def test_liveness_does_not_query_an_unavailable_database(client, monkeypatch):
    from app.extensions import db

    def fail_query(*args, **kwargs):
        raise AssertionError("Liveness must not query the database")

    monkeypatch.setattr(db.session, "execute", fail_query)
    monkeypatch.setattr(db.session, "scalar", fail_query)

    for path in ("/api/v1/live", "/api/v1/health"):
        response = client.get(path)

        assert response.status_code == 200
        assert response.json == {"status": "ok", "version": "test"}


def test_published_pitching_explanatory_paragraphs_are_not_displayed(client):
    html = client.get("/savant-card").get_data(as_text=True)
    js = client.get("/static/savant-card.js").get_data(as_text=True)

    assert "run-prevention-note" not in html
    assert "Official published pitcher-season values from FanGraphs" not in html
    assert "FanGraphs handedness metrics are full-season references" not in js
    assert "sourceNote" not in js
    assert 'data-metric="fip"' in html
    assert 'data-metric="xera"' in html


def test_dashboard_stat_alignment_css_applies_to_desktop_and_mobile(client):
    response = client.get("/static/styles.css")
    assert response.status_code == 200
    css = response.get_data(as_text=True)
    assert ".dashboard-shell .arsenal-table th," in css
    assert ".dashboard-shell .arsenal-table td," in css
    assert ".dashboard-shell .responsive-table tbody td {" in css
    assert ".dashboard-shell .pitch-label {" in css
    assert ".dashboard-shell .compact-metric," in css
    assert ".dashboard-shell .metric-card," not in css
    assert ".dashboard-shell .split-card dl > div {" in css
    assert ".dashboard-shell .dashboard-section > .section-heading {" in css
    assert "grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);" in css
    assert "@media (max-width: 800px) {" in css
