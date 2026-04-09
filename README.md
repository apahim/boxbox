<p align="center">
  <img src="app/static/favicon.svg" alt="BoxBox" width="64" height="64">
</p>

<h1 align="center">BoxBox</h1>

<p align="center">
  Racing telemetry dashboard — turn your <a href="https://racechrono.com/">RaceChrono</a> CSV exports or <strong>GoPro MP4</strong> videos into interactive dashboards with lap analysis, corner breakdowns, racing line comparisons, and coaching insights.
</p>

<p align="center">
  Built with Flask, PostgreSQL, Plotly, and Apple MapKit JS.
</p>

---

## Getting Started

### 1. Start the app

Requires [Podman](https://podman.io/) (or Docker) with compose support.

```bash
python3 -m venv venv
venv/bin/pip install podman-compose

# Start the app and PostgreSQL
venv/bin/podman-compose up --build -d

# Run database migrations
venv/bin/podman-compose exec web flask db upgrade
```

The app runs at **http://localhost:5050**.

### 2. Sign in

BoxBox uses **Google Sign-In** for authentication. You'll need to set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` environment variables (see [Environment Variables](#environment-variables)).

### 3. Explore the demo

On first login, BoxBox offers to load a demo session with real telemetry data so you can explore the dashboard immediately. You can skip this and upload your own data right away.

---

## Uploading a Session

BoxBox uses a 3-step upload wizard:

1. **Choose your source** — select RaceChrono (CSV) or GoPro (MP4 video).
2. **Fill in details** — date, track, session start time, and labels. The date, time, and track are auto-detected from GPS data when possible.
3. **Review & upload** — confirm and process. The telemetry is analyzed and the dashboard is available immediately.

### RaceChrono

Export your session as a **RaceChrono v3 CSV** (with GPS, accelerometer, and speed data). The CSV has a header row, a units row, and a source row, followed by telemetry samples. Duplicate columns from multiple sensors are handled automatically.

### GoPro

Select one or more **GoPro MP4 files** from the same session (supports chaptered video, e.g., GX010001.MP4, GX020001.MP4). BoxBox extracts the GPS telemetry directly in the browser — the video file is never uploaded to the server.

If the track has a start/finish gate configured, laps are detected automatically from the GPS data.

---

## Setting Up Tracks

1. Go to **Tracks > Add Track**.
2. Search for your track or circuit on the satellite map and position the crosshair on the track.
3. Give it a name and save.
4. On the **track edit page**, configure:
   - **Start/finish line** — draw a gate across the track for accurate lap detection.
   - **Corner trap lines** — click the map or use the "+ Add" button to place trap lines at each corner. Drag endpoints to position them, rename corners, and reorder via drag-and-drop.

When you add or edit corners, existing sessions at that track are flagged for reingestion so the corner analysis updates automatically.

---

## Dashboard

Each session has an interactive dashboard with four tabs (plus Video Sync for GoPro sessions):

### Session Overview

- **Summary stats** — best lap, average, consistency percentage, total laps.
- **Lap time bar chart** with automatic outlier detection and exclusion.
- **Delta-to-best chart** — see how each lap compares to your fastest.
- **Sector time breakdown** — when corners are configured.
- **Coaching summary** — actionable feedback generated from your telemetry.
- **Weather** — automatically fetched based on date, time, and track location.

### Lap Deep Dive

Select any clean lap and see:

- **Track maps** — speed zones, braking zones, and sector delta overlays on Apple MapKit satellite imagery.
- **Cumulative delta trace** — time gained/lost vs the median lap, plotted against distance.
- **Throttle & brake phase chart** — longitudinal acceleration inputs through the lap.

### Racing Line Comparison

- **A/B comparison** — pick Lap A from this session and Lap B from any session at the same track (cross-session).
- **Animated playback** on the satellite map with speed-coded racing line colors.
- **Playback controls** — play/pause, timeline scrub, adjustable speed (1x-10x).
- **Live delta display** during playback.

### Corner Analysis

- **Corner performance table** — ranked by time loss with root cause classification.
- **Corner archetypes** — entry-limited, mid-speed, or exit-limited.
- **Metrics per corner** — entry/apex/exit speed, braking point consistency, braking distance spread.
- **Braking consistency chart** — across all corners.
- **Corner map overlay** on satellite imagery.

### Video Sync (GoPro sessions)

- Load your GoPro video file locally (it stays on your device and is never uploaded).
- Watch the video synchronized with the racing line on the map.
- The position dot tracks your location in real time as the video plays.
- Choose map overlays: racing line, speed heatmap, or braking/acceleration.

---

## Session Management

- **Labels** — tag sessions with custom labels (e.g., Wet, Dry, Race, Practice, New tyres). Labels are suggested from your history and filterable on the sessions list.
- **Filters** — filter the sessions list by track, data source (RaceChrono/GoPro), and labels.
- **Sorting** — sort by date, track, best lap, clean laps, or consistency.
- **Sharing** — generate a time-limited share link (30-day expiry) for any session. Recipients can view the full dashboard without signing in.
- **Reingest** — when you update a track's corners or start/finish gate, affected sessions can be reingested to pick up the changes.

---

## CLI Commands

```bash
flask seed-tracks --file tracks.yaml            # bulk import tracks from a YAML file
flask import-session <race_dir> --user-email user@example.com
flask reingest-session <session_id>              # re-process from stored compressed CSV
flask seed-demo --user-email user@example.com    # seed demo data for a user
flask seed-demo --all                            # seed demo data for all users without it
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes (prod) | PostgreSQL connection string |
| `SECRET_KEY` | Yes (prod) | Flask secret key (must not be the default) |
| `GOOGLE_CLIENT_ID` | Yes | Google OAuth 2.0 client ID |
| `GOOGLE_CLIENT_SECRET` | Yes | Google OAuth 2.0 client secret |
| `MAPKIT_TOKEN` | Yes (prod) | Apple MapKit JS JWT token |

---

## Local Development

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt

export DATABASE_URL="postgresql://user:pass@localhost/boxbox"
export SECRET_KEY="dev-secret"
export FLASK_APP="app:create_app"
export GOOGLE_CLIENT_ID="your-client-id"
export GOOGLE_CLIENT_SECRET="your-client-secret"
export MAPKIT_TOKEN="your-mapkit-token"

venv/bin/python -m flask db upgrade
venv/bin/python -m flask run --debug
```

### Running Tests

```bash
venv/bin/python -m pytest tests/ -x -q
```

Tests use an in-memory SQLite database and don't require any external services.

---

## API

All endpoints return JSON. Authenticated via session cookie or `share_token` query parameter (for shared sessions).

| Endpoint | Description |
|---|---|
| `GET /api/sessions/<id>/summary` | Session stats, weather, coaching, excluded laps |
| `GET /api/sessions/<id>/charts/<type>` | Overview chart data (laptime_bar, delta_to_best, braking_consistency) |
| `GET /api/sessions/<id>/charts/<type>/<lap>` | Per-lap chart (speed_map, braking_map, sector_map, cumulative_delta, throttle_brake) |
| `GET /api/sessions/<id>/laps` | Lap list with times and best-lap flag |
| `GET /api/sessions/<id>/corners` | Corner analysis data |
| `GET /api/sessions/<id>/corners/map` | Corner map overlay data |
| `GET /api/sessions/<id>/sectors` | Sector time breakdown |
| `GET /api/sessions/<id>/raceline` | Racing line GPS traces per lap |
| `GET /api/sessions/raceline?session_ids=1,2` | Batch raceline data for cross-session comparison |
| `GET /api/sessions/<id>/detect-track` | Auto-detect track from first GPS coordinate |
| `PUT /api/sessions/<id>/video-filename` | Save local video filename for a session |
| `GET /api/tracks` | Tracks the user has sessions at |
| `GET /api/tracks/<id>/sessions` | User's sessions at a given track |
| `GET /api/tracks/<id>/gate` | Start/finish gate coordinates |
| `GET /api/labels` | Distinct labels across user's sessions |

---

## Project Layout

```
app/                      Flask application
  auth/                   Google OAuth sign-in
  sessions/               Session upload, edit, delete, share, reingest
    ingest.py             CSV → analysis → database pipeline
    reingest.py           Re-process from stored compressed CSV
  tracks/                 Track CRUD with corner and S/F gate editor
  dashboard/              Session dashboard and shared view
  api/                    JSON API endpoints
  demo_data/              Demo session seeding
  legal/                  Terms of service and privacy policy
  templates/              Jinja2 HTML templates
  static/                 CSS and JS
    js/dashboard.js       Dashboard tab logic and chart rendering
    js/raceline.js        Racing line A/B comparison with playback
    js/videosync.js       GoPro video sync with map
    js/gopro-extract.js   Client-side GoPro telemetry extraction
    js/mapkit-helpers.js   Apple MapKit utilities
scripts/analysis/         Telemetry analysis modules (shared with static pipeline)
migrations/               Alembic database migrations
tests/                    Test suite (pytest, in-memory SQLite)
```

## Tech Stack

- **Backend:** Flask, SQLAlchemy, Pandas, NumPy, SciPy
- **Frontend:** Bootstrap 5, Plotly.js, Apple MapKit JS
- **Database:** PostgreSQL (SQLite for local dev and tests)
- **Auth:** Google OAuth 2.0 via Authlib
- **Container:** Podman/Docker with multi-stage builds, Gunicorn, Caddy reverse proxy
