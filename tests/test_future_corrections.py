"""Correction plan, aggregate and transaction safety tests."""

import os
from copy import deepcopy

import pytest

from scripts.apply_future_corrections import (
    apply_transaction,
    expected_patches,
    fingerprint,
    read_values,
    validate_totals,
)
from scripts.reconcile_future_sources import plan_all, synthetic_bundle
from scripts.rehearse_snapshot_release import ReleaseError, assert_identity, connect


def fixture():
    bundle = synthetic_bundle()
    packet = bundle["pitchers"][0]
    staged = {
        packet["pitcher_id"]: {
            f"{row['game_pk']}_{row['at_bat_number']}_{row['pitch_number']}": dict(row)
            for row in packet["detail"]
        }
    }
    report = {
        "season": 2027,
        "synthetic": True,
        "source_manifest": {"date_from": "2027-04-01", "date_to": "2027-04-02"},
    }
    return staged, plan_all(report, staged, bundle)


def test_expected_patches_and_aggregate_validation():
    staged, plan = fixture()
    patches = expected_patches(staged, plan)
    assert len(patches) == 6
    validate_totals(patches, plan)
    assert sum(row[3] or 0 for row in patches.values()) == 2


@pytest.mark.parametrize("failure", ["extra_field", "duplicate", "missing", "unknown_key"])
def test_reject_invalid_patch_scope(failure):
    staged, plan = fixture()
    broken = deepcopy(plan)
    if failure == "extra_field":
        broken["patches"][0]["pitch_type"] = "SI"
    elif failure == "duplicate":
        broken["patches"].append(broken["patches"][0])
    elif failure == "missing":
        broken["patches"].pop()
    else:
        broken["patches"][0]["pitch_id"] = "1_1_1"
    with pytest.raises(ReleaseError):
        expected_patches(staged, broken)


@pytest.mark.parametrize("field", ["rv", "numerator", "denominator"])
def test_reject_incorrect_post_correction_aggregates(field):
    staged, plan = fixture()
    patches = expected_patches(staged, plan)
    key = next(key for key, row in patches.items() if row[3] == 1)
    owner, rv, numerator, denom = patches[key]
    if field == "rv":
        rv += 0.1
    elif field == "numerator":
        numerator += 0.1
    else:
        denom = 0
    patches[key] = (owner, rv, numerator, denom)
    with pytest.raises(ReleaseError):
        validate_totals(patches, plan)


@pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") != "true", reason="Requires disposable CI PostgreSQL."
)
def test_postgres_transaction_rolls_back_then_applies(monkeypatch):
    from sqlalchemy.engine import make_url

    url = make_url(os.environ["DATABASE_URL"])
    assert url.host == "localhost" and url.database == "mlb_pitch_intelligence_test"
    staged, plan = fixture()
    patches = expected_patches(staged, plan)
    with connect(url) as conn:
        # GitHub forwards localhost to the Docker service's bridge address.
        # Prove the real guard rejects that address; adapt only this test.
        with conn.cursor() as cur:
            cur.execute("SELECT host(inet_server_addr()), current_database()")
            host, database = cur.fetchone()
        assert database == url.database
        if host not in {"127.0.0.1", "::1"}:
            with pytest.raises(ReleaseError, match="loopback check failed"):
                assert_identity(conn, url.database)

            def assert_ci_identity(connection, expected):
                assert connection is conn and expected == url.database
                with connection.cursor() as cur:
                    cur.execute("SELECT current_database(), pg_my_temp_schema()")
                    name, schema = cur.fetchone()
                assert name == expected and schema != 0

            monkeypatch.setattr(
                "scripts.apply_future_corrections.assert_identity", assert_ci_identity
            )
        # Every table is temporary and shadows its permanent counterpart.
        # Nothing persists beyond this connection, even if a test fails.
        with conn.cursor() as cur:
            cur.execute("CREATE TEMP TABLE players (mlb_id integer)")
            cur.execute("CREATE TEMP TABLE games (game_pk integer, season integer, game_type text)")
            cur.execute(
                """
                CREATE TEMP TABLE pitches (
                    pitch_id text PRIMARY KEY, game_pk integer, pitcher_id integer,
                    delta_run_expectancy double precision, savant_woba_numerator double precision,
                    savant_woba_denominator integer, untouched text
                )
                """
            )
            cur.execute(
                "CREATE TEMP TABLE fangraphs_stuff (mlb_id integer, season integer, category text)"
            )
            cur.execute(
                "CREATE TEMP TABLE published_pitching_metrics "
                "(mlb_id integer, season integer, batter_side text)"
            )
            cur.execute(
                "CREATE TEMP TABLE savant_active_spin "
                "(mlb_id integer, season integer, pitch_type text)"
            )
            cur.execute("CREATE TEMP TABLE alembic_version (version_num text)")
            cur.execute("INSERT INTO games VALUES (1, 2026, 'R')")
            cur.execute("INSERT INTO pitches VALUES ('1_1_1', 1, 1, 0.5, 1.2, 1, 'historical')")
            for game in {int(key.split("_")[0]) for key in patches}:
                cur.execute("INSERT INTO games VALUES (%s, 2027, 'R')", (game,))
            for key, (owner, _, _, _) in patches.items():
                cur.execute(
                    "INSERT INTO pitches VALUES (%s, %s, %s, 0, NULL, NULL, 'unchanged')",
                    (key, int(key.split("_")[0]), owner),
                )
        conn.commit()
        before = fingerprint(conn, 2027)
        unchanged = fingerprint(conn, 2027, ignore_corrections=True)
        conn.commit()
        wrong = deepcopy(plan)
        wrong["pitcher_results"][0]["rv_total_pitcher"] = 9
        with pytest.raises(ReleaseError, match="official aggregate mismatch"):
            with conn.transaction():
                apply_transaction(conn, url.database, 2027, patches, wrong, before, unchanged)
        assert fingerprint(conn, 2027) == before
        conn.commit()
        with conn.transaction():
            after = apply_transaction(conn, url.database, 2027, patches, plan, before, unchanged)
        assert fingerprint(conn, 2027) == after
        assert after != before
        assert fingerprint(conn, 2027, ignore_corrections=True) == unchanged
        with conn.cursor() as cur:
            assert read_values(cur, 2027) == patches
            assert read_values(cur, 2026) == {"1_1_1": (1, 0.5, 1.2, 1)}
