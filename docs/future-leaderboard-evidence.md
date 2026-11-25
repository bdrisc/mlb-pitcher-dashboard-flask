# Published leaderboard evidence

Read-only acquisition and offline replay, bound to the exact staged and
quarantined correction reports. Four raw official responses are retained:
FanGraphs type 36 Stuff+/Location+/Pitching+ and type 8 FIP/xFIP/SIERA,
Savant xERA and spin-based Active Spin. No handedness splits are requested.
The output contains planned rows only for staged pitchers and lists unmatched
source IDs, absent staged IDs and missing values. Missing does not mean zero.
An active-spin export without a year is explicitly identified as such.
A PASS indicates reproducible evidence, not complete coverage or permission
to publish. Independent identity verification, coverage review and a later
transactional import are required. Real 2027 sources are not yet tested.

## Synthetic rehearsal

```powershell
$backup = "$env:LOCALAPPDATA\MLB-Pitcher-Dashboard-Backups\20261125_150934"
$stage = "$backup\future_staging_synthetic_01\staging_report.json"
$correction = "$backup\future_corrections_synthetic_01\correction_report.json"
$stageSha = (Get-FileHash $stage -Algorithm SHA256).Hash.ToLowerInvariant()
$correctionSha = (Get-FileHash $correction -Algorithm SHA256).Hash.ToLowerInvariant()
$out = "$backup\future_leaderboard_evidence_synthetic_01"
python -m scripts.acquire_future_leaderboards --synthetic `
  --staging-report "$stage" --staging-sha "$stageSha" `
  --correction-report "$correction" --correction-sha "$correctionSha" --output "$out"
$report = "$out\leaderboard_evidence.json"
$reportSha = (Get-FileHash $report -Algorithm SHA256).Hash.ToLowerInvariant()
python -m scripts.acquire_future_leaderboards --synthetic `
  --staging-report "$stage" --staging-sha "$stageSha" `
  --correction-report "$correction" --correction-sha "$correctionSha" `
  --verify-report "$report" --report-sha "$reportSha"
```

Expected: two grade rows, one combined rate row, one spin row, zero missing
values, four raw responses and LEADERBOARD_EVIDENCE_PASS_NOT_APPLIED.
No database connection or writes. Use a new output folder for retries.
