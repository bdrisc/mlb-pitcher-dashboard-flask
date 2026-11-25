# Future Savant evidence acquisition and replay

This tool never connects to a database. It uses the checksum-approved staged
pitch population and regular-season date window. For each pitcher it archives
four independent HTTP responses: Statcast detail CSV, neutral RV aggregate,
PA detail and wOBA aggregate. It preserves raw response bytes, exact query
parameters and URLs, HTTP status/content type, UTC timestamps and SHA-256.
It rejects redirected, empty, oversized, malformed, truncated or mismatched
responses. A failing acquisition retains its raw files but is not approved.

The normalized bundle must reproduce the archived raw responses and pass
the existing strict reconciliation checks. Real reconciliation and correction
commands now require replayable evidence, rather than manually assembled JSON.
A reviewed bundle digest binds the provenance and all raw-file checksums.
The archive is not a cryptographic attestation from MLB; human review and
independent schedule/completeness checks are still necessary.

## Offline synthetic rehearsal

```powershell
$backup = "$env:LOCALAPPDATA\MLB-Pitcher-Dashboard-Backups\20261125_150934"
$stage = "$backup\future_staging_synthetic_01\staging_report.json"
$stageSha = (Get-FileHash $stage -Algorithm SHA256).Hash.ToLowerInvariant()
$out = "$backup\future_savant_evidence_synthetic_01"
python -m scripts.acquire_future_savant --synthetic `
  --staging-report "$stage" --staging-sha "$stageSha" --output "$out"
$bundle = "$out\evidence_bundle.json"
$bundleSha = (Get-FileHash $bundle -Algorithm SHA256).Hash.ToLowerInvariant()
python -m scripts.acquire_future_savant --synthetic `
  --staging-report "$stage" --staging-sha "$stageSha" `
  --verify-bundle "$bundle" --bundle-sha "$bundleSha"
```

Both commands should print SAVANT_EVIDENCE_PASS_NOT_APPLIED, one pitcher,
six pitches, two PA and four archived responses. Synthetic mode performs no
network requests and is never real official evidence.

For real future-season acquisition omit --synthetic and supply a real
approved staging report. All four requests use hfGT=R|, including wOBA.
Retain the raw directory alongside the bundle. Requests are serial and
paced; failures stop the run rather than silently skipping pitchers.
Exact source mismatch requires restaging; use a new directory for retries.
Live 2027 acquisition, independent completed-game schedule coverage, actual
source schema behavior, leaderboards and player identity remain unverified.
