# Plan: Cloud-Hosted Kart Telemetry Platform

## Context

The kart racing project is currently a static site generator: Python scripts parse RaceChrono CSV exports, run 14 analysis modules, and produce HTML dashboards. There is no database — every regeneration re-parses the full ~24MB CSV. The goal is to turn this into a proper cloud-hosted web application with user auth, CSV upload, track management, team collaboration, and dashboards served from a database via API endpoints.

## Architecture Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Database | **PostgreSQL** | Handles 117k telemetry rows/session well. SQL queries across sessions enable cross-race analysis. Managed Postgres on Railway/Neon is free-tier friendly (~13MB/session = ~75 sessions in 1GB). |
| Framework | **Flask** | Already using Jinja2. Flask-Login for auth, Flask-SQLAlchemy for ORM. Stays out of the way of pandas workflows. Single-developer friendly. |
| Frontend | **Server-rendered shell + JSON API** | Dashboard page loads as lightweight shell. Chart/map data fetched on demand via JSON API endpoints. Plotly renders client-side via `Plotly.react()`. Eliminates 12MB inline embedding. |
| Auth | **Flask-Login + bcrypt** | Self-registration with email/password/display name. |
| Tenancy | **Multi-tenant with teams** | Users own their data. Teams (many-to-many) enable shared visibility. Team creator manages membership. Team dashboard deferred to future scope. |
| Hosting | **TBD** | Evaluate Railway, Render, Fly.io — see hosting comparison below. |
| Telemetry storage | **In the database** | Enables SQL queries across sessions. ~13MB/session in Postgres is fine at this scale. No object storage complexity. |
| CSV handling | **Process on upload, store results in DB, keep compressed original as backup** | CSV is an import format, not a storage format. |
| Chart data | **Precompute on ingest** | All chart-ready JSON stored in `chart_data` table (JSONB) during CSV upload. API endpoints read and return — no computation at request time. `flask reingest-session` CLI for when analysis code changes. |
| Ingest mode | **Synchronous** | Block on upload, show spinner. No task queue infrastructure needed at this scale. |
| Cross-session | **SQL queries replace `evolution.py`** | `evolution.py` reads from filesystem (no race dirs in cloud). New DB-native queries for lap trends, corner improvement, racing line comparison. |

## Database Schema

```sql
-- Auth & Teams
users (id, email, password_hash, display_name, created_at)
teams (id, name, slug, created_by, created_at)
team_members (id, team_id, user_id, role, joined_at)
  -- role: 'owner' | 'member'
  -- UNIQUE(team_id, user_id)

-- Track definitions
tracks (id, slug, name, lat, lon, timezone, created_by)
track_corners (id, track_id, name, sort_order, lat, lon)

-- Sessions (one per CSV upload)
sessions (
  id, user_id, track_id, team_id NULLABLE,
  date, session_type, session_start, kart_number, driver_weight_kg,
  -- Precomputed summary stats
  total_laps, clean_laps, best_lap_time, average_time, median_time,
  std_dev, consistency_pct, top_speed_kmh,
  max_lateral_g, max_braking_g, max_accel_g,
  weather JSONB, coaching JSONB,
  created_at
)

-- Per-lap data
laps (id, session_id, lap_number, seconds, is_outlier, outlier_reason)

-- Raw telemetry (~82k rows per session, only race laps)
telemetry (
  id BIGSERIAL, session_id, lap_number, sample_index,
  timestamp, elapsed_time, distance_traveled,
  latitude, longitude, altitude, bearing,
  speed_gps, speed_calc,
  lateral_acc, longitudinal_acc, combined_acc,
  x_acc, y_acc, z_acc,
  x_rotation, y_rotation, z_rotation, lean_angle
  -- INDEX on (session_id, lap_number)
)

-- Corner analysis (maps to CornerRecord dataclass)
corner_records (
  id, session_id, corner_name, corner_index, lap_number,
  lat, lon, distance, corner_frac,
  entry_speed, min_speed, exit_speed,
  time_loss, braking_point, braking_distance, trail_braking_depth,
  root_cause  -- "entry"|"mid"|"exit"|NULL
)

-- Corner aggregates (maps to CornerSummary dataclass)
corner_summaries (
  id, session_id, corner_name, corner_index,
  lat, lon, distance,
  archetype, avg_time_loss, total_time_loss,
  best_min_speed, avg_min_speed, std_min_speed,
  best_entry_speed, best_exit_speed,
  braking_spread, dominant_root_cause
)

-- Sector times
sector_times (id, session_id, lap_number, sector_index, sector_name, seconds)

-- Precomputed chart data (replaces 12MB inline embedding)
chart_data (
  id, session_id, chart_type, chart_key,
  data JSONB,
  created_at
)
-- chart_type: 'speed_map' | 'braking_map' | 'sector_map' | 'lateral_g_map' |
--             'cumulative_delta' | 'throttle_brake' |
--             'laptime_bar' | 'delta_to_best' | 'gg_diagram' |
--             'braking_consistency' | 'brake_release' | 'raceline'
-- chart_key: lap number (string) or 'overview' for non-lap-specific charts
-- INDEX on (session_id, chart_type, chart_key)

-- Original CSV backup
session_uploads (id, session_id, original_filename, csv_compressed BYTEA, uploaded_at)
```

## API Layer Design

The dashboard page loads as a lightweight shell with metadata. All chart/map data is fetched on demand via JSON API endpoints. All endpoints read from the `chart_data` table (precomputed JSONB) — no analysis computation at request time.

Auth middleware checks: `session.user_id == current_user.id OR current_user in session.team.members`.

```
GET /api/sessions/{id}/summary                    → summary stats, lap list, weather, coaching
GET /api/sessions/{id}/charts/laptime-bar         → Plotly JSON for lap time bar chart
GET /api/sessions/{id}/charts/delta-to-best       → Plotly JSON for delta to best lap chart
GET /api/sessions/{id}/charts/gg-diagram          → Plotly JSON for GG diagram
GET /api/sessions/{id}/charts/braking-consistency  → Plotly JSON
GET /api/sessions/{id}/charts/brake-release        → Plotly JSON for trail braking depth chart
GET /api/sessions/{id}/maps/speed/{lap}           → map data dict for speed overlay
GET /api/sessions/{id}/maps/braking/{lap}         → map data dict for braking overlay
GET /api/sessions/{id}/maps/sectors/{lap}         → map data dict for sector deltas
GET /api/sessions/{id}/maps/lateral-g/{lap}       → map data dict for lateral G overlay
GET /api/sessions/{id}/charts/cumulative-delta/{lap} → Plotly JSON
GET /api/sessions/{id}/charts/throttle-brake/{lap}   → Plotly JSON
GET /api/sessions/{id}/corners                    → corner summaries + per-lap breakdowns
GET /api/sessions/{id}/corners/map                → corner map overlay data
GET /api/sessions/{id}/sectors                    → sector times table data
GET /api/sessions/{id}/raceline                   → racing line coordinates for all clean laps (serves the A/B lap comparison within a single session)
```

### Evolution API (cross-session, SQL-based)

```
GET /api/evolution?track_id={id}                  → lap time trends, consistency trends
GET /api/evolution/corners?track_id={id}          → corner improvement over time
GET /api/evolution/raceline?session_ids=a,b&laps=x,y → racing line data for cross-session comparison
```

Example SQL queries:

```sql
-- Lap time trend across sessions
SELECT s.date, s.best_lap_time, s.average_time, s.consistency_pct
FROM sessions s WHERE s.user_id = ? AND s.track_id = ?
ORDER BY s.date;

-- Corner improvement over time
SELECT s.date, cs.corner_name, cs.avg_time_loss, cs.best_min_speed
FROM corner_summaries cs JOIN sessions s ON cs.session_id = s.id
WHERE s.user_id = ? AND s.track_id = ?
ORDER BY s.date, cs.corner_index;

-- Racing line comparison across sessions
SELECT t.lap_number, t.latitude, t.longitude, t.elapsed_time
FROM telemetry t JOIN sessions s ON t.session_id = s.id
WHERE s.id IN (?, ?) AND t.lap_number IN (?, ?)
ORDER BY t.session_id, t.sample_index;
```

## Application Structure

```
kart/
  app/
    __init__.py                  # Flask app factory (create_app)
    config.py                    # Config from env vars (DATABASE_URL, SECRET_KEY)
    models.py                    # SQLAlchemy models
    auth/
      __init__.py                # Blueprint
      routes.py                  # login, logout, register
      forms.py                   # LoginForm, RegisterForm
    sessions/
      __init__.py                # Blueprint
      routes.py                  # list, create (upload + metadata form), detail
      forms.py                   # SessionCreateForm
      ingest.py                  # CSV parse -> analysis -> DB insert + chart precompute
    tracks/
      __init__.py                # Blueprint
      routes.py                  # list, create, edit (map-based corner placement)
      forms.py                   # TrackForm
    teams/
      __init__.py                # Blueprint
      routes.py                  # create, manage members, list
      forms.py                   # TeamForm, AddMemberForm
    api/
      __init__.py                # Blueprint
      routes.py                  # All /api/ endpoints (JSON)
      auth.py                    # API auth decorator (session-based, same as web)
    dashboard/
      __init__.py                # Blueprint
      routes.py                  # Render lightweight dashboard shell
    templates/
      base.html                  # Base layout (nav, Bootstrap 5)
      auth/login.html, register.html
      sessions/list.html, create.html
      tracks/list.html, edit.html
      teams/list.html, manage.html
      dashboard/dashboard.html   # Lightweight shell — data loaded via API
    static/
      css/dashboard.css          # Extracted from inline styles
      js/
        dashboard.js             # Tab management, lazy data loading, Plotly.react() calls
        mapkit-helpers.js        # Map init, canvas overlay, corner labels, wind indicator
        raceline.js              # A/B comparison, animation, polyline, timeline slider
    cli.py                       # CLI commands: create-user, seed-tracks, import-session, reingest-session
  scripts/
    analysis/                    # UNCHANGED - all 14 modules stay as-is
    load_data.py                 # UNCHANGED - reused by ingest pipeline
  migrations/                    # Flask-Migrate (Alembic)
  tests/
    # Existing analysis tests (UNCHANGED)
    test_api.py                  # NEW — API endpoint tests
    test_ingest.py               # NEW — ingest pipeline tests
    test_models.py               # NEW — model/query tests
    test_auth.py                 # NEW — registration, login, team membership
  Procfile                       # web: gunicorn "app:create_app()"
  requirements.txt               # Add flask, flask-login, flask-sqlalchemy, etc.
```

## Core Design: Ingest Pipeline (`app/sessions/ingest.py`)

The bridge between existing analysis code and the database. On CSV upload (synchronous — blocks until complete):

1. Parse CSV using existing `load_racechrono_session()` -> DataFrame
2. Extract lap times using existing `extract_laptimes_from_telemetry()` + `filter_non_race_laps()`
3. Create `Session` record with metadata from the form
4. Bulk-insert telemetry rows (use `COPY` or `bulk_insert_mappings` for speed)
5. Store lap records with outlier detection via existing `detect_outliers()`
6. Generate summary via existing `generate_summary()` -> store on session row
7. Run corner analysis via existing `build_corner_analysis()` -> store in `corner_records` + `corner_summaries`
8. Run sector analysis via existing `create_sector_times_table()` -> store in `sector_times`
9. **Precompute all chart data** -> store in `chart_data` table:
   - Per clean lap: speed_map, braking_map, sector_map, lateral_g_map, cumulative_delta, throttle_brake
   - Overview: laptime_bar, delta_to_best, gg_diagram, braking_consistency, brake_release
   - Racing line data for all clean laps
10. Generate coaching via existing `generate_coaching_summary()` -> store as JSONB
11. Fetch weather via existing `fetch_weather()` -> store as JSONB
12. Store compressed original CSV in `session_uploads`
13. Redirect to dashboard page

**Re-ingest CLI**: `flask reingest-session <session_id>` — deletes precomputed data and reruns steps 5-12. Needed when analysis code changes.

**Key insight**: All existing analysis modules accept DataFrames and return plain dicts. They don't change. The ingest pipeline calls them exactly as `generate_dashboard.py` does today.

## Dashboard Frontend Architecture

The dashboard template becomes a lightweight shell. Data is loaded via fetch() calls to the JSON API:

- **On page load**: fetch `/api/sessions/{id}/summary` → render metadata, lap list, weather badge
- **Overview tab**: fetch laptime-bar + gg-diagram charts → `Plotly.react()`
- **Deep Dive tab**: user selects lap → fetch speed map + cumulative delta + throttle brake
- **Corners tab**: fetch corner summaries + corner map. Lap selector fetches per-lap breakdown.
- **Sectors tab**: fetch sector times table data
- **Racing Line tab**: fetch raceline data, initialize MapKit animation

### Inline JS Extraction

Current 568 lines of inline JS in `dashboard.html.j2` extracted to 3 focused modules:

| File | Responsibility | Lines (approx) |
|------|---------------|-----------------|
| `dashboard.js` | Tab management, lazy data loading, Plotly.react() calls, lap selector handlers | ~150 |
| `mapkit-helpers.js` | `initSatMap()`, canvas overlay, color scales, corner labels, wind indicator, tooltips | ~200 |
| `raceline.js` | Racing line polylines, A/B selector, animation (requestAnimationFrame), timeline slider, delta display | ~200 |
| `dashboard.css` | All custom CSS extracted from `<style>` block | ~70 |

## Pages

1. **Register** — email/password/display name form
2. **Login** — email/password form
3. **Session list** — user's sessions + sessions visible via team membership
4. **Session create** — CSV upload + metadata form (date, track dropdown, kart number, weight, session type, start time, optional team assignment)
5. **Track list** — all tracks with corner counts
6. **Track editor** — MapKit JS map with clickable/draggable corner markers, name inputs, reorder
7. **Dashboard** — lightweight shell, chart/map data loaded via API
8. **Team list** — user's teams (created + member-of)
9. **Team manage** — add/remove members by email, only for team owner

## Implementation Phases

### Phase 1: Flask skeleton + Auth + Database + Teams
- Flask app factory, config, SQLAlchemy models for all tables
- PostgreSQL schema via Flask-Migrate
- Registration + Login pages with Flask-Login
- Team creation and member management pages
- CLI: `flask create-user`, `flask seed-tracks`
- Deploy to chosen hosting platform

### Phase 2: Track management
- Track list/create/edit pages
- MapKit JS map for corner placement (click to add, drag to move, name input)
- Corner auto-detection fallback: when a track has no manually-placed corners and a session is uploaded, run `auto_detect_corners()` on the telemetry to bootstrap corner positions. Offer the user the auto-detected corners for review/editing.
- CLI: `flask seed-tracks` to import from `data/tracks.yaml`

### Phase 3: Session upload + Ingest pipeline
- Session create form with CSV upload + metadata fields
- Full `ingest.py` pipeline (parse -> analyze -> precompute -> store)
- Session list page (user's own + team-visible)
- CLI: `flask import-session <race_dir>` for existing data
- CLI: `flask reingest-session <id>` for re-processing after code changes

### Phase 4: API layer + Dashboard
- All `/api/sessions/{id}/...` endpoints reading from `chart_data`
- Dashboard template as lightweight shell with fetch()-based data loading
- Client-side JS modules (`dashboard.js`, `mapkit-helpers.js`, `raceline.js`)
- Extracted `dashboard.css`
- Tab-based lazy loading with `Plotly.react()` rendering

### Phase 5: Cross-session evolution (SQL-based)
- New SQL queries for lap trends, corner improvement, consistency tracking
- Evolution API endpoints (`/api/evolution/...`)
- Evolution page with Plotly charts rendered client-side
- Racing line comparison across sessions

## Testing Strategy

| Layer | What to test | How |
|-------|-------------|-----|
| Models | User, Team, Session creation; team membership queries; data isolation | pytest + test DB |
| Ingest | CSV parse → DB round-trip; verify stored data matches `summary_generated.yaml` | pytest with fixture CSVs |
| API | Each endpoint returns correct JSON shape; auth enforcement; team visibility | pytest Flask test client |
| Auth | Registration, login, logout; duplicate email rejection; team owner permissions | pytest Flask test client |
| Analysis | Existing 14 test modules | UNCHANGED |
| Frontend | Manual smoke test — compare rendered dashboard with current static HTML | Visual parity check |

## Hosting Comparison

| Platform | Managed Postgres | Free tier | Deploy from Git | Notes |
|----------|-----------------|-----------|----------------|-------|
| Railway | Yes | $5/mo credit | Yes | Simple, good DX, but free tier shrinking |
| Render | Yes | 90-day free DB | Yes | Free web service (sleeps after 15min inactivity) |
| Fly.io | Yes (Supabase addon) | $5/mo credit | Yes (flyctl) | More infra control, Fly Postgres is self-managed |
| Neon + container | Yes (Neon free) | Neon: 0.5GB free | Varies | Neon for DB, any container host for app |

Recommend evaluating **Render** (simplest free tier) or **Railway** (best DX) first.

## What Does NOT Change

- `scripts/analysis/` — all 14 modules unchanged
- `scripts/load_data.py` — CSV parsing reused by ingest
- Existing tests continue to pass
- Plotly for all charts, MapKit JS for all maps, Bootstrap 5 for layout

## What Gets Replaced

- `scripts/analysis/evolution.py` — filesystem-based cross-session analysis (`load_all_races`, `load_all_laptimes`, `prepare_raceline_data`) replaced by SQL queries. Note: there is no `generate_evolution.py` script; evolution functions live in this analysis module.
- `scripts/templates/dashboard.html.j2` inline JS/CSS — extracted to static files + refactored for API-based data loading
- `scripts/generate_dashboard.py` orchestration — replaced by ingest pipeline (same module calls, different output target)
- `scripts/generate_index.py` — race listing page replaced by the Session list page (user's own + team-visible sessions)

## What Coexists (Transitional)

The static site generation pipeline (`scripts/generate_all.py`, `generate_dashboard.py`, `generate_index.py`) continues to work alongside the Flask app. The analysis modules are shared; only the output target differs (HTML files to `docs/` vs. database rows). The static pipeline can be deprecated once the cloud app reaches parity and GitHub Pages hosting is no longer needed.

## MapKit Token Management

The MapKit JS token is currently passed as a Jinja2 template variable. In the cloud app, the token must be available to the client-side JS modules. Approach: embed it in the dashboard shell template as a `<meta>` tag or JS global (e.g., `window.MAPKIT_TOKEN`), populated from server-side config (`MAPKIT_TOKEN` env var). This avoids a separate API endpoint and keeps the token out of JS bundles.

## Data Import Dependency Order

When bootstrapping the cloud app with existing data, CLI commands must run in this order:

1. `flask db upgrade` — apply migrations
2. `flask create-user` — create user account
3. `flask seed-tracks` — import tracks from `data/tracks.yaml` (creates track + corner records)
4. `flask import-session <race_dir>` — import each session (requires user and track to exist)

The `import-session` CLI must resolve the track from `race.yaml` metadata (track name) against the `tracks` table, and assign the session to the specified user.

## New Dependencies

```
flask
flask-login
flask-sqlalchemy
flask-migrate
flask-wtf
psycopg2-binary
gunicorn
bcrypt
```

## Verification

After each phase:
1. Run existing tests: `venv/bin/python -m pytest tests/ -x -q`
2. Phase 1: Verify registration + login flow works, DB migrations apply cleanly, team create/manage works
3. Phase 2: Create a track via UI, verify corners appear on map
4. Phase 3: Upload a CSV from `data/races/`, verify all tables populated correctly. Compare summary stats with existing `summary_generated.yaml`. Verify `chart_data` rows exist for all chart types.
5. Phase 4: Compare rendered dashboard with current static HTML — visual parity check. Verify API endpoints return correct JSON. Verify team member can view teammate's dashboard.
6. Phase 5: Import all 3 existing sessions, verify cross-session queries return expected data
