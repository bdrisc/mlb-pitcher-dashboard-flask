# Pitch separation: velocity and movement

This is a descriptive comparison of a pitcher's pitch-type averages in the
current filtered sample. The table reports gaps for each pair of pitch types.
It does not train a model or combine mph and inches into a single score.

For two types A and B:

- Velocity gap (mph): `abs(mean_velocity_B - mean_velocity_A)`.
- Signed velocity difference, available in the API/tooltip: `mean_velocity_B - mean_velocity_A`.
- ΔHB (inches): `mean_HB_B - mean_HB_A`.
- ΔIVB (inches): `mean_IVB_B - mean_IVB_A`.
- Movement gap (inches): `hypot(ΔHB, ΔIVB)`.

For example, a 95 mph fastball with -8 inches HB and 16 inches IVB versus an
85 mph changeup with -14 inches HB and 8 inches IVB has a 10 mph velocity gap,
-6 inches ΔHB, -8 inches ΔIVB, and a 10 inch movement gap.

Movement gap is the distance between the two mean **movement vectors**. It is
not the difference between the magnitudes of those vectors: opposite movement
directions can have identical magnitudes but substantial separation. It also
is not separation between two pitches' plate locations or their trajectories
at a hitter's decision point. Greater separation alone does not establish that
an arsenal or pitch pair is better.

## Samples, tracking and filters

SQL groups existing pitches by Statcast pitch code. Alternate names for the
same code are merged so they cannot produce duplicate or self-comparison rows.
All the dashboard's global filters apply before calculating means, including
pitch-type selection, dates, season, team, batter side, count and venue.
At least two classified pitch types are needed; selecting one type alone
shows an instruction to choose All pitch types or broaden the filters.

Velocity means use finite velocity readings. Movement means use only pitches
with **both** finite HB and IVB, ensuring each two-dimensional centroid comes
from the same tracked sample. Velocity and movement may therefore have different
sample counts. Hover a table cell for coverage. Missing data remains unavailable;
it is never replaced with zero. Real zero gaps remain zero. Automatic events
and unknown/blank pitch types do not become arsenal comparison pitches.

Calculations use unrounded SQL means. The API retains their full precision and
explicit units; only display values are rounded to one decimal. Horizontal
movement uses the app's existing catcher-perspective coordinates, and IVB is
induced vertical break. No additional gravity or handedness transformation is
applied.

## Display and API

A separate Pitch separation section sits below the arsenal table. The initial
reference is the most-used tracked fastball type among FF, SI, FA and FC; the
user can select another pitch or All pitch pairs. Without a fastball, the
initial display uses all pairs. The reference choice stays selected across
sample changes for the same pitcher when that type remains available.

There is one backend record for each unordered pair. The table places a chosen
reference in column A, reversing signed B-minus-A differences as needed.
Unsigned velocity and movement gaps do not change when the pair is reversed.

`pitch_separation` in the existing profile API contains:

- `pitch_types`: unrounded centroids and velocity/movement/total counts.
- `pairs`: pitch codes, absolute velocity gap, signed velocity/HB/IVB differences
  and Euclidean movement gap, with units in their field names.
- `reference_pitch_type`: the default display reference, or null.
- `difference_convention`: `pitch_b_minus_pitch_a`.

No database migration, reference download or backfill is required. Both apps
calculate this from the existing pitch records each time the sample changes.

## Repository connection

The existing [CCBL Stuff+ notebook](https://github.com/bdrisc/ccbl-stuff-plus/blob/main/notebooks/CCBL_StuffPlus_Model.ipynb)
uses velocity, horizontal break and induced vertical break as individual pitch
features. The [opponent pitcher scouting graphics](https://github.com/bdrisc/my-portfolio/blob/main/Opp_Pitcher_Scout_Graphics.ipynb)
plot arsenals on HB/IVB axes. This dashboard feature quantifies the gaps between
those pitch-type clusters; it is an extension of that analysis rather than an
existing named model copied from those projects.

## Verification

Tests cover opposite movement vectors with equal magnitudes, true zero gaps,
missing dimensions, unique unordered pairs, direction reversal, matched HB/IVB
tracking, nonfinite readings, pitch-name aliases, full-precision calculations
and global-filter behavior. An additional DOM integration check ran the actual
Flask page and JavaScript against SQL-backed API fixtures and verified the
initial reference, reversed-reference signs, selection persistence, all-pairs
mode and the one-pitch empty state. The complete Python suite has 113 tests.
