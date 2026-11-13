"""Import and refresh official, published FanGraphs and Baseball Savant rates."""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import click
import pandas as pd
from flask.cli import with_appcontext

from app.services.published_pitching import (
    import_fangraphs_published,
    import_savant_xera,
)
from app.services.published_pitching_fetch import validate_handedness_split


@click.group("published")
def published_cli():
    """Manage published season pitching metrics without re-ingesting Statcast."""


@published_cli.command("import-fangraphs")
@click.argument("csv_path", type=click.Path(exists=True, path_type=Path))
@click.option("--season", type=click.IntRange(2015, 2100), required=True)
@click.option("--split", type=click.Choice(["ALL", "L", "R"]), default="ALL")
@with_appcontext
def import_fangraphs(csv_path, season, split):
    """Import a FanGraphs advanced pitching leaderboard (MLB IDs required)."""
    try:
        result = import_fangraphs_published(pd.read_csv(csv_path), season, split)
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(result)


@published_cli.command("import-savant")
@click.argument("csv_path", type=click.Path(exists=True, path_type=Path))
@click.option("--season", type=click.IntRange(2015, 2100), required=True)
@with_appcontext
def import_savant(csv_path, season):
    """Import official Savant expected-statistics pitcher xERA from CSV."""
    try:
        result = import_savant_xera(pd.read_csv(csv_path), season)
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(result)


def _acquire(provider, season, side, destination, timeout):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.services.published_pitching_fetch",
            provider,
            str(season),
            side,
            str(destination),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise ValueError(f"{provider} {side} fetch failed: {(detail or ['unknown error'])[-1]}")
    return pd.read_csv(destination)


@published_cli.command("sync")
@click.option("--season", type=click.IntRange(2015, 2100), default=lambda: date.today().year)
@click.option("--timeout", type=click.IntRange(1, 600), default=90, show_default=True)
@with_appcontext
def sync_published(season, timeout):
    """Download publisher values; keep all saved stats on upstream failure."""
    errors = []
    with TemporaryDirectory(prefix="published-pitching-") as directory:
        home = Path(directory)
        full = None
        try:
            full = _acquire("fangraphs", season, "ALL", home / "fg_all.csv", timeout)
            click.echo(import_fangraphs_published(full, season, "ALL"))
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"FanGraphs full season: {exc}")
        if full is not None:
            for side in ("L", "R"):
                try:
                    frame = _acquire("fangraphs", season, side, home / f"fg_{side}.csv", timeout)
                    validate_handedness_split(frame, full)
                    click.echo(import_fangraphs_published(frame, season, side))
                except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
                    errors.append(f"FanGraphs vs {side}HH: {exc}")
        try:
            savant = _acquire("savant", season, "ALL", home / "savant.csv", timeout)
            click.echo(import_savant_xera(savant, season))
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"Baseball Savant: {exc}")
    for failure in errors:
        click.echo(f"Source unavailable; previous values retained. {failure}", err=True)
    if errors:
        raise click.ClickException(
            f"{len(errors)} publisher source(s) were unavailable; successful imports were saved."
        )
