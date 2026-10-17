"""FanGraphs acquisition and manual CSV fallback commands."""

import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import click
import pandas as pd
from flask.cli import with_appcontext
from sqlalchemy import func, select

from app.config import PROJECT_ROOT
from app.extensions import db
from app.models import FanGraphsStuff
from app.services.fangraphs_stuff import import_grades


@click.group("fangraphs")
def fangraphs_cli():
    """Refresh or import season-level FanGraphs Stuff+."""


@fangraphs_cli.command("sync")
@click.option("--season", type=click.IntRange(2020, 2100), default=lambda: date.today().year)
@click.option("--timeout", type=click.IntRange(1, 600), default=120)
@with_appcontext
def sync(season, timeout):
    """Refresh grades; preserve the last successful import on upstream failure."""
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "stuff.csv"
        try:
            result = subprocess.run(
                [sys.executable, "-m", "app.services.fangraphs_fetch", str(season), str(output)],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if result.returncode:
                raise ValueError(
                    "FanGraphs acquisition failed. Use fangraphs import-csv with an "
                    "exported leaderboard and ID crosswalk."
                )
            summary = import_grades(pd.read_csv(output), season)
        except (subprocess.TimeoutExpired, ValueError, OSError) as error:
            raise click.ClickException(f"{error} Existing grades were preserved.") from error
    click.echo(summary)


@fangraphs_cli.command("import-csv")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--season", required=True, type=click.IntRange(2020, 2100))
@click.option("--crosswalk", type=click.Path(exists=True, path_type=Path))
@with_appcontext
def import_csv(path, season, crosswalk):
    """Import FanGraphs CSV; supply MLB IDs or a Chadwick-format ID crosswalk."""
    try:
        mapping = pd.read_csv(crosswalk) if crosswalk else None
        click.echo(import_grades(pd.read_csv(path), season, mapping))
    except (ValueError, KeyError) as error:
        raise click.ClickException(str(error)) from error


@fangraphs_cli.command("seed-if-needed")
@with_appcontext
def seed_if_needed():
    """Load bundled snapshots when a season lacks the complete model metrics."""
    for path in sorted((PROJECT_ROOT / "data").glob("fangraphs_stuff_*.csv")):
        season = int(path.stem.rsplit("_", 1)[1])
        count = db.session.scalar(
            select(func.count())
            .select_from(FanGraphsStuff)
            .where(
                FanGraphsStuff.season == season,
                FanGraphsStuff.location_plus.is_not(None),
                FanGraphsStuff.pitching_plus.is_not(None),
            )
        )
        if not count:
            click.echo(import_grades(pd.read_csv(path), season))
