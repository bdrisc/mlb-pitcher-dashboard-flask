# Controlled historical release rehearsal

This release tool intentionally has no production-write path. It uses the
previously restored, verified full-league 2025–26 local recovery database,
not the live database. The exact reviewed local/public archives, the original
660-case audit, both recovery reports and the fingerprint baseline are
required. No source download, production credential, or Neon connection is
needed. A new random local candidate database is cloned from the recovery
database and reduced to the same 50-pitcher 2026 public cohort. All required
pitcher and batter players, games, and full-league 2026 published metrics
are retained. Historical original rows and reference files are never edited.

Run from a clean main checkout with the virtual environment and PostgreSQL
utilities on PATH. Keep several GB of free local disk space.

```powershell
$env:Path += ";C:\Program Files\PostgreSQL\17\bin"
$backup = "$env:LOCALAPPDATA\MLB-Pitcher-Dashboard-Backups\20261125_150934"
python -m scripts.rehearse_snapshot_release rehearse `
  --baseline outputs/snapshot_integrity/verified_2026.json `
  --audit extended_dashboard_parity_2026.json `
  --backups "$backup" `
  --local-recovery "$backup\recovery_test_1e9698ec9b81.json" `
  --public-recovery "$backup\recovery_public_1712_35b9ea2c5f52.json" `
  --output "$backup\release_rehearsal_01"
```

The source is fingerprinted before and after. The clone is independently
fingerprinted before cohort derivation. The candidate receives the exact
same 660 API comparison plan, including expected HTTP status and pitch
counts, all required profile/chart sections and the shared pitcher index.
Any discrepancy prevents archive export. Both test app connections are
read-only. The archive and parity report are bound by checksums to a release
manifest. This candidate is not assumed to be identical to the existing Neon
database at the byte level: historical non-displayed source values,
timestamps and metadata may differ. It is a rehearsal candidate only.

Once the script prints REHEARSAL_PASS_NOT_PUBLISHED, review the manifest
and report, then substitute the printed manifest digest:

```powershell
python -m scripts.rehearse_snapshot_release review --output "$backup\release_rehearsal_01" --manifest-sha <printed-sha256>
```

This independently verifies artifact checksums and audit evidence and prints
REHEARSAL_REVIEW_PASS_NO_PUBLICATION. It never changes Render, Neon, or
any database. Keep the outputs private. The archive must also be restored
and fingerprinted before any actual release. Failed candidate databases
and evidence are retained for diagnosis. Use a new output directory for
a retry; never overwrite reviewed evidence.

## Future-season source preflight

```powershell
python -m scripts.audit_future_statcast_sources --season 2027 --schedule reviewed_schedule.json --output source_manifest.json statcast_2027_*.csv.gz
```

Supply explicit paths (expand wildcard paths yourself if your shell does not).
The schedule JSON maps independently reviewed completed regular-season game
IDs to ISO game dates for the intended acquisition window. The tool hashes
source files, rejects historical or non-regular-season rows, duplicate
natural keys across files, inconsistent games, invalid counts, and missing
or extra game IDs. This is a source preflight, not proof of every pitch's
completeness or correctness. Official schedule review and game/pitch coverage
validation are still required before any real ingestion.

## Dependency and publication policy

For future ingestion, preserve 2025–26 in the full-league staging copy.
Validate all raw sources and resolve classifications, outcome fields and
trajectory inputs before derived flags, angles and run values. Recompute
derived metrics only for the candidate season using reviewed definitions.
Import saved published metrics rather than independently fetching twice.
Build full-league movement, role, location and adjusted-angle references from
the validated full-league candidate; do not derive these from the public
cohort. Independently verify reference metadata, denominators and checksums.
The existing 2026 loaders and completed-season role thresholds are not
sufficient for in-progress 2027 data. Historical rehearsal reuses the already
independently verified references and derived inputs rather than recomputing
or changing the sealed historical snapshot.

Actual new-season ingestion, season-aware reference generation, staging
promotion, candidate archive restore, coordinated Render/Neon publication
and rollback require a subsequent implementation and explicit release
approval. No command in this change can publish to production.
