# Contact-adjusted expected pitcher run value (xRV) — methodology and audit

**xRV is a custom contact-adjusted metric, not an official Baseball Savant statistic
or a reproduction of FanGraphs Community's count-based xPV.** Baseball Savant
publishes context-neutral actual RV and expected **wOBA**, but not an official
expected pitch run-value formula. This metric combines these two sources in a
reproducible linear-weights approximation.

## Formula

Observed pitcher RV is unchanged from the dashboard's stored
`-Pitch.delta_run_expectancy`, using the existing Savant-neutral verification
pipeline in `app/services/run_value_refresh.py`.

For physical pitches that end a standard **ball in play**:

```
contact_correction = (seasonal_actual_wOBA_weight - Statcast_contact_xwOBA) /
                     same_season_FanGraphs_wOBAScale

pitcher_xRV        = pitcher_actual_RV + contact_correction
pitcher_RV_minus_xRV = pitcher_actual_RV - pitcher_xRV
```

Actual outcome weights and wOBAScale are both taken from the same **current,
season-specific FanGraphs Guts table**. A single, double, triple or home run
receives its season's w1B, w2B, w3B or wHR, respectively. Ordinary batted-ball
outs, errors, fielder's choices and sacrifice flies have a wOBA numerator of
zero. They are still included if Statcast supplies a valid contact xwOBA.

All non-contact pitches with recorded actual RV, including balls, called and
swinging strikes, fouls, strikeouts, walks and hit-by-pitches, keep the same
actual and expected RV. Count effects remain represented through Savant's
existing pitch run values; the app does not fit another count model.

The expected contact value is `estimated_woba_using_speedangle`, stored in
`Pitch.estimated_woba`. This CSV field is explicitly based on exit velocity and
launch angle, while full Savant xwOBA incorporates Sprint Speed on certain
weakly hit balls; the two are **not exactly equivalent on all contact**.

### 2026 source-coefficient correction, November 16, 2026

A final methodology audit identified that a previously cached FanGraphs Guts
result used older **2026** constants. The currently displayed table, independently
consistent with a November 4, 2026 baseballr Guts extraction, has:

| 2026 constant | Correct current value | Previously used value |
| --- | ---: | ---: |
| wOBAScale | **1.238** | 1.259 |
| w1B | **0.890** | 0.897 |
| w2B | **1.261** | 1.275 |
| w3B | **1.596** | 1.614 |
| wHR | **2.049** | 2.079 |

The constants for **every Statcast season from 2015 to 2026** are now stored
in `WOBA_CONSTANTS`. For an unsupported season (such as 2027 before its
constants are published), contact is left unscored rather than silently
borrowing another year's conversion factor.

The original approach mixed the current scale with whichever
`savant_woba_numerator` or `woba_value` had been stored when the data was
last imported. That could combine a newly revised scale with old event weights.
The audited implementation uses a **single known coefficient vintage** for
both fields, **without changing the underlying Savant RV** or requiring a
database migration. A separate audit counter
`expected_run_value_imported_weight_mismatch` identifies scored contact
where an imported weight differs from the current seasonal Guts weight by
more than 0.005. It is diagnostic: the final published seasonal weight is
used for xRV.

## Comparison rules

Only normal physical pitches with actual RV are eligible. For contact, the
app additionally requires a supported terminal Statcast event, an expected
wOBA in [0, 3], and seasonal Guts coefficients. Nonstandard outcomes such
as sacrifice bunts, catcher interference, interrupted PAs and unknown contact
event labels are **not** scored as ordinary batted-ball outs. Automatic balls
and strikes, and unknown pitch types, are excluded from physical-pitch counts.

For an active filter selection:

```
N_scored          = number of pitches with paired RV and xRV
paired_actual/100 = 100 * sum(actual_pitcher_RV on scored pitches) / N_scored
xRV/100           = 100 * sum(pitcher_xRV on scored pitches) / N_scored
RV - xRV          = sum(paired_actual_pitcher_RV - pitcher_xRV)
ΔRV/100           = 100 * (RV - xRV) / N_scored
coverage          = N_scored / N_physical_pitches
```

**Pitcher-positive sign:** Positive RV − xRV means better actual run prevention
than the contact-adjusted expectation. Negative means worse. This is not a pure
luck statistic: defensive alignment, runner events, extreme spray contact,
park conditions and limitations of the xwOBA model may affect residuals.

The original Savant-aligned `RV/100` continues to include its **full**
physical-pitch denominator. `paired_actual/100` and `RV/100` may differ
if the xRV sample is incomplete; do **not** subtract original RV/100 from
xRV/100. The API exposes coverage, paired actual RV, missing actual RV,
unscored contact, unsupported outcomes, unsupported seasonal scales and
outdated imported contact-weight counts to help audit the selection.

## Remaining limits

- This is an **outcome-adjusted**, not a pre-pitch predictive, run-value model.
  Savant does not supply an official xRV total to use as a direct benchmark.
- Replacing contact wOBA weights using linear weights is an approximation; it
  does not rerun full counterfactual base/out state simulations. Some play
  effects (e.g., extra outs on a double play) remain in observed RV.
- Savant alignment of **actual** run values is guaranteed only for dataset
  rows successfully checked by the repository's existing Savant-neutral
  refresh. A raw dataset imported without that verification is not made
  Savant-verified merely by calculating xRV.
- Local and public deployments use the same code, but this audit did not
  independently examine every row of the private local database or validate
  actual player-season xRV against an unavailable official Savant xRV metric.
- No predictive stability or year-over-year test is included.

## Sources

- [Baseball Savant Run Value leaderboard](https://baseballsavant.mlb.com/leaderboard/swing-take?stats=statcast)
- [Statcast CSV definitions](https://baseballsavant.mlb.com/csv-docs)
- [MLB xwOBA glossary](https://www.mlb.com/glossary/statcast/expected-woba)
- [FanGraphs Guts! seasonal constants](https://www.fangraphs.com/tools/guts?type=cn)
- [baseballr Guts extraction reference](https://billpetti.github.io/baseballr/reference/fg_guts.html)
- [FanGraphs Community Expected Pitch Value article](https://community.fangraphs.com/expected-pitch-value/)
