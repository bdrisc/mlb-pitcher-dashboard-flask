# HAA Above Expected (HAAAA)

The dashboard defines HAAAA as:

`HAAAA = observed HAA - expected HAA`

For each Statcast pitch type and throwing hand, a separate ordinary least
squares regression uses:

`expected HAA = intercept + release_side_coefficient * release_pos_x + location_coefficient * plate_x_front`

The target is the unrounded, front-of-plate HAA derived from Statcast velocity
and acceleration. No movement, velocity, spin, pitch outcome or batter result
is used as a predictor. The residual measures approach-angle deviation after
accounting for release side and location; it is not a run-value or quality grade.

This is the app’s custom frozen model, using the published adjustment variables.

## Reference and evaluation

- Training: all available 2025 MLB regular-season pitch fits, acquired in
  nonoverlapping three-day windows. Source event totals must match
  Savant's independent league aggregate before fitting. Official physical and
  classified-pitch totals are recorded separately because unclassified pitches
  can still be physical pitches.
- Minimum group support: 500 usable pitches, five pitchers, full-rank regression.
  Unsupported categories and incomplete tracking stay unavailable.
- The 2025 coefficients are frozen in `data/haaaa_reference_2025.json` and used
  for 2026 and later. A SHA-256 integrity check validates the artifact at load.
- 2026 is a separate temporal evaluation set. Its targets never fit or recenter
  coefficients. Evaluation and source-file hashes are in
  `data/haaaa_validation_2026.json`; compare context-adjusted errors with a
  frozen 2025 pitch-type/hand mean as the unadjusted baseline.
- Both app installations load the identical artifact. Pitcher selection,
  date, handedness, count and other UI filters change the aggregated sample,
  not the model. The 50-pitcher public cohort is not the training population.
- Older seasons are not scored by a model trained on 2025.

## Measurement plane and signs

Savant defines `plate_x` at the front of home plate through 2025, and at the
midpoint from 2026 onward. Raw HAA in this app is defined at the front. To
align the location predictor, first calculate flight times from y=50 feet to
front y=17/12 feet and midpoint y=17/24 feet with the constant-acceleration fit.
Then, for 2026 and later:

`plate_x_front = plate_x + vx0*(t_front-t_mid) + 0.5*ax*(t_front^2-t_mid^2)`

The stored `plate_x` and the existing raw HAA are not changed. Missing trajectory
components needed for conversion prevent scoring; they are not assumed zero.

The residual retains the app's signed raw-HAA coordinate: positive is toward
the catcher's right, negative toward the catcher's left. Neither value is
multiplied by throwing hand, movement sign, or its absolute value. A positive
residual means a more positive HAA than predicted; it does not automatically
mean a better pitch. For example, observed -1 degrees minus expected -3 degrees
is +2 degrees.

## Storage and updates

Migration 0005 adds nullable per-pitch throwing hand, expected HAA, HAAAA and
model ID. New CSV ingestion scores each pitch before any aggregation. Old
records use the stored player hand when no per-pitch hand exists; known
switch-hand pitchers identified in the evaluation data require per-pitch hand
rather than guessing. Raw-angle backfills capture the source hand and invalidate
HAAAA's model marker so subsequent scoring picks up changed trajectories.

`statcast backfill-haaaa` updates only the expected value, residual and model
marker on existing pitches, in resumable batches. It does not insert or remove
pitches, players or games. Null inputs and unsupported groups are counted as
unavailable, not displayed as zero. Hover the HAAAA cell for sample coverage.
SQL averages unrounded individual residuals after applying the active filters;
the table displays signed degrees to two decimals.

Public startup runs this scoring after the raw-angle backfill. Set
`SYNC_HAAAA_ON_STARTUP=0` to disable that maintenance step. Native local users
run the commands in README against their existing full PostgreSQL database.

## Reproduction

`python scripts/build_haaaa_reference.py`

The script uses only NumPy, pandas and the Python standard library. Downloads
are cached under the ignored `data/cache/haaaa_reference` directory; the two
small frozen reference/evaluation artifacts are checked into Git. Normal app
startup never downloads league training data or fits a regression.

Tests cover the residual identity and signs, independent geometric conversion
between the midpoint and front planes, temporal eligibility, throwing-hand
strata, unsupported/missing inputs, SQL aggregation, filter behavior and
preservation of existing pitch data.

## Sources

- [Savant CSV documentation](https://baseballsavant.mlb.com/csv-docs)
- [Chamberlain: HAA adjustment for location, hand and release side](https://blogs.fangraphs.com/a-visual-primer-on-horizontal-approach-angle-haa/)
- [MLB ABS measurement plane](https://www.mlb.com/interactive/mlb-abs-system-explainer)

## Frozen-reference results

The source audit matched 712,528 events in 2025 and 716,792 in 2026 to Savant's
independent regular-season aggregates. There were 709,906 usable training fits
and 714,116 usable evaluation fits. The 22 supported type/hand strata covered
712,979 evaluation pitches. Weighted 2026 RMSE was 0.364960 degrees, compared
with 1.170560 degrees for the frozen 2025 type/hand mean. This evaluates the
geometric expectation, not the residual's predictive value for pitch outcomes.

End-to-end SQLite verification on the complete bundled public source loaded
133,933 pitches, backfilled 133,932 classified physical pitches, and scored
133,829 of them. The 103 unavailable pitches had unsupported reference groups.
The test preserved row counts, raw HAA/VAA, strikeout/walk rates, run value and
xwOBA; a repeated backfill processed zero pitches. New-ingestion scores and
field-only backfill scores matched for every checked arsenal row.
