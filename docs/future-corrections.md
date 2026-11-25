# Transactional future-season corrections (milestone 14)

Only an approved reconciliation plan can be applied. Rebuild the plan from
the checksum-bound staged files and reviewed evidence, verify the original
recovered historical database and the staging candidate, then clone staging
to a new isolated loopback PostgreSQL database. No production connection
is used. Only neutral RV and Savant wOBA numerator/denominator can change.

The write transaction verifies the entire clone fingerprint, locks the
seven model tables, applies season- and pitcher-scoped updates, checks
every corrected field and official pitcher aggregates, and compares a
fingerprint excluding exactly the three approved future-season fields.
Any failure inside the transaction rolls back all updates. A later audit
failure leaves the committed isolated clone quarantined, without a passing
report. The original staged database and recovered historical source are
never updated. A passing report is not publication approval.

## Synthetic integration rehearsal

Run after successful PR 66 staging and PR 67 reconciliation:

```powershell
$backup = "$env:LOCALAPPDATA\MLB-Pitcher-Dashboard-Backups\20261125_150934"
$stage = "$backup\future_staging_synthetic_01\staging_report.json"
$plan = "$backup\future_staging_synthetic_01\reconciliation_plan.json"
$stageSha = (Get-FileHash $stage -Algorithm SHA256).Hash.ToLowerInvariant()
$planSha = (Get-FileHash $plan -Algorithm SHA256).Hash.ToLowerInvariant()
python -m scripts.apply_future_corrections --synthetic `
  --baseline outputs/snapshot_integrity/verified_2026.json `
  --audit extended_dashboard_parity_2026.json `
  --backups "$backup" `
  --local-recovery "$backup\recovery_test_1e9698ec9b81.json" `
  --public-recovery "$backup\recovery_public_1712_35b9ea2c5f52.json" `
  --staging-report "$stage" --staging-sha "$stageSha" `
  --plan "$plan" --plan-sha "$planSha" `
  --output "$backup\future_corrections_synthetic_01"
```

Expected: CORRECTIONS_PASS_QUARANTINED; six corrected pitches and two PA.
The synthetic RV totals and weights are fixtures, not real official data.
The correction report retains all prior release blockers until a later
release gate independently validates them. Real source acquisition,
published leaderboards, player identity resolution, new-season coefficients,
reference generation, candidate export/recovery and production promotion
remain separate tasks.

For a real plan, omit --synthetic and provide --bundle with the same
reviewed evidence file used for reconciliation. The plan's recorded
bundle evidence must match exactly. Keep approved hashes independently;
computing a fresh digest of an unreviewed artifact is not approval.
