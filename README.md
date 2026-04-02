# Boxbox

A kart racing telemetry platform that turns [RaceChrono](https://racechrono.com/) CSV exports into interactive dashboards with lap analysis, corner breakdowns, racing line comparisons, and cross-session performance tracking.

Built with Flask, PostgreSQL, Plotly, and Apple MapKit JS.

## Features

**Session Dashboard**
- Lap time bar charts with outlier detection
- Delta-to-best analysis showing where time is gained or lost
- Sector time breakdowns
- Coaching summary with actionable feedback

**Lap Deep Dive**
- Per-lap track maps showing speed zones, braking zones, and sector splits
- Cumulative delta traces against the median lap
- Throttle and brake phase charts

**Racing Line Comparison**
- A/B lap comparison with cross-session selection
- Animated playback on Apple MapKit with speed-coded colors
- Play/pause, timeline scrub, and adjustable playback speed (1x-10x)
- Live delta display during playback

**Corner Analysis**
- Corner-by-corner performance ranking with time loss attribution
- Corner archetypes (entry-limited, mid-speed, exit-limited)
- Braking point consistency and entry/apex/exit speed metrics
- Corner map overlay

**Evolution Tracking**
- Lap time trends (best, average, median) across sessions at the same track
- Corner-by-corner improvement over time
- Cross-session racing line comparison

**Teams**
- Create teams and invite members
- Share sessions within a team
- Role-based access control (owner, member)

## Quick Start

### Container (recommended)

Requires [Podman](https://podman.io/) (or Docker) with compose support.

```bash
python3 -m venv venv
venv/bin/pip install podman-compose

# Start the app and PostgreSQL
venv/bin/podman-compose up --build -d

# Run database migrations
venv/bin/podman-compose exec web flask db upgrade

# Create a user
venv/bin/podman-compose exec web flask create-user \
  --email you@example.com --password secret --name "Your Name"
```

The app runs at **http://localhost:5050**.

### Local Development

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# Set environment variables
export DATABASE_URL="postgresql://user:pass@localhost/kart"
export SECRET_KEY="dev-secret"
export FLASK_APP="app:create_app"

# Run migrations and start
venv/bin/python -m flask db upgrade
venv/bin/python -m flask run --debug
```

## Usage

1. **Create a track** at `/tracks/create` — pick the location on the map, then define corners on the edit page.
2. **Upload a session** at `/sessions/create` — select the track, upload a RaceChrono CSV, and fill in session metadata.
3. **View the dashboard** — the session is automatically analyzed and the dashboard is available immediately.
4. **Track evolution** at `/dashboard/evolution` — compare performance across sessions at the same track.

## CLI Commands

```bash
flask create-user --email user@example.com --password secret --name "John Doe"
flask seed-tracks --file tracks.yaml       # bulk import tracks from a YAML file
flask import-session <race_dir> --user-email user@example.com
flask reingest-session <session_id>        # re-process after track corner changes
```

## API

All endpoints require authentication and return JSON.

| Endpoint | Description |
|---|---|
| `GET /api/sessions/<id>/summary` | Session stats, weather, excluded laps |
| `GET /api/sessions/<id>/charts/<type>` | Precomputed chart data (laptime_bar, delta_to_best, etc.) |
| `GET /api/sessions/<id>/charts/<type>/<lap>` | Per-lap chart variant (speed_map, braking_map, etc.) |
| `GET /api/sessions/<id>/laps` | Lap list with times |
| `GET /api/sessions/<id>/corners` | Corner analysis data |
| `GET /api/sessions/<id>/corners/map` | Corner map overlay |
| `GET /api/sessions/<id>/sectors` | Sector times |
| `GET /api/sessions/<id>/raceline` | Racing line data |
| `GET /api/evolution` | Cross-session lap time trends |
| `GET /api/evolution/corners` | Corner improvement across sessions |
| `GET /api/evolution/raceline` | Cross-session racing line comparison |
| `GET /api/tracks` | Tracks with sessions |

## Project Layout

```
app/                  Flask application
  auth/               Registration and login
  teams/              Team management
  tracks/             Track CRUD with corner editor
  sessions/           Session upload and ingest pipeline
  dashboard/          Dashboard and evolution pages
  api/                JSON API endpoints
  templates/          Jinja2 templates
  static/             CSS and JS (Plotly charts, MapKit maps)
scripts/analysis/     Telemetry analysis modules
migrations/           Alembic database migrations
tests/                Test suite
```

## Tech Stack

- **Backend:** Flask, SQLAlchemy, Pandas, SciPy
- **Frontend:** Bootstrap 5, Plotly.js, Apple MapKit JS
- **Database:** PostgreSQL (SQLite for tests)
- **Container:** Podman/Docker with multi-stage builds

## Running Tests

```bash
venv/bin/python -m pytest tests/ -x -q
```

## Data Format

Boxbox expects **RaceChrono v3 CSV exports** with GPS, accelerometer, and speed data. The CSV has a header row, a units row, and a source row, followed by telemetry samples. Duplicate columns from multiple sensors are handled automatically.
