# CLAUDE.md

## Environment

- Always use the project venv: `venv/bin/python` and `venv/bin/pip`
- Never use system python

## Key Commands

```bash
venv/bin/python -m pytest tests/ -x -q          # run tests
```

## Container Commands

Uses podman-compose (installed in venv). App runs on port 5050 locally.

```bash
venv/bin/podman-compose up --build -d                          # start local dev (app + postgres)
venv/bin/podman-compose down -v                                # stop and remove volumes
venv/bin/podman-compose exec web flask db upgrade              # run migrations
venv/bin/podman-compose exec web flask shell                   # interactive shell
venv/bin/podman-compose exec web python -m pytest tests/ -x -q # run tests in container
```

## Project Layout

- `app/` — Flask application (auth, teams, sessions, tracks, API, dashboard blueprints)
- `app/sessions/ingest.py` — CSV upload → analysis → DB insert pipeline
- `app/cli.py` — CLI commands (create-user, seed-tracks, import-session, reingest-session)
- `app/api/routes.py` — JSON API endpoints for dashboard data
- `app/templates/` — Jinja2 HTML templates
- `app/static/` — CSS and JS (dashboard.js, mapkit-helpers.js, raceline.js)
- `scripts/analysis/` — shared analysis modules (from kart repo)
- `scripts/load_data.py` — telemetry and metadata loading functions
- `migrations/` — Flask-Migrate (Alembic) database migrations
- `data/tracks.yaml` — track corner definitions and coordinates
- `tests/app/` — app test suite

## Data Conventions

- RaceChrono v3 CSV: header row, units row, source row; duplicate columns deduplicated by sensor suffix
- Speed in telemetry is m/s (multiply by 3.6 for km/h)
- Ingest pipeline calls analysis modules from `scripts/analysis/` — same code as the static generator
- All chart data is precomputed on ingest and stored as JSONB in the `chart_data` table

## Code Conventions

- Flask with Blueprints (auth, teams, sessions, tracks, api, dashboard)
- SQLAlchemy ORM with Flask-Migrate for schema management
- Plotly for all charts (rendered client-side via Plotly.react())
- Apple MapKit JS for all maps
- Bootstrap 5 for layout

## Workflow

After making changes:
1. Run tests: `venv/bin/python -m pytest tests/ -x -q`
