"""Flask CLI commands for repeatable MLB Statcast ingestion."""

from pathlib import Path

import click
from flask.cli import with_appcontext

from app.services.statcast_ingestion import IngestionError, ingest_statcast_file


@click.group("statcast")
def statcast_cli() -> None:
    """Validate and ingest MLB Statcast data."""


@statcast_cli.command("ingest")
@click.argument(
    "csv_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--batch-size",
    default=2_000,
    show_default=True,
    type=click.IntRange(min=1, max=20_000),
    help="Rows written per database batch.",
)
@with_appcontext
def ingest_command(csv_path: Path, batch_size: int) -> None:
    """Load one Baseball Savant CSV into the configured database."""
    try:
        report = ingest_statcast_file(csv_path, batch_size=batch_size)
    except IngestionError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo("Statcast ingestion completed")
    click.echo(f"Run ID: {report.ingestion_run_id}")
    click.echo(f"Source rows: {report.source_rows:,}")
    click.echo(f"Inserted pitches: {report.inserted_rows:,}")
    click.echo(f"Updated pitches: {report.updated_rows:,}")
    click.echo(f"Rejected rows: {report.rejected_rows:,}")
