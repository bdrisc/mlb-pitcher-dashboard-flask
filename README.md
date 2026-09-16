# MLB Pitch Intelligence — Flask Foundation

This project restructures the original single-file pitch API into a maintainable Flask
application. It uses an application factory, browser and API blueprints, environment-backed
configuration, isolated data and plotting services, Jinja templates, and Flask test-client
coverage.

The second development milestone adds PostgreSQL persistence, Flask-SQLAlchemy models,
Flask-Migrate migrations, a validated Statcast ingestion command, transactional upserts, and
an audit record for every attempted load. The third milestone adds one shared, typed filter
contract with normalization and structured validation errors. The fourth milestone adds a
database-backed pitcher directory and profile API with SQL-level aggregation. The fifth
milestone adds a responsive, server-rendered Savant Card whose browser controls call that API.
The sixth milestone adds six interactive Plotly charts backed by a dedicated, filtered chart-
data endpoint. The seventh milestone adds production configuration, expanded automated tests,
a non-root Docker image, a PostgreSQL Docker Compose stack, GitHub Actions CI, Gunicorn, and a
Render deployment blueprint.
The eighth milestone adds resumable, cached MLB Statcast season acquisition and a reproducible
top-50-pitcher production sample that preserves every pitch for each selected pitcher.

## Project structure

```text
mlb-pitch-intelligence-flask/
├── app/
│   ├── blueprints/
│   │   ├── api.py
│   │   └── main.py
│   ├── commands/statcast.py
│   ├── services/
│   │   ├── database_queries.py
│   │   ├── filters.py
│   │   ├── pitch_data.py
│   │   ├── pitcher_charts.py
│   │   ├── pitcher_profiles.py
│   │   ├── plots.py
│   │   ├── statcast_acquisition.py
│   │   └── statcast_ingestion.py
│   ├── static/
│   │   ├── savant-card-charts.js
│   │   ├── savant-card.js
│   │   └── styles.css
│   ├── templates/
│   │   ├── base.html
│   │   ├── index.html
│   │   └── savant_card.html
│   ├── __init__.py
│   ├── config.py
│   ├── extensions.py
│   └── models.py
├── data/
│   ├── sample_statcast.csv
│   └── production_statcast_2026.csv.gz
├── .github/workflows/ci.yml
├── migrations/
├── scripts/docker-entrypoint.sh
├── tests/
├── .dockerignore
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── gunicorn.conf.py
├── render.yaml
├── requirements.txt
├── requirements-data.txt
├── requirements-dev.txt
└── wsgi.py
```

## Windows setup

From PowerShell in the project folder:

```powershell
py -3.10 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Create a PostgreSQL database named `mlb_pitch_intelligence`. You can use pgAdmin or:

```powershell
createdb -U postgres mlb_pitch_intelligence
```

Open `.env` and replace `replace-with-your-password` in `DATABASE_URL` with your PostgreSQL
password. Then build the four database tables from the included migration:

```powershell
flask --app wsgi db upgrade
```

Start the browser application:

```powershell
flask --app wsgi run --debug --port 8080
```

Open `http://127.0.0.1:8080`. After ingesting data, the Savant Card is available at
`http://127.0.0.1:8080/savant-card`.

The included CSV is an explicitly fictional Statcast-shaped sample that makes the project
runnable before a real MLB export is added. Set `PITCH_DATA_PATH` in `.env` to use another CSV.

## Ingest an MLB Statcast export

Place an authorized Baseball Savant CSV in `data/raw/`. That directory is excluded from Git.
From the repository root, run:

```powershell
flask --app wsgi statcast ingest data\raw\statcast.csv
```

The command:

- validates the required Statcast columns and numeric fields;
- generates `game_pk_at_bat_number_pitch_number` as the stable pitch ID;
- standardizes pitch names;
- derives strike, swing, contact, whiff, CSW, zone, chase, and hard-hit flags;
- converts Statcast movement from feet to inches;
- upserts players, games, and pitches without duplicating existing pitch IDs;
- rolls back every baseball-data write if any part of the load fails; and
- writes a succeeded or failed record to `ingestion_runs` with the source hash and row counts.

Rerunning a corrected or expanded export is safe. Existing pitches are updated and new pitches
are inserted.

The bundled fictional sample now uses the complete ingestion schema. It can safely populate a
new development database before you obtain a real Baseball Savant export:

```powershell
flask --app wsgi statcast ingest data\sample_statcast.csv
```

The sample creates fictional pitcher MLB ID `999001` for local API testing.

## Download the complete 2026 season locally

The local Flask app uses the PostgreSQL connection in your local `.env`; it does not use the
Render database. Install the optional data-acquisition dependency in the activated virtual
environment:

```powershell
python -m pip install -r requirements-data.txt
```

Download every completed 2026 regular-season date through September 14 and ingest each cached
chunk into local PostgreSQL:

```powershell
flask --app wsgi statcast fetch-season 2026 --through 2026-09-14
```

The command requests five calendar days at a time, excludes spring-training and incomplete
records, caches usable rows under `data/cache/statcast/2026/`, and commits each chunk through the
existing idempotent ingestion service. The cache directory is excluded from Git. If a request
fails, rerun the same command: completed chunks are reused and the database upserts prevent
duplicates.

After the real-season load completes successfully, remove only the bundled fictional records:

```powershell
flask --app wsgi statcast remove-fictional-sample
```

This command targets the sample's reserved game and player IDs. It does not delete real MLB
pitches or clear the ingestion audit history.

To extend the local database after additional games are played, use a later completed date or
omit `--through` to use yesterday:

```powershell
flask --app wsgi statcast fetch-season 2026
```

Useful alternatives:

```powershell
# Download and cache without changing PostgreSQL
flask --app wsgi statcast fetch-season 2026 --download-only

# Replace existing cache files with fresh Baseball Savant responses
flask --app wsgi statcast fetch-season 2026 --force-download
```

## Build the public top-50-pitcher dataset

After the local season acquisition finishes, create a compressed production export containing
the 50 pitchers with the most pitches and every cached pitch thrown by those pitchers:

```powershell
flask --app wsgi statcast build-production-sample 2026 --pitchers 50
```

This produces:

- `data/production_statcast_2026.csv.gz`, the deployable ingestion source; and
- `data/production_statcast_2026.manifest.json`, the selection rule, row count, MLB IDs, names,
  and pitch totals needed to document the public sample.

The production export is intentionally selected by complete pitcher history rather than random
pitch rows. That keeps arsenal usage, trends, splits, and rate denominators internally valid.
The checked-in production file contains 133,933 pitches from the 50 busiest pitchers through
September 14, 2026. The full league cache remains local and is never committed.

## API routes

```text
GET /api/v1/health
GET /api/v1/pitchers
GET /api/v1/pitchers/<pitcher_id>/profile
GET /api/v1/pitchers/<pitcher_id>/charts
GET /api/v1/pitches
GET /api/v1/plots/movement?pitcher=Sample%20Pitcher
```

## Savant Card

`GET /savant-card` serves a reusable Jinja page layout, while a separate JavaScript module
loads pitcher data from the versioned JSON API. The page includes:

- a database-backed pitcher selector;
- season, team, pitch type, batter side, count, venue, and date-range filters;
- URL-synchronized filter state for reproducible profiles;
- loading, empty-database, empty-sample, and structured API-error states;
- 12 headline metrics with denominator-aware formatting;
- a pitch-level arsenal table and right/left platoon cards;
- six interactive Plotly charts with hover details, legend isolation, zoom, pan, and PNG export;
- responsive layouts for desktop, tablet, and mobile screens.

The page does not calculate baseball metrics in the browser. It sends the active filter set to
the pitcher profile API and renders the returned SQL aggregates, keeping the API as the single
source of truth. It sends the same normalized filters to the chart-data API, so every metric,
table, and chart represents the same sample.

The six visualizations are:

1. movement profile by pitch type;
2. average velocity by game date;
3. release-point consistency;
4. pitch location with the sample's average strike zone;
5. pitch usage within each count; and
6. pitch-type Whiff%, CSW%, Zone%, and Chase%.

Dense scatter plots are sampled deterministically at 6,000 points for browser performance, while
the velocity, count-usage, and performance calculations continue to use the complete filtered
sample. Plotly.js is loaded from its official CDN with an explicit version rather than the frozen
legacy `plotly-latest` bundle.

`GET /api/v1/pitchers` is a database-backed directory that returns stable MLB IDs, names,
throwing hands, teams, pitch counts, game counts, and date coverage. It accepts the shared
filters, including a partial `pitcher` name search.

`GET /api/v1/pitchers/<pitcher_id>/profile` returns:

- pitcher identity and teams represented in the filtered sample;
- sample sizes and first/last game dates;
- overall velocity, shape, plate-discipline, contact-quality, strikeout, and walk metrics;
- pitch-level arsenal usage and performance metrics; and
- right- and left-handed batter splits.

`GET /api/v1/pitchers/<pitcher_id>/charts` returns six chart-ready datasets. It selects only the
database columns needed for the visualizations, applies the shared filter contract before data
leaves PostgreSQL, and retains `null` rates when a pitch type has no valid opportunity denominator.

All aggregations execute in SQL. The API reports rates as percentages, returns `null` when a
rate has no valid denominator, and includes metric definitions in the response. The
`xwoba_on_contact` field is explicitly contact-only rather than being presented as full pitcher
xwOBA.

After ingesting the fictional sample, open:

```text
http://127.0.0.1:8080/api/v1/pitchers/999001/profile?season=2026
http://127.0.0.1:8080/api/v1/pitchers/999001/charts?season=2026
```

The pitch summary and movement chart use the same validated filters:

| Query parameter | Accepted values |
| --- | --- |
| `pitcher` | Case-insensitive partial name; required for the movement chart |
| `team` | Two- or three-letter MLB team code |
| `pitch_type` | Statcast code or full name; repeat it or use commas for multiple types |
| `batter_side` | `R`, `L`, `right`, or `left`; supports multiple values |
| `season` | Integer from 2008 through the current year |
| `date_from`, `date_to` | Inclusive ISO dates in `YYYY-MM-DD` format |
| `balls` | Integer from 0 through 3 |
| `strikes` | Integer from 0 through 2 |
| `home_away` | `home`, `away`, `H`, or `A` |

Example:

```text
/api/v1/pitches?pitcher=Sample%20Pitcher&pitch_type=FF,SL&batter_side=R&season=2026
```

Scalar filters may appear only once. Unknown parameters, unsupported categorical values,
out-of-range counts, malformed dates, and reversed date ranges return HTTP `400` with details
for every invalid field:

```json
{
  "error": "validation_error",
  "message": "Invalid query parameters.",
  "details": {
    "balls": ["must be between 0 and 3"]
  }
}
```

## Tests and code quality

```powershell
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

The suite covers route behavior, filter validation, Statcast ingestion, pitcher-profile and
chart aggregations, production configuration, security headers, and the deployment manifests.
The GitHub Actions workflow runs these checks against PostgreSQL 17 on Python 3.10 and 3.12,
smoke-tests the migrated API, and builds the Docker image before a pull request can be merged.

## Run the complete stack with Docker

Install and start Docker Desktop, then run this from the repository root:

```powershell
docker compose up --build
```

Compose starts PostgreSQL 17, waits for it to become healthy, applies the database migrations,
loads the fictional sample data idempotently, and serves the Flask app through Gunicorn at
`http://127.0.0.1:8080`. The API health check is available at
`http://127.0.0.1:8080/api/v1/health`.

Press `Ctrl+C` to stop the foreground process, then remove the stopped containers:

```powershell
docker compose down
```

The named PostgreSQL volume preserves the database between runs. Only use
`docker compose down -v` when you intentionally want to erase that local Docker database.

## Deploy on Render

`render.yaml` defines a Docker web service and managed PostgreSQL 17 database. To deploy it:

1. Push this repository to GitHub.
2. In Render, create a new Blueprint and select the repository.
3. Review the resources described by `render.yaml`, then apply the Blueprint.
4. Confirm `/api/v1/health` reports `"status": "ok"` after the first deployment.

Render generates the production secret and database connection string. `PITCH_DATA_PATH` keeps
the small fallback source used by legacy in-memory routes separate from `STATCAST_SEED_PATH`, the
large database-ingestion source. The container entrypoint applies database migrations and streams
`data/production_statcast_2026.csv.gz` into an empty database before Gunicorn starts. When
upgrading the original demonstration deployment, the seed command keeps the six reserved
fictional pitches available until all 133,933 real pitches load successfully, then removes them.
Later deployments and container restarts detect the existing MLB data and skip the import. For a
public portfolio deployment that must retain data indefinitely, review the current retention
limits before choosing a free database plan.

For other Linux container platforms, the production process is:

```text
gunicorn --config gunicorn.conf.py wsgi:app
```

Set `APP_ENV=production`, a strong `SECRET_KEY`, `DATABASE_URL`, and `BEHIND_PROXY=1`. The app
refuses to start in production when the development-only secret is still configured.

## Architectural decisions

- `create_app()` prevents configuration and data state from being locked to one module import.
- Blueprints separate server-rendered pages from the versioned JSON API.
- `PitchDataStore` owns source detection, normalization, filtering, and summaries.
- Flask-SQLAlchemy owns the relational model layer and Flask-Migrate owns schema revisions.
- The `statcast` Flask CLI group keeps repeatable data work outside request handlers.
- `PitchFilters` gives browser, chart, and future database endpoints one canonical query contract.
- Filter responses expose normalized MLB codes so URLs are reproducible across clients.
- Pitcher profiles aggregate inside PostgreSQL instead of loading an entire season into Python.
- The pitcher directory exposes stable MLB IDs for the Savant Card player selector.
- Chart queries reuse the exact profile filters and select only visualization fields from the
  database.
- Plotly rendering lives in its own browser module instead of mixing chart code into Flask views.
- Rate denominators are explicit, and zero-opportunity rates serialize as `null` rather than zero.
- Plot generation is isolated from request handling and uses a non-interactive backend.
- Missing or invalid data produce readable `503` responses while the app remains diagnosable.
- The health endpoint verifies both the SQL connection and pitch-data source for orchestrator
  readiness checks.
- Gunicorn serves production traffic, while `ProxyFix` is enabled explicitly behind a trusted
  platform proxy.
- The container runs as an unprivileged user and starts only after optional migration and sample
  ingestion hooks finish successfully.
- CI proves migrations, ingestion, API responses, linting, formatting, and image construction on
  every proposed change.
- MLB Statcast movement is converted from feet to inches during normalization.
- The original TrackMan schema remains temporarily supported so the restructure does not discard
  the prototype's earlier functionality.
