# Raw VAA and HAA

Angles are calculated for each pitch, in degrees, at the **front plane of home
plate** (`y_f = 17/12` feet). Statcast's initial velocity components refer to
`y_0 = 50` feet, not `release_pos_y`. The six source fields are `vx0`, `vy0`,
`vz0` (ft/s) and `ax`, `ay`, `az` (ft/s²). `az` already includes gravity;
no extra gravity correction is applied.

## Equations and signs

With `d = 50 - 17/12`:

```
vy_f = -sqrt(vy0² - 2*ay*d)
t = 2*d / (-vy0 + sqrt(vy0² - 2*ay*d))
vz_f = vz0 + az*t
vx_f = vx0 + ax*t
VAA = degrees(atan2(vz_f, -vy_f))
HAA = degrees(atan2(vx_f, -vy_f))
```

This is algebraically equivalent to Alex Chamberlain's published equations,
`t = (vy_f-vy0)/ay` and `-degrees(atan(v_axis_f/vy_f))`, for a pitch traveling
toward home plate. The rationalized time formula also works when `ay = 0`
and avoids subtracting nearly equal velocities. These are the published
vertical/longitudinal and horizontal/longitudinal **plane** angles; VAA does
not substitute the 3D horizontal speed for `-vy_f`.

VAA is negative for a descending pitch. HAA is positive toward the catcher's
right (Statcast positive x), negative toward the catcher's left. Neither angle
is flipped by pitcher or batter handedness. These are raw, unadjusted angles.
They are not location-adjusted VAA/HAA or directly measured Hawk-Eye angles.

Nonfinite components, motion away from the plate, or a trajectory that cannot
reach the plate with negative y-velocity do not produce a value. Missing
horizontal tracking need not invalidate usable vertical tracking, and vice
versa. SQL averages individual unrounded angles after applying filters;
only the final display is rounded to one decimal. Hover each arsenal cell
for the usable-pitch count. Missing angles display as a dash.

## Verification

- The checked-in 47-pitch fixture includes multiple pitch types and both
  throwing hands from the bundled 2026 Savant CSV.
- Tests independently locate the front plane by bisection of position and
  estimate the trajectory direction by central finite differences. They
  agree with the implementation within `1e-8` degrees.
- A separate test transcribes Chamberlain's original formula and agrees
  within `1e-10` degrees. Zero drag, near-zero drag, mirrored x signs,
  unavailable fits, filtered SQL aggregation and null handling are covered.
- Full bundled-source audit: 133,933 complete fits. Largest difference from
  the original published expression was `2.14e-14` degrees for VAA and
  `8.44e-15` for HAA. This verifies numerical agreement, not tracking accuracy.
- End-to-end migration, ingestion, field-only backfill and API verification
  on a scratch SQLite copy: 133,932 classified physical pitches backfilled,
  zero failures, row count unchanged, existing K%, BB%, K-BB%, run value and
  xwOBA unchanged. A repeated backfill updated zero pitches. The single
  unclassified `UN` pitch was excluded from backfill.

## Data maintenance

Migration `0004_approach_angles` adds nullable source, angle and calculation
version fields without replacing existing pitches. Backfill writes only these
fields, matches natural pitch IDs, checks pitcher/season ownership, and never
inserts players, games or pitches. A supplied CSV is processed transactionally;
downloads commit separately for each complete pitcher-season. Incomplete or
failed downloads preserve saved data and are reported so a rerun retries them.
Successfully checked missing fits are marked processed to avoid downloading
untracked pitches on every restart. Future CSV ingestion calculates angles
and preserves existing angle fields when the incoming CSV omits them.

Public startup applies migrations before starting the server, then backfills
in the background from the bundled CSV and downloads trajectories only for
remaining unprocessed pitches. `SYNC_APPROACH_ANGLES_ON_STARTUP=0` disables
that background backfill. Native local Flask uses the manual commands in README.

## References

- [Savant CSV field definitions](https://baseballsavant.mlb.com/csv-docs)
- [Chamberlain: VAA](https://blogs.fangraphs.com/a-visualized-primer-on-vertical-approach-angle-vaa/)
- [Chamberlain: HAA](https://blogs.fangraphs.com/a-visual-primer-on-horizontal-approach-angle-haa/)
- [Kagan: PITCHf/x coordinates and trajectory fit](https://baseball.physics.illinois.edu/kaganpitchfx.pdf)
