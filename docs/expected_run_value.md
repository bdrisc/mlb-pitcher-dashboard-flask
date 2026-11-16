# Contact-adjusted expected pitcher run value (xRV)

## Definition and source alignment

**This is a custom metric, not an official Baseball Savant xRV or FanGraphs xPV.**
The baseline for each pitch is the *existing* Baseball Savant-aligned,
context-neutral pitcher run value in the dashboard, not a new approximation of
run expectancy or a separate reconstruction of a wOBA-by-count table.

The repository verifies observed pitcher-season pitch RV against Savant's
context-neutral total in `app/services/run_value_refresh.py` and preserves the
normal `RV/100` calculation without changes. Source data for each scored pitch:

- `Pitch.delta_run_expectancy`: batter-signed run value as stored after the
  existing Savant-neutral verification/refresh (pitcher RV is its negative).
- `Pitch.estimated_woba`: Statcast `estimated_woba_using_speedangle` for
  balls put into play (primarily exit velocity and launch angle).
- `Pitch.savant_woba_numerator`, if available, otherwise `Pitch.woba_value`:
  actual outcome wOBA weight as documented by Savant.
- `Game.season`: selects **that season's** FanGraphs wOBAScale.

For scored balls in play, the calculation on the pitcher's sign convention is:

```
pitcher_actual_RV = -Savant_batter_pitch_RV
pitcher_xRV       = pitcher_actual_RV + (actual_wOBA_weight - contact_xwOBA) / wOBAScale
pitcher_RV_minus_xRV = pitcher_actual_RV - pitcher_xRV
```

For a normal ball, called/swinging strike, foul, walk, strikeout or HBP,
`pitcher_xRV = pitcher_actual_RV`. The observed run value already incorporates
the count transition; we **do not** fit another count-based model, since that
would cause the dashboard's paired actual run values to diverge from verified
Savant run values. FanGraphs Community's *Expected Pitch Value* provides the
conceptual inspiration for using xwOBA and wOBAScale, but its count-based xPV
is a different statistic.

The sign is **pitcher-positive**: positive RV − xRV means the pitcher prevented
more runs than this contact-quality-adjusted estimate. This is a description
of observed versus expected contact results, **not a measure of pure luck**.

## Pairing, filters, coverage and denominators

Only physical pitches with an observed run value are candidates. For
descriptions `hit_into_play`, `hit_into_play_no_out`, and
`hit_into_play_score`, a pitch needs valid actual and expected wOBA values,
a documented scale for the season, and a standard plate-appearance outcome.
Contact plays without those requirements are **excluded from both paired actual
and expected totals**, not filled with an arbitrary zero correction.

Sacrifice bunts, catcher interference, and interrupted PAs are explicitly
excluded from scored contact. They still count toward the denominator and the
published missing-coverage counters. Automatic ball and automatic strike
events, and unidentified pitch types, are excluded from the denominator to
match the existing physical-pitch `RV/100` convention.

For any selection or arsenal pitch type:

```
paired_xRV/100     = 100 * sum(paired_pitcher_xRV) / N_scored
paired_actual/100  = 100 * sum(paired_pitcher_actual_RV) / N_scored
RV - xRV           = sum(paired_pitcher_actual_RV) - sum(paired_pitcher_xRV)
(RV - xRV)/100     = 100 * (RV - xRV) / N_scored
coverage           = N_scored / N_physical
```

The original `RV/100` reports *all* available RV pitches with its original
physical-pitch denominator. If a selection has missing batted-ball estimates
or run values, `paired_actual/100` and original `RV/100` may differ: do not
subtract original `RV/100` from xRV/100. Paired totals, scored counts, coverage
percentages, missing actual-RV counts, unscored contact counts, unsupported
contact counts, and unknown seasonal-scale counts are included in the profile
JSON. Empty paired samples return null, not zero.

## FanGraphs wOBA scale

The scales are taken from FanGraphs' season-specific Guts table, not the older
article's illustrative `1.15` approximation:

| Year | wOBAScale |
| --- | ---: |
| 2023 | 1.204 |
| 2024 | 1.242 |
| 2025 | 1.232 |
| 2026 | 1.259 |

A future or otherwise unsupported season does not silently inherit the 2026
scale. Update `WOBA_SCALES` after that year's scale is available.

## Limitations / audit

- This adjusts the **observed outcome of contacted balls only**. It is *not*
  a pre-pitch prediction of whether a batter swings, whiffs, makes contact,
  reaches base, or scores.
- Realized non-contact outcomes, count effects, and non-contact baserunning
  effects remain in the Savant-verified observed RV. The wOBA-to-runs adjustment
  is a linear-weights approximation; it cannot exactly re-create the change in
  run expectancy that would occur if individual batted-ball outcomes changed.
- `estimated_woba_using_speedangle` is a tracked-contact EV/LA estimate; it
  is not guaranteed identical to the full Savant xwOBA treatment of all PAs,
  including sprint-speed adjustments in certain cases.
- The original observed RV values are only as neutral as the **verified
  Savant-neutral refresh** for that dataset. The pipeline favors Savant
  deleveraged fields on ingestion and has a separate validator that matches
  its season totals. Missing/legacy unverified values are not retroactively
  converted by this metric.
- Missing or unusual batted-ball events are not silently assigned actual RV.
  The JSON and hover tooltips reveal the incomplete-data counts. An individual
  pitcher/pitch type with substantially incomplete coverage should not be
  interpreted as having an unbiased full-season expected value.
- No year-over-year stability or predictive test has been performed.

## Sources

- [Baseball Savant: Run Value](https://baseballsavant.mlb.com/swing-take)
- [Baseball Savant: CSV field definitions](https://baseballsavant.mlb.com/csv-docs)
- [FanGraphs Guts: season-specific wOBA scales](https://www.fangraphs.com/tools/guts?type=cn)
- [FanGraphs Community: Expected Pitch Value](https://community.fangraphs.com/expected-pitch-value/)
