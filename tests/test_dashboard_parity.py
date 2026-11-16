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



def test_pair_arrays_match_by_both_pitch_types_not_row_position():
    local = {
        "pitch_tunneling": {
            "pairs": [
                {"pitch_a": "FF", "pitch_b": "CH", "late_separation_inches": 9.4},
                {"pitch_a": "FF", "pitch_b": "SL", "late_separation_inches": 10.2},
            ]
        },
        "pitch_separation": {
            "pairs": [
                {"pitch_a": "FF", "pitch_b": "SL", "movement_gap_inches": 18.1},
                {"pitch_a": "FF", "pitch_b": "CH", "movement_gap_inches": 12.3},
            ]
        },
    }
    public = {
        "pitch_tunneling": {
            "pairs": list(reversed(local["pitch_tunneling"]["pairs"]))
        },
        "pitch_separation": {
            "pairs": list(reversed(local["pitch_separation"]["pairs"]))
        },
    }
    assert compare_profiles(local, public) == []
    public["pitch_tunneling"]["pairs"][0] = {
        "pitch_a": "FF",
        "pitch_b": "SL",
        "late_separation_inches": 10.3,
    }
    assert compare_profiles(local, public) == [
        {
            "field": "pitch_tunneling.pairs[FF->SL].late_separation_inches",
            "local": 10.2,
            "public": 10.3,
        }
    ]
