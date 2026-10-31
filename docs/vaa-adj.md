# Location-adjusted vertical approach angle (VAAAdj)

The app defines a per-pitch signed residual in degrees:

`VAAAdj = observed VAA - expected VAA`

For each supported Statcast pitch type, ordinary least squares on the 2025 MLB
regular season estimates:

`expected VAA = intercept + height_coefficient * plate_z_front`

Positive is flatter (less negative VAA) than expected at that height; negative
is steeper. Zero is an actual match to expectation. This is a description of
approach geometry, not a universal pitch-quality or run-value grade.

This is the app's own frozen model following published location-adjusted VAA
methodology. It is not a downloaded FanGraphs or Pitcher List grade and is not
claimed to reproduce their coefficients. Unlike HAAAA, it does not condition on
release point or throwing hand. Release height and velocity are intentionally
not predictors: their contributions to unusual flatness/steepness remain in
the residual. Heights are in feet, not batter-zone-normalized coordinates.

## Training and evaluation

`scripts/build_vaa_adj_reference.py` downloads complete 2025 training and 2026
evaluation regular seasons in nonoverlapping three-day windows. It validates
season/date/game type, response size and unique pitch IDs. CSV event and
classified-pitch totals must match the independently verified full-season source
audit in `data/haaaa_validation_2026.json`; its hash is recorded. Physical pitch
totals are independently rechecked against current Savant league aggregates.
Current aggregate `total_pitches` and `num_events` do not count every automatic
call present in the CSV, so they are recorded separately rather than treated as
CSV row counts. Some physical pitches also have no pitch classification.

Only pitch types with 500 usable training pitches, five distinct pitchers and
full-rank regression are supported. Unclassified/missing fits stay unavailable.
No 2026 targets fit or recenter the model. Evaluation compares against a frozen
2025 pitch-type mean; it measures geometric fit, not predictive pitch quality.
The reference JSON has a SHA-256 model ID checked at runtime, and the evaluation
JSON records metrics and hashes for every source window.

Both apps use the identical small checked-in reference. No UI filter, pitcher
selection or public-cohort composition fits or changes the coefficients. Model
training never runs on app startup. The 2025-trained reference applies to 2026
and later, not earlier seasons. Predictions outside the training height range
are linear extrapolations; ranges are recorded in the artifact.

## Measurement plane

Raw VAA is calculated from Statcast's constant-acceleration fit at the front
of home plate, y=17/12 feet. Through 2025, `plate_z` refers to that plane.
From 2026 onward it refers to the plate midpoint, y=17/24 feet. We align the
height predictor before scoring:

`z_front = plate_z + vz0*(t_front-t_mid) + 0.5*az*(t_front^2-t_mid^2)`

Flight time from y=50 to a plane y is:

`t(y) = 2*(50-y) / (-vy0 + sqrt(vy0^2 - 2*ay*(50-y)))`

Incomplete, nonfinite or impossible required trajectory inputs yield no score.
The conversion changes neither stored `plate_z` nor existing VAA/HAA/HAAAA.

## Integration

Migration 0006 adds `expected_vaa`, `vaa_adj` and `vaa_adj_model_id`. Ingestion
scores complete new pitches; sparse reimports preserve existing tracking and
scores. Raw-angle backfills invalidate the model marker for rescoring.

`flask --app wsgi statcast backfill-vaa-adj --season 2026` updates only those
three new fields, in resumable batches, without adding/removing pitches, games
or players. Repeated runs skip the current model. Public startup runs the
backfill after raw-angle maintenance and before other enrichment tasks; set
`SYNC_VAA_ADJ_ON_STARTUP=0` to disable this step.

SQL averages full-precision per-pitch residuals after all active filters.
The arsenal table displays signed degrees to two decimals beside VAA and
hover text reports scored sample coverage. API overall, arsenal and platoon
metrics expose `vaa_adj`, `expected_vaa` and `vaa_adj_pitch_count`.
An unscored pitch is null, never zero. The main metric cards are unchanged.

## Sources

- [Chamberlain's VAA primer](https://blogs.fangraphs.com/a-visualized-primer-on-vertical-approach-angle-vaa/): location adjustment within pitch type.
- [Savant CSV documentation](https://baseballsavant.mlb.com/csv-docs): trajectory fields and the 2026 plate-location plane change.

## Frozen-reference results

The source audit matches 712,528 CSV events for 2025 and 716,792 for 2026.
Current independent physical pitch totals match 710,084 and 714,483 respectively.
The model supports 12 pitch types. There are 713,160 supported 2026 evaluation
pitches; their RMSE is 0.656763 degrees, versus 1.131193 degrees for the frozen
2025 pitch-type mean. These are geometry-validation results, not estimates of
run prevention or future pitch effectiveness.

End-to-end SQLite verification migrated a fresh database and ingested all
133,933 bundled public-source pitches. New-ingestion and backfilled scores
matched exactly. The backfill processed 133,932 classified physical pitches,
scored 133,830 and left 102 unavailable. Pitch counts, raw VAA/HAA, HAAAA and
run values were preserved; a second backfill processed zero pitches. Unit/API
checks also cover filters, missing data, signs and sparse reimports; DOM checks
cover column order, signed degrees, unavailable cells and filter reloads.
