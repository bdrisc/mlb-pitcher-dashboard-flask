# Package A — independent release evidence

Run a single command against the retained synthetic checkpoint:

```powershell
$backup = "$env:LOCALAPPDATA\MLB-Pitcher-Dashboard-Backups\20261125_150934"
python -m scripts.validate_future_release_evidence --synthetic-backup "$backup" --output "$backup\package_a_synthetic_01"
```

The command replays the existing staged files, correction plan, Savant raw
archive, leaderboards and MLB scope evidence; checks the retained metric
import report; acquires and replays the sixteen synthetic register shards
and two game feeds; and produces package_a_report.json. Expected status:
PACKAGE_A_SYNTHETIC_PASS_NOT_APPLIED, one mapping, two games, six physical
pitches. No network access or database writes in synthetic mode.

The report is evidence, not approval to publish. The existing database
checkpoint itself will be re-fingerprinted before release in Package C.
The game-feed comparison requires exact physical pitch keys, owners,
batters, hands and team codes. Explicit common team abbreviations are
normalized; unknown mismatches fail. Non-pitch plays are listed, not
silently counted as pitches. Automatic count events, ambiguous mid-PA
substitutions and other unsupported events fail closed for manual
normalization review. This does not prove full official PA/event
completeness or independent pitch classification and remains untested
against real live feeds. Published coverage gaps remain visible.

Real acquisition requires --inputs with an independently reviewed JSON
manifest, --inputs-sha with its pinned checksum and --register-commit
with a full immutable Chadwick commit. Each manifest key (staging, plan,
correction, savant, leaderboard, scope) maps to an object with absolute
path and sha256. Real mode does not accept an import checkpoint.
Real mode always reports PACKAGE_A_EVIDENCE_REVIEW_REQUIRED and cannot
authorize writes. Date-window and provider as-of consistency, omissions,
source schema behavior, exceptional events and coverage still need review.
For offline replay use --verify-report and --report-sha instead of --output,
with the same input arguments and register commit. Keep all raw archives.

CI still enforces exact lint, format, full tests and Docker. Formatting
failures additionally print the formatter's diff so fixes can be applied
directly to the branch without asking the operator to reformat files.
