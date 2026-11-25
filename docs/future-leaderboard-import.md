# Quarantined synthetic leaderboard import

This rehearsal replays the checksum-approved leaderboard evidence, checks the
corrected candidate fingerprint, clones it locally, and inserts only target-year
published grades, rates and spin values inside one PostgreSQL transaction.
It checks staged pitch owners, player IDs and historical FanGraphs mappings,
rejects existing target-year metric rows, reads back exact planned values, and
compares all seven sealed table fingerprints and all out-of-scope metric rows.
A failed transaction rolls back; any scratch clone remains quarantined.
Only synthetic inputs are enabled. Real independent MLB player identity
verification and coverage review remain prerequisites; historical crosswalk
consistency alone is not proof of real identity.

```powershell
$backup = "$env:LOCALAPPDATA\MLB-Pitcher-Dashboard-Backups\20261125_150934"
$stage = "$backup\future_staging_synthetic_01\staging_report.json"
$correction = "$backup\future_corrections_synthetic_01\correction_report.json"
$report = "$backup\future_leaderboard_evidence_synthetic_01\leaderboard_evidence.json"
$stageSha = (Get-FileHash $stage -Algorithm SHA256).Hash.ToLowerInvariant()
$correctionSha = (Get-FileHash $correction -Algorithm SHA256).Hash.ToLowerInvariant()
$reportSha = (Get-FileHash $report -Algorithm SHA256).Hash.ToLowerInvariant()
$out = "$backup\future_leaderboard_import_synthetic_01"
python -m scripts.apply_future_leaderboards --synthetic `
  --staging-report "$stage" --staging-sha "$stageSha" `
  --correction-report "$correction" --correction-sha "$correctionSha" `
  --report "$report" --report-sha "$reportSha" --output "$out"
```

Expected: two grade rows, one rate row, one spin row,
LEADERBOARD_IMPORT_PASS_QUARANTINED. No writes to source or production.
Retain the report and candidate. Use a new output folder for any retry.
