"""Synthetic metric import identity, scope and transactional rollback tests."""

import os
from copy import deepcopy
from types import SimpleNamespace

import pytest

from scripts.acquire_future_leaderboards import normalize, synthetic_bodies
from scripts.apply_future_corrections import fingerprint
from scripts.apply_future_leaderboards import (
    apply_transaction,
    approved_inputs,
    mappings,
    planned_rows,
)
from scripts.rehearse_snapshot_release import ReleaseError, assert_identity, connect

PID = 2000000010


def fixture():
    staged = {PID: {"1_1_1": {"pitch_type": "FF"}}}
    report = {
        "season": 2027,
        "synthetic": True,
        **normalize(synthetic_bodies(2027), 2027, staged),
    }
    return staged, report


def test_real_import_is_blocked():
    with pytest.raises(ReleaseError, match="Real imports"):
        approved_inputs(SimpleNamespace(synthetic=False))


@pytest.mark.parametrize("pairs", [[(1, "7"), (2, "7")], [(1, "7"), (1, "8")]])
def test_conflicting_identity(pairs):
    with pytest.raises(ReleaseError, match="Conflicting"):
        mappings(pairs)


def test_consistent_identity():
    assert mappings([(PID, "9000001"), (PID, "9000001"), (1, None)]) == {PID: "9000001"}


@pytest.mark.parametrize("failure", ["wrong_year", "wrong_player", "duplicate", "split"])
def test_bad_plan_scope(failure):
    staged, report = fixture()
    row = report["published_pitching_metrics"][0]
    if failure == "wrong_year":
        row["season"] = 2026
    elif failure == "wrong_player":
        row["mlb_id"] = 123
    elif failure == "duplicate":
        report["published_pitching_metrics"].append(deepcopy(row))
    else:
        row["batter_side"] = "L"
    with pytest.raises(ReleaseError):
        planned_rows(report, set(staged))


@pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") != "true", reason="Requires disposable CI PostgreSQL."
)
def test_postgres_metric_import_rollback_and_success(monkeypatch):
    from psycopg.errors import CheckViolation
    from sqlalchemy.engine import make_url

    url = make_url(os.environ["DATABASE_URL"])
    assert url.host == "localhost" and url.database == "mlb_pitch_intelligence_test"
    staged, report = fixture()
    with connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT host(inet_server_addr()), current_database()")
            host, database = cur.fetchone()
        assert database == url.database
        if host not in {"127.0.0.1", "::1"}:
            with pytest.raises(ReleaseError, match="loopback check failed"):
                assert_identity(conn, url.database)

            def ci_identity(connection, expected):
                assert connection is conn and expected == url.database
                with connection.cursor() as cur:
                    cur.execute("SELECT current_database(), pg_my_temp_schema()")
                    name, schema = cur.fetchone()
                assert name == expected and schema != 0

            monkeypatch.setattr("scripts.apply_future_leaderboards.assert_identity", ci_identity)
        with conn.cursor() as cur:
            cur.execute("CREATE TEMP TABLE players (mlb_id integer)")
            cur.execute("CREATE TEMP TABLE games (game_pk integer, season integer, game_type text)")
            cur.execute("CREATE TEMP TABLE pitches (pitch_id text, game_pk int, pitcher_id int)")
            cur.execute(
                """
                CREATE TEMP TABLE fangraphs_stuff (
                    mlb_id int, season int, category text, fangraphs_id text,
                    stuff_plus float8, location_plus float8, pitching_plus float8,
                    updated_at timestamptz
                )
                """
            )
            cur.execute(
                """
                CREATE TEMP TABLE published_pitching_metrics (
                    mlb_id int, season int, batter_side text, fangraphs_id text,
                    fip float8, xfip float8, siera float8, xera float8,
                    fangraphs_updated_at timestamptz, savant_updated_at timestamptz
                )
                """
            )
            cur.execute(
                """
                CREATE TEMP TABLE savant_active_spin (
                    mlb_id int, season int, pitch_type text, active_spin_pct float8,
                    updated_at timestamptz,
                    CONSTRAINT forced_failure CHECK (active_spin_pct < 90)
                )
                """
            )
            cur.execute("CREATE TEMP TABLE alembic_version (version_num text)")
            cur.execute("INSERT INTO players VALUES (%s)", (PID,))
            cur.execute("INSERT INTO games VALUES (1, 2027, 'R')")
            cur.execute("INSERT INTO pitches VALUES ('1_1_1', 1, %s)", (PID,))
            cur.execute(
                "INSERT INTO fangraphs_stuff VALUES (1, 2026, 'ALL', '1', 100, 100, 100, now())"
            )
            cur.execute("INSERT INTO savant_active_spin VALUES (1, 2026, 'FF', 80, now())")
        conn.commit()
        before = fingerprint(conn, 2027)
        conn.commit()
        # The spin insert fails after grades and rates have been inserted.
        with pytest.raises(CheckViolation):
            with conn.transaction():
                apply_transaction(conn, url.database, staged, report, before)
        assert fingerprint(conn, 2027) == before
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE savant_active_spin DROP CONSTRAINT forced_failure")
        conn.commit()
        with conn.transaction():
            after, identities = apply_transaction(conn, url.database, staged, report, before)
        assert fingerprint(conn, 2027) == after
        assert identities == {str(PID): "9000001"}
        assert after["fangraphs_stuff"]["rows"] == before["fangraphs_stuff"]["rows"] + 2
        assert after["published_pitching_metrics"]["rows"] == 1
        assert after["savant_active_spin"]["rows"] == before["savant_active_spin"]["rows"] + 1
        with conn.cursor() as cur:
            cur.execute("SELECT active_spin_pct FROM savant_active_spin WHERE season = 2026")
            assert cur.fetchone() == (80.0,)
