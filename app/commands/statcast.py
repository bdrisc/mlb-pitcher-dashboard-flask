"""Flask CLI commands for repeatable MLB Statcast acquisition and ingestion."""

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import click
from flask.cli import with_appcontext
from sqlalchemy import func, select

from app.extensions import db
from app.models import Game, Pitch
from app.services.statcast_acquisition import (
    StatcastAcquisitionError,
    acquire_statcast_chunk,
    build_top_pitcher_sample,
    filter_statcast_pitchers,
    iter_date_chunks,
    recent_statcast_chunk,
    season_date_range,
)
from app.services.statcast_ingestion import (
    IngestionError,
    ingest_statcast_file,
    remove_fictional_sample,
    seed_statcast_if_needed,
)


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


@statcast_cli.command("seed-if-needed")
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
def seed_if_needed_command(csv_path: Path, batch_size: int) -> None:
    """Seed an empty deployment database and skip subsequent restarts."""
    try:
        report = seed_statcast_if_needed(csv_path, batch_size=batch_size)
    except IngestionError as exc:
        raise click.ClickException(str(exc)) from exc

    if report.removed_sample is not None:
        click.echo(f"Removed fictional pitches: {report.removed_sample.pitches:,}")

    if not report.seeded:
        click.echo("Statcast seed skipped; database already contains real pitch data.")
        click.echo(f"Existing pitches: {report.existing_pitches:,}")
        return

    assert report.ingestion is not None
    click.echo("Statcast seed completed")
    click.echo(f"Run ID: {report.ingestion.ingestion_run_id}")
    click.echo(f"Inserted pitches: {report.ingestion.inserted_rows:,}")
    click.echo(f"Updated pitches: {report.ingestion.updated_rows:,}")


@statcast_cli.command("remove-fictional-sample")
@with_appcontext
def remove_fictional_sample_command() -> None:
    """Remove only the six bundled demonstration pitches and their records."""
    try:
        report = remove_fictional_sample()
    except IngestionError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo("Fictional sample removal completed")
    click.echo(f"Removed pitches: {report.pitches:,}")
    click.echo(f"Removed games: {report.games:,}")
    click.echo(f"Removed players: {report.players:,}")


@statcast_cli.command("sync-recent")
@click.option(
    "--lookback-days",
    default=4,
    show_default=True,
    type=click.IntRange(min=1, max=14),
    help="Recent calendar days to redownload through yesterday.",
)
@click.option("--retries", default=3, show_default=True, type=click.IntRange(min=1, max=10))
@click.option(
    "--batch-size",
    default=2_000,
    show_default=True,
    type=click.IntRange(min=1, max=20_000),
)
@with_appcontext
def sync_recent_command(lookback_days: int, retries: int, batch_size: int) -> None:
    """Update the deployed cohort with a small recent Statcast window."""
    pitcher_ids = set(db.session.scalars(select(Pitch.pitcher_id).distinct()))
    if not pitcher_ids:
        click.echo("Recent Statcast sync skipped; no deployed pitcher cohort exists.")
        return

    latest_game_date = db.session.scalar(select(func.max(Game.game_date)))
    window = recent_statcast_chunk(
        lookback_days=lookback_days,
        latest_game_date=latest_game_date,
    )
    if window is None:
        click.echo("Recent Statcast sync skipped; the season window has not started.")
        return

    chunks = iter_date_chunks(window.start_date, window.end_date, 7)
    selected_rows = 0
    inserted_rows = 0
    updated_rows = 0

    try:
        with TemporaryDirectory(prefix="statcast-sync-") as temporary_directory:
            working_directory = Path(temporary_directory)
            for chunk in chunks:
                downloaded = acquire_statcast_chunk(
                    chunk,
                    cache_dir=working_directory,
                    retries=retries,
                )
                selected_path = working_directory / (
                    f"selected_{chunk.start_date}_{chunk.end_date}.csv.gz"
                )
                chunk_rows = filter_statcast_pitchers(
                    downloaded.path,
                    selected_path,
                    pitcher_ids,
                )
                if chunk_rows == 0:
                    continue

                report = ingest_statcast_file(selected_path, batch_size=batch_size)
                selected_rows += chunk_rows
                inserted_rows += report.inserted_rows
                updated_rows += report.updated_rows
    except (StatcastAcquisitionError, IngestionError) as exc:
        raise click.ClickException(str(exc)) from exc

    if selected_rows == 0:
        click.echo("Recent Statcast sync completed; no pitches matched the deployed cohort.")
        return

    click.echo(f"Recent Statcast sync completed for {window.start_date} through {window.end_date}.")
    click.echo(f"Cohort pitches downloaded: {selected_rows:,}")
    click.echo(f"Inserted pitches: {inserted_rows:,}")
    click.echo(f"Updated pitches: {updated_rows:,}")


@statcast_cli.command("fetch-season")
@click.argument("season", type=click.IntRange(min=2015, max=2100))
@click.option(
    "--through",
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Inclusive final date. Defaults to yesterday for the current season.",
)
@click.option(
    "--chunk-days",
    default=5,
    show_default=True,
    type=click.IntRange(min=1, max=7),
    help="Calendar days requested per resumable download.",
)
@click.option(
    "--cache-dir",
    default="data/cache/statcast",
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option("--retries", default=3, show_default=True, type=click.IntRange(min=1, max=10))
@click.option("--force-download", is_flag=True, help="Replace existing cached chunks.")
@click.option("--download-only", is_flag=True, help="Cache files without loading PostgreSQL.")
@click.option(
    "--batch-size",
    default=2_000,
    show_default=True,
    type=click.IntRange(min=1, max=20_000),
)
@with_appcontext
def fetch_season_command(
    season: int,
    through: datetime | None,
    chunk_days: int,
    cache_dir: Path,
    retries: int,
    force_download: bool,
    download_only: bool,
    batch_size: int,
) -> None:
    """Download and optionally ingest one complete MLB regular season."""
    try:
        start_date, end_date = season_date_range(
            season,
            through=through.date() if through else None,
        )
        season_cache = cache_dir / str(season)
        chunks = iter_date_chunks(start_date, end_date, chunk_days)
        click.echo(
            f"Acquiring {season} regular-season Statcast data from "
            f"{start_date} through {end_date} in {len(chunks)} chunk(s)."
        )

        downloaded_pitches = 0
        inserted_pitches = 0
        updated_pitches = 0
        for number, chunk in enumerate(chunks, start=1):
            cached = acquire_statcast_chunk(
                chunk,
                cache_dir=season_cache,
                retries=retries,
                force_download=force_download,
            )
            downloaded_pitches += cached.pitch_rows
            source_label = "cache" if cached.from_cache else "download"
            click.echo(
                f"[{number}/{len(chunks)}] {chunk.start_date} to {chunk.end_date}: "
                f"{cached.pitch_rows:,} usable pitches ({source_label}, "
                f"{cached.dropped_rows:,} excluded)."
            )

            if not download_only and cached.pitch_rows:
                ingestion = ingest_statcast_file(cached.path, batch_size=batch_size)
                inserted_pitches += ingestion.inserted_rows
                updated_pitches += ingestion.updated_rows
                click.echo(
                    f"    PostgreSQL: {ingestion.inserted_rows:,} inserted, "
                    f"{ingestion.updated_rows:,} updated."
                )

    except (StatcastAcquisitionError, IngestionError) as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo("Season acquisition completed")
    click.echo(f"Usable cached pitches: {downloaded_pitches:,}")
    if not download_only:
        click.echo(f"Inserted pitches: {inserted_pitches:,}")
        click.echo(f"Updated pitches: {updated_pitches:,}")


@statcast_cli.command("build-production-sample")
@click.argument("season", type=click.IntRange(min=2015, max=2100))
@click.option(
    "--pitchers",
    "pitcher_limit",
    default=50,
    show_default=True,
    type=click.IntRange(min=1, max=500),
    help="Number of complete pitcher histories to retain.",
)
@click.option(
    "--cache-dir",
    default="data/cache/statcast",
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Compressed CSV destination.",
)
def build_production_sample_command(
    season: int,
    pitcher_limit: int,
    cache_dir: Path,
    output: Path | None,
) -> None:
    """Build a deployable file with complete profiles for the busiest pitchers."""
    destination = output or Path(f"data/production_statcast_{season}.csv.gz")
    try:
        report = build_top_pitcher_sample(
            season=season,
            cache_dir=cache_dir / str(season),
            output_path=destination,
            pitcher_limit=pitcher_limit,
        )
    except StatcastAcquisitionError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo("Production sample completed")
    click.echo(f"Pitchers: {report.pitcher_count:,}")
    click.echo(f"Pitches: {report.pitch_count:,}")
    click.echo(f"CSV: {report.output_path}")
    click.echo(f"Manifest: {report.manifest_path}")
