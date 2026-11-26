# Independent MLB schedule and identity evidence

Read-only check using MLB Stats API schedule and people endpoints, not the
Statcast pitch export. An explicit reviewed date window is required, not a
window inferred from the first and last staged pitch. Completed regular-season
game IDs and official dates must exactly match staging. Postponed/cancelled
games are recorded separately; unresolved games fail closed. Pitcher names and
throwing hands must agree with MLB people records, and batter identities and
handedness must agree (switch hitters may appear on either side).
Strict name matching and official-date matching may need reviewed exceptions
for aliases, resumed games or unusual handedness. No automatic exceptions.
This is not independent pitch-event completeness, team-code validation or
FanGraphs-to-MLB crosswalk verification. Those remain blockers. Real 2027 API
response behavior has not been exercised.

```powershell
$backup = "$env:LOCALAPPDATA\MLB-Pitcher-Dashboard-Backups\20261125_150934"
$stage = "$backup\future_staging_synthetic_01\staging_report.json"
$stageSha = (Get-FileHash $stage -Algorithm SHA256).Hash.ToLowerInvariant()
$out = "$backup\future_mlb_scope_synthetic_01"
python -m scripts.acquire_future_mlb_scope --synthetic `
  --staging-report "$stage" --staging-sha "$stageSha" `
  --start 2027-04-01 --end 2027-04-02 --output "$out"
$report = "$out\mlb_scope_evidence.json"
$reportSha = (Get-FileHash $report -Algorithm SHA256).Hash.ToLowerInvariant()
python -m scripts.acquire_future_mlb_scope --synthetic `
  --staging-report "$stage" --staging-sha "$stageSha" `
  --start 2027-04-01 --end 2027-04-02 `
  --verify-report "$report" --report-sha "$reportSha"
```

Expected: two completed games, one pitcher, one batter, two unique MLB people,
MLB_SCOPE_EVIDENCE_PASS_NOT_APPLIED. No database or network writes.
Synthetic mode does not access the internet.
