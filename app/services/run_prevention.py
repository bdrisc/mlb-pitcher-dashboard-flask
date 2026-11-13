"""Filterable, independently computed run-prevention estimates.

FIP and xFIP use their published event formulas and the 2026 FanGraphs cFIP.
SIERA uses the published MLB/Baseball Prospectus equation (not the proprietary
later FanGraphs coefficients or run-environment/SP adjustment). xERA is an
explicit ERA-scale xwOBA proxy: Savant does not publish its conversion.
The source-specific comparability caveats are returned to the UI.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# Source: FanGraphs Guts!, 2026 seasonal constants.
# https://www.fangraphs.com/tools/guts?type=cn
# League 2026 HR/FB is a cohort-based approximation: measured across the
# 50 busiest 2026 Statcast pitchers in the bundled public cohort, with popups
# counted as fly balls. It is not an independently verified league-wide rate.
# Change this baseline only after sourcing the true all-MLB 2026 value.
SEASON_BASELINES = {
    2026: {
        "fip_constant": 3.081,
        "hr_fb_rate": 1025 / 8118,
        "hr_fb_source": "2026 public cohort estimate; not league-wide",
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
        "rp_siera_method": "MLB/BP published coefficients; not FanGraphs adjusted SIERA",
        "rp_outs_method": "outs from PA-ending events; non-PA baserunner outs may be missing",
    }
    if baseline is None:
        return result

    if outs > 0:
        numerator = 13 * hr + 3 * (bb + hbp) - 2 * k
        result["fip"] = _two(numerator / innings + baseline["fip_constant"])
        if classified == bbe and fb:
            x_numerator = 13 * fb * baseline["hr_fb_rate"] + 3 * (bb + hbp) - 2 * k
            result["xfip"] = _two(x_numerator / innings + baseline["fip_constant"])

    # The historical, publicly specified SIERA formula uses PA as its rate
    # denominator and treats (GB - FB - PU) as the net ground-ball count.
    if pa > 0 and classified == bbe and bbe > 0:
        k_rate = k / pa
        bb_rate = bb / pa
        net = (gb - fb) / pa
        result["siera"] = _two(
            6.145
            - 16.986 * k_rate
            + 11.434 * bb_rate
            - 1.858 * net
            + 7.653 * k_rate**2
            - 6.664 * net * abs(net)
            + 10.130 * k_rate * net
            - 5.195 * bb_rate * net
        )

    # Published ERA-equivalent linear-weight identity. Baseball Savant does not
    # document the specific transformation used by its official xERA displays.
    if xwoba is not None:
        delta = (xwoba - baseline["lg_woba"]) / baseline["woba_scale"]
        result["xera"] = _two(max(0, baseline["lg_era"] + delta * baseline["pa_per_nine"]))

    return result
