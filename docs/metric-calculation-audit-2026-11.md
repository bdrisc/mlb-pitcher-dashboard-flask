# MLB Pitcher Dashboard — metric calculation audit (2026-11-22)

## Scope and verification standard

This is a **code-and-test audit** of the shared dashboard calculations in
`app/services/pitcher_profiles.py`, the associated specialized service modules,
the Statcast importer and the public/local data-source adapters. It identifies
which measures are direct third-party imports, source-aligned calculations, or
explicitly custom models. It is **not** a claim that every player/season/filtered
number has been independently reconciled against current Baseball Savant and
FanGraphs data: that requires the exact corresponding local pitch sample and
source vintage. Passing automated tests alone cannot prove source parity.

Primary definitions/source documentation:

- Baseball Savant Statcast CSV: https://baseballsavant.mlb.com/csv-docs
- MLB Statcast glossary: https://www.mlb.com/glossary/statcast
- FanGraphs glossary: https://library.fangraphs.com/
- FanGraphs annual wOBA constants: https://www.fangraphs.com/tools/guts?type=cn
- Direct FanGraphs grades/reference and Savant published metric imports are
  implemented in `published_pitching.py`, `fangraphs_stuff.py`,
  and `savant_active_spin.py`.

**Important principle:** matching a published statistic requires matching
(1) the exact pitch/game sample, (2) the source's definitions and eligible
events, (3) tracked-event coverage, and (4) the source update vintage.
Player, date, pitch type, count and team filters can produce different numbers
from season-only leaderboards even with correct formulas.

## Outcome and run prevention

| Display metric | Implemented definition / provenance | Audit result |
| --- | --- | --- |
| K% | Strikeout PA endings / recorded PA | Source-aligned outcome counting; game outcome events govern denominator |
| BB% | Walk and intentional-walk PA endings / recorded PA | Source-aligned; all walks currently included |
| K-BB% | K% minus BB% using identical PA denominator | Correct difference of recorded rates |
| wOBA against | Sum of exact source-verified Savant wOBA numerators / summed source denominators | Requires full `backfill-woba` coverage; withholds incomplete results |
| xwOBA against | Statcast expected contact weights on eligible PA endings + 0 for K + verified/unadjusted source weights on BB/HBP, over eligible PA | Shared source-aligned formula in `expected_woba.py`; withholds incomplete source tracking; not automatically identical to a newer Savant vintage |
| xBA against | Expected hits on tracked AB contact plus 0 for K / scored eligible AB | Source-aligned; current missing-contact handling uses *scored* AB, so validate source coverage before comparing leaderboards |
| xSLG against | Expected total bases from source contact estimates + 0 for K / scored eligible AB | Source-aligned; scored-AB denominator and source tracking coverage matter |
| RV/100 | Pitcher-positive negative of Statcast `delta_run_exp` sum × 100 / physical pitches | Source-aligned **on complete eligible pitches**; this audit now withholds a rate when any eligible pitch lacks RV |
| xRV/100 | Local contact-adjusted RV based on the seasonal FanGraphs wOBA scale and the tracked pitch subset | **Custom research metric**, *not* an official Savant expected RV; keeps tracking-quality flags and is not validated to outperform observed RV prospectively |
| FIP/xFIP/SIERA | Imported published FanGraphs full-season values | Source values; **not** recomputed or pitcher-filtered |
| xERA | Imported published Baseball Savant full-season value | Source value; not derived from a filtered local xwOBA |
| Stuff+/Location+/Pitching+ | Imported FanGraphs grades/reference values | Source values; not trained or re-created by the dashboard |

## Pitch results and plate discipline

| Metric | Implemented formula / event handling |
| --- | --- |
| Strike% | Called strikes, swings-and-misses, fouls, and in-play contacts / **physically thrown** pitches |
| Swing% | Swings, including foul tips, bunts and **all** Statcast hit-into-play variants / physical pitches |
| Whiff% | Source-style whiff outcomes (incl. foul tips/missed bunts) / swings |
| Z-Whiff% | Those whiffs on classified in-zone pitches / classified in-zone swings |
| O-Whiff% | Those whiffs on classified out-of-zone pitches / classified out-of-zone swings |
| SwStr% | Swinging strikes and blocked swinging strikes / physical pitches; deliberately excludes foul tips and bunts |
| PutAway% | PA-ending strikeouts on pitches thrown with two strikes / physical two-strike pitches |
| CSW% | Called strikes + whiffs / physical pitches |
| Zone% | Tracked, classified in-zone physical pitches / all classified-location physical pitches |
| Chase% | Swings on classified out-of-zone pitches / all classified out-of-zone physical pitches |
| Pitch count/Usage% | Observed pitch-event records and proportional pitch-type use in the active sample, not a projected quantity |

**Corrections in this audit:** Before this change, `hit_into_play_no_out` and
`hit_into_play_score` did not enter some swing/strike denominators despite
counting as batted balls elsewhere. They now count consistently in import,
overall/pitch-type splits and pitch-pair results. Saved `is_chase` booleans
from older ingests can lag source definitions; the profile now calculates
chases directly from the matching SQL zone/swing subset. Automatic balls and
strikes do not count as physical pitches for Strike%, Swing%, CSW% or Zone%.

These are **explicit event definitions**. Specialized Savant or FanGraphs
leaderboards may classify rare event codes and automated calls differently.
Do not claim numerical parity without comparing the same game-level data.

## Contact and batted-ball results

| Metric | Implemented formula / source |
| --- | --- |
| Avg EV | Mean tracked exit velocity on eligible batted balls |
| Hard-Hit% | Batted balls with EV ≥ 95 mph / batted balls with tracked EV |
| Barrel% | Official source barrel classification / all eligible BBE; withheld unless classification audit is complete |
| GB% / FB% / LD% / PU% | Classified batted-ball type counts / total classified BBE, with displayed rounding allocated to sum exactly 100% |
| xwOBAcon | Mean Statcast contact expected-wOBA estimate on tracked batted balls; **not** PA-ending full xwOBA |
| xwOBAcon by pitch pair | Same contact-only expected value on the *second* pitch of a genuinely consecutive A→B pair; report scored BBE and missing-data context |

BBE/event eligibility and missing launch-monitor values must be checked before
using sample-based rates as season-leaderboard equivalents.

## Pitch shape, location, movement and source grades

| Metric or section | Calculation and classification |
| --- | --- |
| Velo / max velo | Mean / maximum imported Statcast release speed |
| Perceived Velocity | Imported Statcast `effective_speed`, extension-adjusted; **not** location-based effective velocity |
| Extension | Mean source release extension, feet |
| Spin | Mean source spin rate, rpm |
| Spin Axis | Imported/backfilled source spin axis; circular display/aggregation needs validation around the 0°/360° boundary |
| Spin Efficiency | Published Savant active-spin percentage, full-season pitch-type reference, not a locally filtered movement proxy |
| HB / IVB | Source-derived horizontal/induced vertical movement in inches |
| HB/IVB vs AVG | Local same pitch, throwing hand, arm-angle reference cohort; a **custom comparator** |
| Release Height/Side/SD | Means in feet and paired release-position sample standard deviation in inches |
| Arm Angle | Source arm-angle value averaged on valid tracked pitches |
| VAA / HAA | Trajectory-based arrival angle from tracked velocity/acceleration at the front of home plate; see `approach_angles.py` |
| VAAAdj | Observed minus frozen pitch/location reference expected VAA; custom metric |
| HAAAA | Observed minus frozen pitch/hand/location/release expected HAA; custom metric |
| Pitch Transition Matrix | Observed consecutive within-PA next-pitch frequencies; **not** effectiveness |
| Pitch Pair Effectiveness | Directional consecutive within-PA pairs, with Whiff/CSW/xwOBAcon/RV on second pitch |
| Pitch Separation and Tunneling | Vector gaps and 3D path separation using a reference tunnel point; **custom measurements** |
| Location Heatmaps | Kernel density on tracked pitch locations and batter hand; visualization, not official Savant leaderboard |
| Pitch Location Performance | 3×3 zones and league-relative reference from the *loaded database cohort*, not the entire league if only a sample was loaded |
| Times Through the Order | Aggregation by tracked `n_thruorder_pitcher`; groups 4th and later turns together |

## Data coverage and remaining independent verification

1. **Full public/local numeric parity not established by this audit.** The
   repository includes a local/public parity workflow, Savant run-value
   case studies, tests of annual wOBA weight use, and source-verified
   FanGraphs/Savant imports. Re-run representative pitcher-season tests
   after a complete 2025 ingestion; do not infer results from a synthetic
   fixture or a 2026 holdout alone.
2. **Some xBA/xSLG samples omit untracked contact**, with scored/eligible
   counts separately available. They are not guaranteed to reproduce the
   full-source leaderboard when coverage is incomplete.
3. **Source-published references** (FIP/xFIP/SIERA/xERA, FanGraphs grades,
   Savant active spin) do not update with arbitrary pitch-level filters,
   and no historical references are invented for data years not imported.
4. **Custom metrics** (xRV, VAAAdj, HAAAA, separation, location comparisons)
   should be compared with their documented internal baselines, not
   declared equivalent to official Savant/FanGraphs formulas.
5. **Missing values remain null, not invented zeros.** Full xwOBA and
   observed RV/100 are now withheld rather than diluted when outcomes
   required for their denominator are missing.
6. **2025 season verification:** After importing local 2025, check pitch
   counts by season/team, sample game-type coverage, full PA/event
   tracking, missing expected-value and run-value counts, and whether
   optional published/reference backfills have run for 2025.

**Automated controls:** `tests/test_dashboard_quality.py` checks the
team/season directory, old-flag-safe chase rate, swing and strike event
variants, and physical-pitch denominators. Existing focused suites verify
xwOBA, xBA, xSLG, wOBA, RV, run-value refresh, barrels, approach angles,
grades, splits, location and pitch sequencing. These tests are a regression
baseline, not a claim of universal source-level accuracy.
