from app.services.filters import PitchFilters
from app.services.pitch_roles import (
    ROLE_FIELDS,
    build_pitch_roles,
    count_key,
    filter_count_key,
    percentile,
    role_values,
)


def test_unrounded_and_qualification():
    row = dict.fromkeys(ROLE_FIELDS, 0)
    row.update(
        physical_pitch_count=150,
        role_regular_pitches=150,
        first_pitch_opportunities=60,
        first_pitch_strikes=41,
        swings=80,
        whiffs=27,
        gb_count=12,
        fb_count=0,
        run_value_denominator=150,
        run_value_pitches=149,
        run_value_against=-3,
        xrv_scored_pitches=149,
        xrv_paired_expected=4,
    )
    result = role_values(row)
    assert result["first_pitch_strike_pct"]["value"] == 100 * 41 / 60
    assert result["whiff_pct"]["qualified"]
    assert not result["gb_pct"]["qualified"]
    assert result["run_value_per_100"]["value"] is None
    assert not result["expected_run_value_per_100"]["qualified"]


def test_midrank_and_minimum_peers():
    assert percentile(1, [1] * 20) == 50
    assert percentile(1, [1] * 19) is None
    assert percentile(0, [1] * 20) == 0
    assert percentile(2, [1] * 20) == 100


def test_count_scope():
    assert filter_count_key(PitchFilters(count_group="two_strikes")) == count_key(
        [(b, 2) for b in range(4)]
    )
    assert filter_count_key(PitchFilters(balls=0, strikes=0)) == "0-0"


def test_missing_reference_never_falls_back():
    row = dict.fromkeys(ROLE_FIELDS, 0)
    row.update(physical_pitch_count=100, role_regular_pitches=100, swings=80, whiffs=40)
    result = build_pitch_roles(
        [{"pitch_type": "SL", "role_values": role_values(row)}], PitchFilters(season=1900), "R"
    )
    whiff = result["rows"][1]
    assert whiff["cells"][0]["value"] == 50
    assert whiff["cells"][0]["percentile"] is None
    assert whiff["most_effective"] == ["SL"]
    assert whiff["best_vs_peers"] == []


def test_exact_hand_pitch_side_count_matching(tmp_path, monkeypatch):
    import json

    import app.services.pitch_roles as roles

    monkeypatch.setattr(roles, "REFERENCE_DIR", tmp_path)
    masks = filter_count_key(PitchFilters(season=2026, batter_sides=("R",)))
    k = roles.peer_key("SL", "R", "R", masks, "whiff_pct")
    other = roles.peer_key("SL", "L", "R", masks, "whiff_pct")
    all_side = roles.peer_key("SL", "R", "ALL", masks, "whiff_pct")
    path = roles.reference_path(2026)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "season": 2026,
                "pitchers": 800,
                "physical_pitches": 700000,
                "games": 2430,
                "through": "2026-09-27",
                "distributions": {k: [25] * 20, other: [75] * 20, all_side: [50] * 20},
            }
        )
    )
    row = dict.fromkeys(ROLE_FIELDS, 0)
    row.update(physical_pitch_count=100, role_regular_pitches=100, swings=80, whiffs=40)
    arsenal = [{"pitch_type": "SL", "role_values": role_values(row)}]

    def result(filters, hand):
        return build_pitch_roles(arsenal, filters, hand)["rows"][1]["cells"][0]["percentile"]

    assert result(PitchFilters(season=2026, batter_sides=("R",)), "R") == 100
    assert result(PitchFilters(season=2026, batter_sides=("R",)), "L") == 0
    assert result(PitchFilters(season=2026), "R") == 50
    assert result(PitchFilters(season=2026, batter_sides=("L",)), "R") is None
    assert result(PitchFilters(season=2026, strikes=2, batter_sides=("R",)), "R") is None
    assert result(PitchFilters(), "R") is None
    assert result(PitchFilters(season=2025), "R") is None


def test_reference_hash_is_independent_of_line_endings(tmp_path):
    import json
    from hashlib import sha256

    from app.services.pitch_roles import _load

    payload = {
        "version": 1,
        "season": 2026,
        "pitchers": 800,
        "physical_pitches": 700000,
        "games": 2430,
        "distributions": {"test": [1, 2, 3]},
    }
    raw = (json.dumps(payload, indent=2) + "\n").encode()
    paths = [tmp_path / "lf.json", tmp_path / "crlf.json"]
    paths[0].write_bytes(raw)
    paths[1].write_bytes(raw.replace(b"\n", b"\r\n"))
    for path in paths:
        loaded, digest = _load(str(path), path.stat().st_mtime_ns)
        assert loaded == payload
        assert digest == sha256(raw).hexdigest()
