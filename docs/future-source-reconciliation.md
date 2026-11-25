# Strict future-season reconciliation (milestone 14, second increment)

This command is offline and read-only with respect to every database. It reads
the source copies from a successful quarantined staging run, verifies their
checksums, and compares every pitch against separately reviewed source
evidence. A successful result is a correction plan, not a database update.
Do not use the legacy refresh commands to apply this plan to production.

## Synthetic rehearsal

After PR 66's successful synthetic staging run, execute:

```powershell
$backup = "$env:LOCALAPPDATA\MLB-Pitcher-Dashboard-Backups\20261125_150934"
$stage = "$backup\future_staging_synthetic_01\staging_report.json"
$digest = (Get-FileHash $stage -Algorithm SHA256).Hash.ToLowerInvariant()
python -m scripts.reconcile_future_sources --synthetic `
  --staging-report "$stage" --staging-sha "$digest" `
  --output "$backup\future_staging_synthetic_01\reconciliation_plan.json"
```

Expected: RECONCILIATION_PLAN_PASS_NOT_APPLIED, one pitcher, six pitches,
two official-fixture PA, six planned patches and zero revisions.
The independent hardcoded fixture intentionally changes all six RV values
relative to the staged CSV. It is not an official 2027 source.

## Real-source evidence contract

Use a reviewed JSON bundle and its SHA-256 with --bundle and --bundle-sha,
rather than --synthetic. The bundle has the exact structure returned by
synthetic_bundle() in scripts/reconcile_future_sources.py, except synthetic
is false, the intended season/window is specified, and every staged pitcher
has one packet. Each packet includes independently acquired regular-season
Savant detail (including context-neutral, hitter-sign delta_run_exp), its
official pitcher-sign neutral RV aggregate, official PA detail and the
official PA aggregate. Preserve exact IDs, dates, handedness, descriptions,
events and weights. Use blank strings for absent event labels. Record
original acquisition URLs, parameters, timestamps and raw response hashes
outside the normalized bundle as part of source review; the current command
does not fetch or authenticate these sources. No extra or missing pitch IDs
or PA IDs are allowed. Any pitch classification, event, description or
handedness revision blocks all patches; rebuild the entire final source
snapshot and recalculate dependencies before reconciliation can pass.

The plan contains exact pitch-keyed RV and wOBA components, not inferred
weights. It explicitly leaves publication blocked. Real source acquisition,
transactional application to a fresh isolated candidate, independent
post-application database checks, published leaderboard reconciliation,
player identity resolution, future-season coefficients and reference
validation remain separate work. Do not use a synthetic plan for any
real candidate.
