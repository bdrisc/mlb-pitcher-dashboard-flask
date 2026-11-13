"""Filterable, independently computed run-prevention estimates.

FIP and xFIP use their published event formulas and the 2026 FanGraphs cFIP.
SIERA uses the published 2011 FanGraphs equation coefficients but without
unpublished 2026 season and start/relief adjustments; it is NOT an exact
FanGraphs reproduction. xERA is an explicit ERA-scale xwOBA proxy:
Savant does not publish its complete conversion.
The source-specific comparability caveats are returned to the UI.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# FanGraphs Guts! 2026 cFIP: https://www.fangraphs.com/tools/guts?type=cn
# 2026 league-wide MLB Statcast totals: 5,575 HR, 124,611 BBE,
# 26.7% fly balls and 7.3% popups. Not a 50-pitcher cohort.
# Source: https://baseballsavant.mlb.com/league?season=2026
# This is the ALL-MLB 2026 HR/FB implied by the rounded public percentages,
# not FanGraphs' unrounded internal denominator. Precision is approximate.
# SIERA coefficients source: https://blogs.fangraphs.com/
# new-siera-part-two-of-five-unlocking-underrated-pitching-skills/
SEASON_BASELINES = {
    2026: {
        "fip_constant": 3.081,
        "hr_fb_rate": 5575 / (124611 * (0.267 + 0.073)),
        "hr_fb_source": (
            "2026 all-MLB Baseball Savant league totals: 5,575 HR / "
            "(124,611 BBE × (26.7% FB + 7.3% PU)); rate is "
            "approximate because batted-ball percentages are rounded"
        ),
        "lg_era": 4.17,
        "lg_woba": 0.316,
        "woba_scale": 1.259,
        "pa_per_nine": 37.84,
    }
}


def _two(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def calculate_run_prevention(counts: dict, season: int | None, xwoba: float | None):
    """Return rates and auditable inputs for the currently filtered PA sample."""
    baseline = SEASON_BASELINES.get(season)
    outs = int(counts.get("outs", 0))
    pa = int(counts.get("pa", 0))
    k = int(counts.get("strikeouts", 0))
    bb = int(counts.get("walks", 0))
    hbp = int(counts.get("hbp", 0))
    hr = int(counts.get("homers", 0))
    fb = int(counts.get("fly_balls", 0))
    gb = int(counts.get("ground_balls", 0))
    pu = int(counts.get("popups", 0))
    classified = int(counts.get("classified_batted_balls", 0))
    bbe = int(counts.get("contact_events", 0))
    innings = outs / 3

    result = {
        "fip": None,
        "xfip": None,
        "siera": None,
        "xera": None,
        "rp_outs": outs,
        "rp_innings": round(innings, 3),
        "rp_pa": pa,
        "rp_k": k,
        "rp_bb": bb,
        "rp_hbp": hbp,
        "rp_hr": hr,
        "rp_fb": fb,
        "rp_gb": gb,
        "rp_pu": pu,
        "rp_classified_bbe": classified,
        "rp_bbe": bbe,
        "rp_fip_constant": None if baseline is None else baseline["fip_constant"],
        "rp_league_hr_fb": None if baseline is None else baseline["hr_fb_rate"],
        "rp_hr_fb_source": None if baseline is None else baseline["hr_fb_source"],
        "rp_xera_method": "ERA-scale xwOBA proxy; not official Savant xERA",
        "rp_siera_method": (
            "FanGraphs 2011 revised coefficients; 2026 season calibration and "
            "starter/reliever innings correction unavailable, so not FG-exact"
        ),
        "rp_outs_method": "outs from PA-ending events; non-PA baserunner outs may be missing",
    }
    if baseline is None:
        return result

    classification_coverage = classified / bbe if bbe else 0
    result["rp_bbe_coverage_pct"] = round(100 * classification_coverage, 1)

    if outs > 0:
        numerator = 13 * hr + 3 * (bb + hbp) - 2 * k
        result["fip"] = _two(numerator / innings + baseline["fip_constant"])
        if classification_coverage >= 0.98 and fb:
            x_numerator = 13 * fb * baseline["hr_fb_rate"] + 3 * (bb + hbp) - 2 * k
            result["xfip"] = _two(x_numerator / innings + baseline["fip_constant"])

    # Revised published FanGraphs SIERA (2011) uses netGB = GB - FB,
    # with popups included in fly balls. The quadratic term changes sign
    # with netGB. Its published 2011 starter coefficient (+0.367 × SP IP%)
    # and a *year-specific* intercept are NOT applied here because neither
    # can be accurately reconstructed for a selected PA sample with the
    # currently stored data. Never describe this as official FG SIERA.
    if pa > 0 and classification_coverage >= 0.98 and bbe > 0:
        k_rate = k / pa
        bb_rate = bb / pa
        net = (gb - fb) / pa
        result["siera"] = _two(
            5.534
            - 15.518 * k_rate
            + 9.146 * k_rate**2
            + 8.648 * bb_rate
            + 27.252 * bb_rate**2
            - 2.298 * net
            - 4.920 * net * abs(net)
            - 4.036 * k_rate * bb_rate
            + 5.155 * k_rate * net
            + 4.546 * bb_rate * net
        )

    # Published ERA-equivalent linear-weight identity. Baseball Savant does not
    # document the specific transformation used by its official xERA displays.
    if xwoba is not None:
        delta = (xwoba - baseline["lg_woba"]) / baseline["woba_scale"]
        result["xera"] = _two(max(0, baseline["lg_era"] + delta * baseline["pa_per_nine"]))

    return result
