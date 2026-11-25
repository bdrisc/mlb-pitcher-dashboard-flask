# Future-season staging, milestone 14

The new command derives an isolated candidate from the verified historical
recovery database. It does not publish, connect to Neon, change the current
dashboard or train reference models. Each run starts from a fresh clone.
Do not retry by writing into a failed candidate.

The real-source path requires an explicit reviewed source manifest SHA-256,
schedule JSON and all source files in their reviewed order. It reruns the
source preflight and copies verified bytes into a private new output directory.
All future regular-season pitches are insert-only; historical game IDs cannot
be reused. Existing historical player metadata is frozen, including rows
that previously existed only as batters. This deliberately defers identity
and handedness reconciliation, which is a separate release blocker.
The ordinary legacy ingestion command is unchanged unless the new guarded
options are explicitly passed.

The current ingestion service calculates the outcome flags and trajectory
angles from the final incoming source, then calculates adjusted angles using
the existing frozen models. It does not call independent refresh jobs against
either live database. Stored future pitch values are checked against the
transformed source, while every original table's historical rows are checked
against the sealed 2025–26 baseline. The recovered source and references are
checked again. The resulting candidate is quarantined: raw RV and wOBA
columns are not certified simply by being present, adjusted-angle references
are provisional for future use, and xRV needs reviewed new-season coefficients.

## Synthetic integration rehearsal

Run from the repository in the active virtual environment:

```powershell
$backup = "$env:LOCALAPPDATA\MLB-Pitcher-Dashboard-Backups\20261125_150934"
python -m scripts.stage_future_ingestion --synthetic `
  --baseline outputs/snapshot_integrity/verified_2026.json `
  --audit extended_dashboard_parity_2026.json `
  --backups "$backup" `
  --local-recovery "$backup\recovery_test_1e9698ec9b81.json" `
  --public-recovery "$backup\recovery_public_1712_35b9ea2c5f52.json" `
  --output "$backup\future_staging_synthetic_01"
```

This generates two artificial games and six artificial pitches, including
called strikes, foul tips and hard contact. The identifiers are intentionally
outside the historical dataset. A successful result is
STAGING_PASS_QUARANTINED, never an approval for publishing synthetic records.
The database and report are retained for review.

## Real-source staging

Run the offline preflight documented in release-rehearsal.md, review its
output and record the manifest SHA-256. Use the same backup and baseline
arguments as above, omit --synthetic, provide a new output directory, and
add --season 2027 --schedule reviewed_schedule.json --manifest
source_manifest.json --manifest-sha DIGEST followed by the exact source
paths. Acquire the full intended regular-season window as one reviewed
snapshot; incremental merge into an older candidate is not supported.

No automatic acquisition or independent official source refresh is added
by this change. The preflight does not prove every pitch is present, and the
storage check reuses the existing transformation rather than independently
validating every formula. Publication remains blocked until neutral RV and
wOBA are reconciled, official published metric snapshots are validated,
player metadata is resolved, season-aware references and parity are tested,
and a candidate archive is recovered and explicitly approved.
