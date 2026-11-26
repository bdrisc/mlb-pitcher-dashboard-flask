# Independent FanGraphs crosswalk evidence

The Chadwick Bureau register is a separate public player-identity compilation.
The acquisition uses all sixteen people CSV shards at an explicitly selected
40-character Git commit, not a mutable branch. It retains exact response
bytes, source URLs and checksums. For every planned FanGraphs ID, both its MLB
ID and its unique Chadwick person key must be consistent. Conflicting,
duplicate or missing mappings block approval, even if FanGraphs and historical
database mappings agree. No name-based guessing or historical fallback.

The report is bound to the checksum-approved staged, correction, leaderboard
and MLB scope reports. The latter two are rebuilt from their raw archives.
This checks planned mappings only, not provider coverage or unpublished
metrics. Register lag, alternate IDs or ambiguous rows need independent
review; no automatic exceptions. Real-source compatibility remains untested.

## Offline synthetic rehearsal

```powershell
$backup = "$env:LOCALAPPDATA\MLB-Pitcher-Dashboard-Backups\20261125_150934"
$stage = "$backup\future_staging_synthetic_01\staging_report.json"
$correction = "$backup\future_corrections_synthetic_01\correction_report.json"
$leaderboard = "$backup\future_leaderboard_evidence_synthetic_01\leaderboard_evidence.json"
$scope = "$backup\future_mlb_scope_synthetic_01\mlb_scope_evidence.json"
$stageSha = (Get-FileHash $stage -Algorithm SHA256).Hash.ToLowerInvariant()
$correctionSha = (Get-FileHash $correction -Algorithm SHA256).Hash.ToLowerInvariant()
$leaderboardSha = (Get-FileHash $leaderboard -Algorithm SHA256).Hash.ToLowerInvariant()
$scopeSha = (Get-FileHash $scope -Algorithm SHA256).Hash.ToLowerInvariant()
$out = "$backup\future_crosswalk_synthetic_01"
python -m scripts.acquire_future_crosswalk --synthetic `
  --staging-report "$stage" --staging-sha "$stageSha" `
  --correction-report "$correction" --correction-sha "$correctionSha" `
  --leaderboard "$leaderboard" --leaderboard-sha "$leaderboardSha" `
  --scope "$scope" --scope-sha "$scopeSha" --output "$out"
$report = "$out\crosswalk_evidence.json"
$reportSha = (Get-FileHash $report -Algorithm SHA256).Hash.ToLowerInvariant()
python -m scripts.acquire_future_crosswalk --synthetic `
  --staging-report "$stage" --staging-sha "$stageSha" `
  --correction-report "$correction" --correction-sha "$correctionSha" `
  --leaderboard "$leaderboard" --leaderboard-sha "$leaderboardSha" `
  --scope "$scope" --scope-sha "$scopeSha" `
  --verify-report "$report" --report-sha "$reportSha"
```

Expected: one verified mapping, sixteen archived synthetic shards,
CROSSWALK_EVIDENCE_PASS_NOT_APPLIED. No network or database writes.
