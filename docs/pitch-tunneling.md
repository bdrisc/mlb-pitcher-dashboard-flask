# Pitch tunneling: fixed-plane geometric estimates

This feature describes actual consecutive pitch sequences using Statcast's
constant-acceleration fits. It does not fit a model, assign a quality grade or
reproduce Baseball Prospectus's later batter-perspective PREMAX measurements.

## Measurements

For each ordered pair A → B, the API reports:

- Release gap: Euclidean distance between measured release x/y/z coordinates,
  multiplied by 12 to convert feet to inches. Extension differences are included.
- Tunnel gap: x/z distance between fitted paths at a common plane **23.8 feet
  in front of the front of home plate**, multiplied by 12.
- Plate gap: x/z distance at the front of home plate, multiplied by 12.
- Late separation: Plate Gap minus Tunnel Gap for each pair, in inches. Positive
  values mean paths spread apart; negative values mean convergence. This includes
  trajectory direction and location effects, so it is not pure late break.
- Flight-time gap: absolute difference between the two fitted release-to-front
  flight times, multiplied by 1,000 to convert seconds to milliseconds.

The front plane is Statcast y=17/12 feet. The tunnel plane is consequently
**y=17/12 + 23.8 = 25.2166667 feet**, not y=23.8. Both paths are evaluated at
that same y plane, each at its own time of arrival there.

The fixed-distance convention follows the original distance-based tunneling
approach. Its time before arrival varies with pitch speed. Later perceived,
time-based tunnel metrics are different measurements; these numbers should not
be compared directly with their league averages. Smaller tunnel gaps describe
closer paths at that plane, not automatically better pitches or more deception.

## Trajectory and coordinate anchoring

Statcast velocities and accelerations are referenced to y=50 feet, not to the
release point. Signed time to a plane y is computed using the stable root:

`t(y) = 2*(50-y) / (-vy0 + sqrt(vy0^2 - 2*ay*(50-y)))`

This handles ay=0. Negative times are allowed for release positions behind
y=50. Fits with forward velocity in the wrong direction, nonfinite values,
impossible discriminants or invalid plane ordering are unavailable.

Stored plate x/z anchor the fitted trajectory. Their plane is front-of-plate
through 2025 and midpoint (y=17/24) from 2026 onward. If ta is time at that
anchor plane, positions at another time t are:

`x(t) = plate_x + vx0*(t-ta) + 0.5*ax*(t^2-ta^2)`

`z(t) = plate_z + vz0*(t-ta) + 0.5*az*(t^2-ta^2)`

Measured release coordinates are used for release distance; they are not
incorrectly substituted for x/z at y=50. Flight time uses each pitch's measured
release y, not just its time from y=50. Missing release x/z leaves release gap
unavailable while retaining path metrics and flight time when possible. Missing
release y prevents release gap and full-flight comparison. Release y must be
behind the tunnel plane and no more than 65 feet from the back tip of the plate.
These are fitted paths; the constant-acceleration model does not simulate a
bounce or the batter's visual perception.

## Pair eligibility and filters

An indexed self-join requires the same game, pitcher, batter and plate appearance,
and exactly adjacent pitch numbers. It joins the actual predecessor before
applying the selected pitch-type/count conditions to the second pitch. Missing
pitch rows or missing tracking never allow a pair to skip over an intervening
pitch. Automatic calls and unknown/unclassified types are excluded. Same-type
pairs are included and are identified separately, such as FF → FF.

All normal filters apply to the second pitch. Its predecessor remains context.
FF → SL and SL → FF are different observed sequence populations in the API.
The Pitch separation table pools both directions into one unordered A/B row.
Each displayed value is an arithmetic mean of individual pair measurements,
using the metric-specific count to weight the ordered-sequence means. It is
not a distance between averaged release points or trajectories. Same-type
sequences remain in the API but do not create comparison-table rows.

Release gap and signed late separation do not change when the reference pitch
is reversed. Their sample counts are available on hover. Missing measurements
or unobserved combinations remain null/dashes, never zero. Existing velocity
and HB/IVB columns still compare filtered pitch-type centroids; their samples
can differ from these sequence-derived columns. Display rounding occurs only
in the browser. The separate Pitch tunneling section has been removed.

## Integration and verification

`app/services/pitch_tunneling.py` adds a read-only `pitch_tunneling` section to
the existing profile API, with `overall`, ordered `pairs`, `by_pitch_type`,
method metadata and metric sample counts. The existing `pitch_tunneling` API
is retained; the compact UI reads enriched `pitch_separation.pairs` fields
`release_gap_inches`, `late_separation_inches`, `release_pair_count`,
`late_separation_pair_count`, and `observed_sequence_pair_count`. Both installations run identical code
on their own stored pitches. Existing sequence indexes and trajectory columns
are sufficient: no new migration, training, season download or backfill is
required for this feature. Historic rows lacking inputs are shown as unavailable.

Tests cover independent bisection of full trajectories, both plate planes,
release-distance effects on flight time, crossing paths, real zeros, missing
tracking, ordered pairs, same-type pairs, every sequence boundary, second-pitch
filtering, missing rows, weighted pooling and empty samples. A separate full-source
check verified all 50 pitchers and all 99,722 eligible pairs in the bundled
133,933-pitch snapshot against independent vectorized trajectories. The largest
overall mean difference was 7.5e-14. Mean query-and-calculation time was 0.069 s
in the local SQLite check; deployed latency depends on database and hosting.

## References

- [Original BP pitch tunnels](https://www.baseballprospectus.com/news/article/31030/prospectus-feature-introducing-pitch-tunnels/)
- [BP's later tunnel update](https://www.baseballprospectus.com/news/article/37436/prospectus-feature-updating-pitch-tunnels/)
- [Savant CSV coordinates and trajectory fields](https://baseballsavant.mlb.com/csv-docs)
