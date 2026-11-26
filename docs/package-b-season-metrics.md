# Package B — season-specific metric infrastructure

The existing 2025 and 2026 coefficient values and reference files are unchanged.
Future xRV uses only reviewed FanGraphs Guts seasonal weights (including
non-contact pitch availability). An unknown future season displays no xRV.
Location, movement and pitch-role league comparisons use only the season-specific
artifacts in the explicitly reviewed data/future_season_references.json registry.
An absent or altered file disables its comparison; no future cohort fallback.
Existing historical reference paths remain unchanged.

The registry ships empty. New entries must name the season, complete MLB
regular-season-to-date scope, window, exact population counts, Package A and
candidate fingerprints, and artifact digests. The coefficient vintage must
match the snapshot through date. No synthetic entry can be loaded. A real
review must independently confirm that the date window starts with the first
regular-season game and that the source and weights are current. The CSV
must contain Season,wOBAScale,w1B,w2B,w3B,wHR (additional columns allowed).
The operator archives the original Guts export and independently approves its
checksum; the script does not claim to authenticate the source website.

## One local rehearsal after Package A

```powershell
$backup = "$env:LOCALAPPDATA\MLB-Pitcher-Dashboard-Backups\20261125_150934"
python -m scripts.build_future_season_references --synthetic-backup "$backup" --output "$backup\package_b_synthetic_01"
```

This replays Package A, opens only the corrected loopback candidate read-only,
checks its sealed fingerprint, validates per-game counts, exports an isolated
location file, archives synthetic coefficients, then rechecks candidate and
historical references. The two-game fixture is intentionally too small for
movement or role distributions. CI tests exercise missing, tampered,
wrong-season and synthetic references and the new xRV path. Expected status:
PACKAGE_B_SYNTHETIC_PASS_NOT_APPLIED. No registry or database changes.

Real builds require --inputs, --inputs-sha, --package-a, --package-a-sha,
--register-commit and (when available) --guts-csv, --guts-sha, --guts-as-of.
Artifacts are proposals only, not approval to install or publish. Future
movement retains the 300 eligible pitchers / 200,000 eligible pitches gate;
roles require 300 pitchers, 200,000 pitches and 600 games, plus existing
per-role opportunity and peer gates. These are conservative descriptive
availability thresholds, not learned calibration or proof of population
completeness. Location comparisons retain existing cell thresholds. Before
those thresholds, league comparisons may be absent while raw pitcher metrics
remain available. Real provider behavior and review remain necessary.

Package C will integrate reviewed registry promotion, exact deployment parity,
candidate archival and rollback. Do not commit synthetic artifacts or manually
edit reviewed historical reference files.
