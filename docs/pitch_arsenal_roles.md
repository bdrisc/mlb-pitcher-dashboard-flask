# Pitch Arsenal Roles (v1)

Seven descriptive metrics use the profile's existing SQL counts and sums. Get Ahead is the strike fraction on physically thrown 0-0 pitches (called strikes, whiffs, fouls and balls in play; automatic calls excluded). GB uses classified batted balls. RV is pitcher-positive and requires complete stored RV coverage. Custom xRV requires 150 scored pitches and at least 95% pitch and contact coverage. Other minimums: 60 0-0 pitches, 80 swings, 100 out-of-zone pitches, 60 two-strike pitches, 40 classified batted balls, 150 RV pitches. Raw statistics can be shown below qualification.

Percentiles are unweighted empirical midranks of qualifying individual pitcher/pitch-type offerings from the same MLB regular season, exact Statcast code, pitcher hand, batter side and count scope (20 minimum qualifying offerings). No fallback. The selected date, team and home/away filters change the numerator sample, not the full-season reference. All Seasons has no percentile reference. Most Effective uses the unrounded raw metric; Best vs. Peers uses the percentile (ties shown).

## Generate references locally before merging/deploying

Use the complete, audited local database, not the Render/Neon cohort. Refresh pitch labels and Savant run value consistently first. Confirm regular-season games and source coverage against the official season schedule and acquisition manifests; the exporter's 750-pitcher, 650,000-pitch and 2,400-game gates reject obvious subsets but are not proof of completeness.

```powershell
python -m scripts.build_pitch_role_reference --season 2025
python -m scripts.build_pitch_role_reference --season 2026
python -m pytest -q
git add data/league_pitch_roles_2025.json data/league_pitch_roles_2026.json
git commit -m "Add audited full-MLB pitch role reference distributions"
```

Commit the same generated files for Render and local installations. Rebuild local Docker image if using Docker. Never substitute public cohort percentiles. The API exposes the reference SHA-256 and the parity checker includes role data. After deployment run the existing parity audit against the public cohort:

```powershell
python -m scripts.check_dashboard_parity --all --season 2026
```

Do not interpret qualification or descriptive percentiles as predictive pitch quality or a causal pitch usage recommendation. Full-league reference generation and parity checks must be completed before claiming production accuracy.
