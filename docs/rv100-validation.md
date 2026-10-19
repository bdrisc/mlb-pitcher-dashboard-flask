# RV/100 validation

Checked October 19, 2026 against Baseball Savant's 2026 regular-season Aaron Nola
pitch arsenal leaderboard and its context-neutral Statcast Search output.

- Source detailed CSV: `https://baseballsavant.mlb.com/statcast_search/csv?all=true&type=details&player_type=pitcher&pitchers_lookup%5B%5D=605400&hfSea=2026%7C&hfGT=R%7C`
- Source pitch arsenal: `https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats?type=pitcher&pitchType=&year=2026&team=&min=0&csv=true`
- Source aggregate: Statcast Search with `outputFormat=json`, `group_by=name`,
  `chk_stats_delev_pitcher_run_exp=on`, and `chk_stats_delev_pitcher_run_value_per_100=on`.

The current detailed CSV `delta_run_exp` matched the explicitly named
`delev_delta_run_exp` in event-level JSON for all 179 pitches in the April 1–10
Nola query (maximum difference zero). It did not match `unadj_delta_run_exp`.
The CSV's pitcher value was the negative of its batter value. Source fields can
change, so explicit neutral fields take precedence when present in imported files.

The retained test fixture contains only pitch type and the source CSV's run value,
not a locally fitted approximation. Its 2,955 event rows include nine automatic
ball/strike records with missing run values. The denominator is 2,946 valued pitches.
Their pitcher run values sum to -22.272 runs. Savant reports overall neutral RV/100
-0.756008147 before display rounding; the app shows -0.8.

| Statcast type | Savant arsenal type | Pitches | Savant RV/100 | App RV/100 |
|---|---|---:|---:|---:|
| FF | FF | 706 | -2.1 | -2.1 |
| SI | SI | 535 | -2.8 | -2.8 |
| KC | CU | 980 | +1.1 | +1.1 |
| CH | CH | 481 | +1.0 | +1.0 |
| FC | FC | 223 | -3.2 | -3.2 |
| SL | SL | 21 | -3.8 | -3.8 |

The regression test replays the source values through SQL aggregation and the real
profile API, checking both overall and all six pitch types. Existing Statcast
pitch classifications remain separate; the Savant arsenal page groups Nola's KC
as CU. Grouped Statcast Search can use the original pitch type.

Formula: `100 * SUM(non-null pitcher run value) / COUNT(physical pitches)`.
The database stores the batter-facing value, so the SQL sum is negated. Zero is
valid data. Missing physical-pitch run values are omitted from the sum but their pitches remain
in the denominator. Coverage is exposed in the API and
in metric hover text. Overall rates use all valued pitches, never an unweighted
average of pitch-type rates. Display uses one decimal and positive is good for the
pitcher. All dashboard filters apply before aggregation.

Existing databases contain the snapshot originally ingested. Later Savant
revisions or different date coverage can change the displayed result; matching
the calculation does not update the underlying pitch dataset. No stored pitches
are overwritten by this feature.


The October 19 live check found the cached Nola total was -22.039 rather than the
current source's -22.272: the same method displayed -0.7 vs -0.8 from updated data.
The dedicated `statcast refresh-run-values` command corrects this by retrieving the
current detailed CSV within each stored pitcher-season's date window and comparing
its sum and denominator to Savant's explicitly named `delev_pitcher_run_exp` total.
Only after both agree are matching existing pitch rows updated. Pitcher-seasons
with missing source identities, truncated responses, count mismatches or mismatched
neutral totals are preserved. No velocity, pitch identity, player, game, or other
performance fields are changed, and no new pitches are inserted.


## Missing-value denominator regression

Brayan Bello (678394), 2026 export checked October 19: 2,152 event rows,
2,140 physical pitches, 2,133 non-null run values, and 12 automatic events with
no pitch type. Seven physical pitches on March 31 have missing run value.
Savant nevertheless reports denominator 2,140 and neutral pitcher total +3.939,
giving +0.184065421 per 100 before rounding. The validator checks physical pitch
counts rather than non-null run-value counts. The dashboard uses the same physical
pitch denominator and reports missing-value coverage separately. Source total
verification remains mandatory, and missing values remain null in storage.
