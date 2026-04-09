"""Seed demo data (track + session) for a user."""

import gzip
import logging
import os
import tempfile
from datetime import date as date_type

import yaml

from app import db
from app.models import Session, Track, TrackCorner
from app.sessions.ingest import ingest_session

logger = logging.getLogger(__name__)

DEMO_DIR = os.path.dirname(__file__)
DEMO_TRACK_FILE = os.path.join(DEMO_DIR, 'track.yaml')
DEMO_SESSION_FILE = os.path.join(DEMO_DIR, 'session.yaml')
DEMO_CSV_FILE = os.path.join(DEMO_DIR, 'session.csv.gz')


def _ensure_demo_track(user_id):
    """Create the demo track if it doesn't exist. Returns the Track."""
    with open(DEMO_TRACK_FILE) as f:
        tracks_data = yaml.safe_load(f)

    slug = list(tracks_data.keys())[0]
    data = tracks_data[slug]

    # Check if this user already has this track
    track = Track.query.filter_by(slug=slug, created_by=user_id).first()
    if track:
        return track

    # Ensure unique slug if another user owns a track with the same slug
    base_slug = slug
    counter = 2
    while Track.query.filter_by(slug=slug).first():
        slug = f'{base_slug}_{counter}'
        counter += 1

    track = Track(
        slug=slug,
        name=data['name'],
        lat=data['lat'],
        lon=data['lon'],
        timezone=data.get('timezone', 'UTC'),
        created_by=user_id,
    )

    # Start/finish gate
    sf = data.get('sf_gate')
    if sf:
        track.sf_lat1 = sf['lat1']
        track.sf_lon1 = sf['lon1']
        track.sf_lat2 = sf['lat2']
        track.sf_lon2 = sf['lon2']

    db.session.add(track)
    db.session.flush()

    # Corners with full trap coordinates
    for c in data.get('corners', []):
        corner = TrackCorner(
            track_id=track.id,
            name=c['name'],
            sort_order=c['sort_order'],
            trap_lat1=c['trap_lat1'],
            trap_lon1=c['trap_lon1'],
            trap_lat2=c['trap_lat2'],
            trap_lon2=c['trap_lon2'],
        )
        db.session.add(corner)

    db.session.flush()
    return track


def seed_demo_data(user):
    """Create a demo session for the given user.

    Ensures the demo track exists, decompresses the bundled CSV,
    and runs the full ingest pipeline. Marks user.demo_seeded = True.
    """
    if user.demo_seeded:
        return

    track = _ensure_demo_track(user.id)

    # Load session metadata
    with open(DEMO_SESSION_FILE) as f:
        meta = yaml.safe_load(f)

    # Parse date
    raw_date = meta['date']
    if isinstance(raw_date, date_type):
        session_date = raw_date
    else:
        parts = str(raw_date).split('-')
        session_date = date_type(int(parts[0]), int(parts[1]), int(parts[2]))

    session = Session(
        user_id=user.id,
        track_id=track.id,
        date=session_date,
        session_start=meta.get('session_start'),
        data_source=meta.get('data_source', 'racechrono'),
        labels=['Demo'],
    )
    db.session.add(session)
    db.session.flush()

    # Decompress CSV to temp file
    with open(DEMO_CSV_FILE, 'rb') as f:
        csv_bytes = gzip.decompress(f.read())

    temp_fd, temp_path = tempfile.mkstemp(suffix='.csv')
    try:
        with os.fdopen(temp_fd, 'wb') as tmp:
            tmp.write(csv_bytes)

        # Build track info for ingest
        corners = TrackCorner.query.filter_by(track_id=track.id).order_by(
            TrackCorner.sort_order
        ).all()
        track_corners = [
            {
                'name': c.name, 'lat': c.lat, 'lon': c.lon,
                'trap_lat1': c.trap_lat1, 'trap_lon1': c.trap_lon1,
                'trap_lat2': c.trap_lat2, 'trap_lon2': c.trap_lon2,
            }
            for c in corners
        ] if corners else None
        track_coords = (track.lat, track.lon, track.timezone)

        sf_gate = None
        if track.sf_lat1 is not None:
            sf_gate = {
                'sf_lat1': track.sf_lat1, 'sf_lon1': track.sf_lon1,
                'sf_lat2': track.sf_lat2, 'sf_lon2': track.sf_lon2,
            }

        ingest_session(temp_path, session, track_coords, track_corners, sf_gate=sf_gate)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    user.demo_seeded = True
    db.session.commit()
    logger.info('Demo data seeded for user %s (session %d)', user.email, session.id)
