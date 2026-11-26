# Package C — final synthetic release rehearsal

This is the final offseason infrastructure rehearsal. It never publishes.
Use the existing Package A and B reports, the original backup directory,
the isolated full imported candidate, and the earlier historical public
rehearsal candidate. Do not substitute either live database.

```powershell
$env:Path += ";C:\Program Files\PostgreSQL\17\bin"
$backup = "$env:LOCALAPPDATA\MLB-Pitcher-Dashboard-Backups\20261125_150934"
python -m scripts.rehearse_future_release --synthetic-backup "$backup" --output "$backup\package_c_synthetic_01"
```

Keep several GB of free disk space. A new directory and two randomly named
loopback candidate databases are created. Existing databases, backups,
historical reference files and the empty future registry are not edited.
The rehearsal replays Package A, validates Package B and reproduces its
location payload from the imported full candidate, verifies historical
fingerprints, derives a public-sized 2026 cohort plus the 2027 fixture,
reruns 660 historical and 26 future API comparisons, exports the candidate
and restores the archive into a new database, then checks its fingerprint
and future API parity. The earlier derived historical public candidate is
not asserted byte-identical to live Neon. The new candidate is synthetic
and permanently ineligible for release.

Expected: PACKAGE_C_SYNTHETIC_PASS_NOT_PUBLISHED and a manifest SHA-256.
The script automatically verifies the manifest; independent later review:

```powershell
python -m scripts.rehearse_future_release --output "$backup\package_c_synthetic_01" --manifest-sha <printed-digest>
```

## Actual 2027 release gate (operator controlled)

1. Verify the live local/public seals, take fresh private backups and
   restore each; stop if any historical fingerprint differs. Keep the
   old Render commit, configuration, database and verified references.
2. Freeze a reviewed regular-season-to-date window from Opening Day.
   Acquire one immutable set of provider data and complete game feeds;
   run source preflight, isolated staging, Savant reconciliation and
   corrected-candidate validation. Missing pitches, automatic count
   events, revised classifications and unknown identities must be
   explicitly resolved rather than silently discarded.
3. Replay Package A against real evidence, independently review source
   coverage, crosswalk and nonpitch events. Real leaderboard import is
   currently blocked by its synthetic-only guard; validate and implement
   the approved real import before publication. Do not bypass that guard.
4. Generate Package B reference proposals against the corrected complete
   league snapshot. Independently review the actual source coefficient
   vintage and artifact checksums. Missing references remain unavailable.
   Install only reviewed real entries, never fixture files. Recheck
   reference metadata, exact scope and the final database fingerprint.
5. Construct a real public replacement from the actual restored public
   history plus the selected 2027 cohort from the same validated full
   candidate. Do not replace existing public historical rows with a
   potentially different locally derived snapshot. Validate all seven
   historical table fingerprints and future identities, coverage and
   metrics. Audit full profiles/charts, filtered and empty cases and
   restore the final archives. Package C's synthetic comparator is a
   rehearsal of these gates, not a real-season authorization.
6. Obtain explicit approval for the exact release manifest, candidate
   database identities, intended cohort, code commit and reference
   digests. Stage the matching code and database in isolation. Keep the
   currently working deployment intact until candidate health and parity
   pass; coordinate the connection and code switch. Verify live health,
   index, historical fingerprints and parity immediately after promotion.
7. If health, identity, coverage or parity fails, switch back to the
   previous database AND corresponding code/reference commit. Verify the
   old snapshot and parity again. Retain the failed candidate for
   diagnosis; never retry by enabling startup ingestion.

No live switch, real source approval or production rollback is automated
by this synthetic command. These require actual 2027 data, real-season
validation and explicit operator approval. A synthetic success is not
proof of compatibility with future live provider schemas.
