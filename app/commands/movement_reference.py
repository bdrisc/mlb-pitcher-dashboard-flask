"""Build a vetted full-MLB arm-angle movement baseline from the native database."""

from pathlib import Path

import click
from flask.cli import with_appcontext

from app.services.movement_reference import export_full_league_reference


@click.group("movement-reference")
def movement_reference_cli():
    """Manage complete-league movement references for HB/IVB vs. AVG."""


@movement_reference_cli.command("export")
@click.option("--season", type=click.IntRange(2020, 2100), default=2026, show_default=True)
@click.option("--output", type=click.Path(path_type=Path), default=None)
@with_appcontext
def export_movement_reference(season: int, output: Path | None):
    """Export one compact full-league reference. Public 50-pitcher sets fail closed."""
    try:
        result = export_full_league_reference(season, output)
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(result)
