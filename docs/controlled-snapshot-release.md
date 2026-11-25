# Controlled snapshot release

The 2026 regular-season snapshot was reviewed on November 25, 2026. The deployed
baseline is commit 36c6319: 868 pitchers and 714,114 pitches locally, 50 pitchers
and 142,141 pitches publicly. Extended audit: 660/660 comparisons passed,
including 16 matching empty responses. This is an API parity result, not a claim
that all source values or every possible filter combination were independently
verified.

## Protect and seal the baseline

Production startup applies schema migrations but never runs legacy background
data maintenance, even if STARTUP_MAINTENANCE_ENABLED is set to 1.
The scheduled Render deploy hook is removed. A manual checklist workflow does
not write any data. Development startup maintenance is opt-in; only use it with
a disposable development database, not the reviewed local database.

Keep the passing extended_dashboard_parity_2026.json outside Git. It is pinned
by the normalized SHA-256 in scripts/snapshot_integrity.py. In the repository:

```powershell
python -m scripts.snapshot_integrity capture --report extended_dashboard_parity_2026.json --baseline outputs/snapshot_integrity/verified_2026.json
python -m scripts.snapshot_integrity verify --baseline outputs/snapshot_integrity/verified_2026.json
```

The script reads local DATABASE_URL from the environment/.env and prompts for
the Neon URL without echoing it. It fingerprints each database independently
in a repeatable-read read-only transaction. All columns in players, games,
pitches, FanGraphs grades, published pitching metrics, active spin and the
migration version are included, including timestamps. Ingestion run logs are
excluded. PostgreSQL streams row SHA-256 digests in primary-key order rather
than sending raw records. The baseline must not be overwritten. Store it and
the passing report in a separate private backup location. Fingerprints detect
drift; they do not independently certify the correctness of current records,
replace database backups, or prove equivalence across PostgreSQL major versions.

## Before any future release

1. Verify the sealed baseline. If drift appears, stop and investigate.
2. Create encrypted/private full PostgreSQL backups of both databases using
   pg_dump --format=custom and the appropriate direct database endpoints.
   Check exit codes, inspect pg_restore --list, and restore to isolated databases
   to prove recovery. Keep the exact prior code and reference files.
3. Use a disposable full-league local staging database and an isolated Neon
   staging branch/database, never the live connection. Fetch source snapshots
   once, retain immutable source files, dates, digests and coverage, and use
   the same reviewed inputs for both destinations. Keep the historical 2025
   and 2026 snapshots unchanged unless explicitly reviewing a correction.
4. Audit source natural keys, duplicate IDs, schedule coverage, classification
   changes, missing values, flags and official outcome fields. Ingest and
   resolve source corrections first. Recompute tracking fields and outcome
   flags, then pitch-type-dependent adjusted angles, RV and contact-adjusted
   metrics with the final inputs. Refresh published grades, rates and active
   spin from saved source snapshots rather than independent live fetches.
5. Rebuild and independently validate full-league references for the intended
   season (roles, movement, location and adjusted-angle models as appropriate).
   Current location loader is pinned to 2026. Adding 2027 needs explicit
   season-aware implementation, tests and a new reviewed manifest.
6. Derive the production cohort from the same validated full-league staging
   snapshot; do not independently ingest public data. Check all dependent
   players/games and reference coverage. Audit the candidate application and
   candidate databases, including full profiles, charts, filtered and empty
   cases, index and pitch counts; require zero unexplained discrepancies.
7. Review the candidate manifest, backup restore proof, and all audit results
   before explicit publication approval. Prefer switching the service to an
   independently validated replacement database with compatible code and
   references; retain the prior database, credentials and deployable commit
   for rollback. Coordinate the release so code and database snapshots cannot
   be mixed. Repeat parity and health checks after publication.
8. If any post-release check fails, restore the matching previous code,
   database and reference set, and recheck parity. Do not blindly retry a
   source refresh or re-enable startup maintenance.

This is a protected baseline and operator-controlled release runbook, not an
implemented automated 2027 ingestion, staging, promotion or rollback system.
Those features need a real candidate dataset and separate validated tooling
before live publication. No scheduled data writer is enabled.

For a fresh disposable local Docker database, the legacy demo seed can be
explicitly enabled with STARTUP_MAINTENANCE_ENABLED=1 in the shell before
starting Docker Compose. Never use that flag against a verified snapshot.
