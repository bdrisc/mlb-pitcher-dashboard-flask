"""Read-only local/public comparison catches drift without leaking local data."""

from scripts.check_dashboard_parity import _flatten, compare_profiles


def test_parity_ignores_row_order_and_publisher_refresh_timestamps():
    local = {
        "sample": {"pitches": 2946},
        "overall": {
            "run_value_per_100": -0.7,
            "expected_run_value_per_100": 0.0,
            "reference_savant_updated": "earlier",
        },
        "arsenal": [
            {"pitch_type": "KC", "run_value_per_100": 1.2},
            {"pitch_type": "FF", "run_value_per_100": -2.0},
        ],
    }
    public = {
        "sample": {"pitches": 2946},
        "overall": {
            "run_value_per_100": -0.7,
            "expected_run_value_per_100": 0.0,
            "reference_savant_updated": "later",
        },
        "arsenal": [
            {"pitch_type": "FF", "run_value_per_100": -2.0},
            {"pitch_type": "KC", "run_value_per_100": 1.2},
        ],
    }
    assert compare_profiles(local, public) == []
    public["overall"]["expected_run_value_per_100"] = -0.1
    assert compare_profiles(local, public) == [
        {
            "field": "overall.expected_run_value_per_100",
            "local": 0.0,
            "public": -0.1,
        }
    ]


def test_parity_reports_missing_metrics_and_count_mismatches():
    local = {
        "sample": {"pitches": 200, "games": 5},
        "overall": {"run_value_per_100": 1.0},
    }
    public = {
        "sample": {"pitches": 199, "games": 5},
        "overall": {"run_value_per_100": 1.1, "expected_run_value_per_100": 0.8},
    }
    fields = {item["field"] for item in compare_profiles(local, public)}
    assert fields == {
        "sample.pitches",
        "overall.run_value_per_100",
        "overall.expected_run_value_per_100",
    }


def test_fingerprint_flatten_retains_order_when_no_unique_key():
    data = {"pitch_separation": {"pairs": [{"pitch_a": "FF"}, {"pitch_a": "FF"}]}}
    assert list(_flatten(data)) == [
        ("pitch_separation.pairs[0].pitch_a", "FF"),
        ("pitch_separation.pairs[1].pitch_a", "FF"),
    ]
