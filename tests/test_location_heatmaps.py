"""Tests for fixed-window pitch-type/batter-hand location KDEs."""

from __future__ import annotations

from app.services.location_heatmaps import KDE_MAX_PITCHES, build_location_heatmaps


def row(
    code="FF",
    name="Four-Seam Fastball",
    hand="R",
    x=0.1,
    z=2.5,
    description="called_strike",
):
    return {
        "pitch_type": code,
        "pitch_name": name,
        "batter_side": hand,
        "plate_x": x,
        "plate_z": z,
        "description": description,
    }


def test_kde_handles_identical_locations_and_rhh_lhh_empty_panels():
    heatmap = build_location_heatmaps([row() for _ in range(3)])
    assert len(heatmap["pitch_types"]) == 1
    assert heatmap["pitch_types"][0]["pitch_count"] == 3
    assert heatmap["panels"][0]["pitch_count"] == 3
    assert heatmap["panels"][0]["kde_sample_count"] == 3
    density = heatmap["panels"][0]["density"]
    assert len(density) == len(heatmap["grid"]["y"])
    assert max(v for line in density for v in line if v is not None) == 1.0
    assert heatmap["panels"][1]["pitch_count"] == 0
    assert heatmap["panels"][1]["density"] is None


def test_kde_rejects_untracked_automatic_and_unknown_handedness():
    heatmap = build_location_heatmaps(
        [row(), row(x=None), row(hand="S"), row(description="automatic_ball"), row(z=None)]
    )
    assert heatmap["pitch_types"][0]["pitch_count"] == 1
    assert heatmap["panels"][0]["density"] is None
    assert heatmap["panels"][0]["kde_sample_count"] == 0


def test_kde_uses_capped_deterministic_sample_without_losing_pitch_count():
    pitches = [
        row(x=(index % 41 - 20) / 30, z=1.5 + (index % 61) / 35)
        for index in range(KDE_MAX_PITCHES + 3)
    ]
    heatmap = build_location_heatmaps(pitches)
    panel = heatmap["panels"][0]
    assert panel["pitch_count"] == KDE_MAX_PITCHES + 3
    assert panel["kde_sample_count"] == KDE_MAX_PITCHES
    assert panel["density"] is not None


def test_kde_orders_pitch_types_by_eligible_usage():
    pitches = [
        row("FF", "Four-Seam Fastball", "R"),
        row("FF", "Four-Seam Fastball", "L"),
        row("SL", "Slider", "R"),
        row("SL", "Slider", "L"),
        row("SL", "Slider", "L"),
    ]
    heatmap = build_location_heatmaps(pitches)
    assert [pitch["pitch_type"] for pitch in heatmap["pitch_types"]] == ["SL", "FF"]
    assert [pitch["pitch_count"] for pitch in heatmap["pitch_types"]] == [3, 2]
    assert [(panel["pitch_type"], panel["batter_side"]) for panel in heatmap["panels"]] == [
        ("SL", "R"),
        ("SL", "L"),
        ("FF", "R"),
        ("FF", "L"),
    ]
