# AGENTS.md

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

- `app/` — Flask application (auth, sessions, tracks, api, dashboard, leaderboard, admin, legal blueprints)
- `app/sessions/ingest.py` — CSV upload → analysis → DB insert pipeline
- `app/cli.py` — CLI commands (seed-tracks, import-session, reingest-session, seed-demo, set-admin)
- `app/api/routes.py` — JSON API endpoints for dashboard data
- `app/templates/` — Jinja2 HTML templates
- `app/static/` — CSS and JS (dashboard.js, raceline.js, videosync.js, gopro-extract.js, mapkit-helpers.js)
- `scripts/analysis/` — shared analysis modules (used by the ingest pipeline)
- `scripts/load_data.py` — telemetry and metadata loading functions
- `migrations/` — Flask-Migrate (Alembic) database migrations
- `tests/app/` — app test suite

## Data Conventions

- RaceChrono v3 CSV: header row, units row, source row; duplicate columns deduplicated by sensor suffix
- Speed in telemetry is m/s (multiply by 3.6 for km/h)
- Ingest pipeline calls analysis modules from `scripts/analysis/`
- All chart data is precomputed on ingest and stored as JSONB in the `chart_data` table

## Code Conventions

- Flask with Blueprints (auth, sessions, tracks, api, dashboard, leaderboard, admin, legal)
- SQLAlchemy ORM with Flask-Migrate for schema management
- Plotly for all charts (rendered client-side via Plotly.react())
- Apple MapKit JS for all maps
- Bootstrap 5 for layout

## Deployment

- Production is a single droplet running the app with docker compose (`docker-compose.prod.yml` + `.env.production`); the repo is checked out at `~/boxbox` on the server
- Deploys are fully automated: push to `main` → GitHub Actions (`.github/workflows/deploy.yml`) runs the test suite, builds the image as `ghcr.io/apahim/boxbox` (tagged `latest` + commit SHA), then SSHes to the droplet to pull the image, restart `web`, run `flask db upgrade`, and health-check `/health`
- Never deploy by hand (no manual image pushes, no manual restarts) — all changes reach production via git push to `main`
- Deploy credentials live in GitHub Actions secrets (`DROPLET_HOST`, `DROPLET_USER`, `DROPLET_SSH_KEY`)
- The MapKit JS token (`MAPKIT_TOKEN`) expires roughly every 6 months — when it does, track maps stop loading while everything else keeps working. Check the Admin dashboard (Data Health → MapKit token) or startup logs. Regenerate with `venv/bin/python scripts/generate_mapkit_token.py --team-id <TEAM_ID>` (key: `config/AuthKey_*.p8`), update `.env.production` on the droplet, and restart `web`
- This repo is public, so the production host/SSH details are intentionally not committed; they live in `DEPLOYMENT.local.md` (gitignored, loaded into OpenCode sessions via `opencode.jsonc`)

### Inspecting production

SSH to the droplet (see `DEPLOYMENT.local.md` if present), then from `~/boxbox`:

```bash
# Follow app logs
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f web

# One-off app context for queries (users, sessions, etc.)
docker compose -f docker-compose.prod.yml --env-file .env.production exec web python -c \
  "from app import create_app, db; from app.models import User; app=create_app(); app.app_context().push(); print([u.email for u in User.query.all()])"

# Flask shell (interactive)
docker compose -f docker-compose.prod.yml --env-file .env.production exec web flask shell

# Run pending migrations manually (Actions does this on every deploy)
docker compose -f docker-compose.prod.yml --env-file .env.production exec web flask db upgrade
```

- Production is PostgreSQL — read-only inspection is fine, but be careful with writes and never run destructive commands against prod data
- Prefer making changes locally, testing, and redeploying over hotfixing on the server

## Workflow

After making changes:

1. Run tests: `venv/bin/python -m pytest tests/ -x -q`
2. Commit and push to `main` — GitHub Actions builds and rolls out automatically
3. Verify the rollout: check the Actions run succeeded, then confirm the production site's `/health` endpoint returns ok
