import os

import click
import yaml
from flask.cli import with_appcontext

from app import db
from app.models import (
    User, Track, TrackCorner, Session,
    Lap, Telemetry, CornerRecord, CornerSummary,
    SectorTime, ChartData, SessionUpload,
)


@click.command('create-user')
@click.option('--email', required=True, help='User email')
@click.option('--password', required=True, help='User password')
@click.option('--name', required=True, help='Display name')
@with_appcontext
def create_user(email, password, name):
    """Create a new user from the command line."""
    if User.query.filter_by(email=email.lower()).first():
        click.echo(f'Error: User with email {email} already exists.')
        raise SystemExit(1)

    user = User(email=email.lower(), display_name=name)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    click.echo(f'User "{name}" ({email}) created successfully.')


@click.command('seed-tracks')
@click.option('--file', 'tracks_file', required=True,
              help='Path to tracks YAML file')
@with_appcontext
def seed_tracks(tracks_file):
    """Import tracks from a YAML file into the database."""
    if not os.path.exists(tracks_file):
        click.echo(f'Error: {tracks_file} not found.')
        raise SystemExit(1)

    with open(tracks_file) as f:
        tracks_data = yaml.safe_load(f)

    if not tracks_data:
        click.echo('No tracks found in file.')
        return

    for slug, data in tracks_data.items():
        if Track.query.filter_by(slug=slug).first():
            click.echo(f'  Skipping "{data["name"]}" (slug "{slug}" already exists)')
            continue

        track = Track(
            slug=slug,
            name=data['name'],
            lat=data['lat'],
            lon=data['lon'],
            timezone=data.get('timezone', 'UTC'),
        )
        db.session.add(track)
        db.session.flush()

        corners = data.get('corners', [])
        offset = 0.00005
        for i, c in enumerate(corners):
            corner = TrackCorner(
                track_id=track.id,
                name=c['name'],
                sort_order=i,
                trap_lat1=c['lat'] + offset, trap_lon1=c['lon'] - offset,
                trap_lat2=c['lat'] - offset, trap_lon2=c['lon'] + offset,
            )
            db.session.add(corner)

        db.session.commit()
        click.echo(f'  Imported "{data["name"]}" with {len(corners)} corners.')


@click.command('import-session')
@click.argument('race_dir')
@click.option('--user-email', required=True, help='Email of the user who owns this session')
@with_appcontext
def import_session(race_dir, user_email):
    """Import a session from an existing race directory."""
    from datetime import date as date_type
    from scripts.load_data import load_race_metadata
    from app.sessions.ingest import ingest_session

    race_dir = race_dir.rstrip('/')

    # Load metadata
    meta = load_race_metadata(race_dir)
    if not meta:
        click.echo(f'Error: no race.yaml in {race_dir}')
        raise SystemExit(1)

    # Find user
    user = User.query.filter_by(email=user_email.lower()).first()
    if not user:
        click.echo(f'Error: no user with email {user_email}')
        raise SystemExit(1)

    # Find track
    track_name = meta.get('track', '')
    track = None
    if track_name:
        # Try matching by name
        track = Track.query.filter(
            db.func.lower(Track.name) == track_name.lower()
        ).first()
    if not track:
        click.echo(f'Error: track "{track_name}" not found in database. Run flask seed-tracks first.')
        raise SystemExit(1)

    # Parse date
    raw_date = meta.get('date')
    if isinstance(raw_date, date_type):
        session_date = raw_date
    else:
        parts = str(raw_date).split('-')
        session_date = date_type(int(parts[0]), int(parts[1]), int(parts[2]))

    # CSV path
    csv_path = os.path.join(race_dir, 'telemetry.csv')
    if not os.path.exists(csv_path):
        click.echo(f'Error: no telemetry.csv in {race_dir}')
        raise SystemExit(1)

    # Create session
    session = Session(
        user_id=user.id,
        track_id=track.id,
        date=session_date,
        session_start=meta.get('session_start'),
    )
    db.session.add(session)
    db.session.flush()

    # Get track corners
    corners = TrackCorner.query.filter_by(track_id=track.id).order_by(TrackCorner.sort_order).all()
    track_corners = [
        {
            'name': c.name, 'lat': c.lat, 'lon': c.lon,
            'trap_lat1': c.trap_lat1, 'trap_lon1': c.trap_lon1,
            'trap_lat2': c.trap_lat2, 'trap_lon2': c.trap_lon2,
        }
        for c in corners
    ] if corners else None
    track_coords = (track.lat, track.lon, track.timezone)

    click.echo(f'Importing {race_dir} for user {user_email}...')
    ingest_session(csv_path, session, track_coords, track_corners)
    click.echo(f'Session {session.id} imported successfully.')


@click.command('reingest-session')
@click.argument('session_id', type=int)
@with_appcontext
def reingest_session(session_id):
    """Re-process a session from its stored compressed CSV."""
    from app.sessions.reingest import reingest_session as _reingest

    session = db.session.get(Session, session_id)
    if not session:
        click.echo(f'Error: session {session_id} not found.')
        raise SystemExit(1)

    click.echo(f'Reingesting session {session_id}...')
    success = _reingest(session)
    if not success:
        click.echo(f'Error: no stored CSV for session {session_id}.')
        raise SystemExit(1)
    click.echo(f'Session {session_id} reingested successfully.')
