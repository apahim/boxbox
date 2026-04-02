"""Tests for the evolution API endpoints."""

import os
from datetime import date

import pytest
import yaml

from app import db
from app.models import (
    User, Track, TrackCorner, Session, Team, TeamMember,
)
from app.sessions.ingest import ingest_session


DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')
RACE_DIRS = [
    os.path.join(DATA_DIR, 'races', '2026-02-27-Kiltorcan'),
    os.path.join(DATA_DIR, 'races', '2026-03-07-Kiltorcan'),
    os.path.join(DATA_DIR, 'races', '2026-03-08-Kiltorcan'),
]
TRACKS_FILE = os.path.join(DATA_DIR, 'tracks.yaml')


def _has_all_data():
    return all(os.path.exists(os.path.join(d, 'telemetry.csv')) for d in RACE_DIRS)


@pytest.fixture
def three_sessions(app):
    """Create 3 sessions at Kiltorcan for evolution testing."""
    with app.app_context():
        user = User(email='evo@test.com', display_name='Evo Test')
        user.set_password('test123')
        db.session.add(user)

        with open(TRACKS_FILE) as f:
            tracks_data = yaml.safe_load(f)
        td = tracks_data['kiltorcan_raceway']
        track = Track(slug='kiltorcan_raceway', name=td['name'],
                      lat=td['lat'], lon=td['lon'], timezone=td.get('timezone', 'UTC'))
        db.session.add(track)
        db.session.flush()

        offset = 0.00005
        for i, c in enumerate(td.get('corners', [])):
            db.session.add(TrackCorner(
                track_id=track.id, name=c['name'], sort_order=i,
                trap_lat1=c['lat'] + offset, trap_lon1=c['lon'] - offset,
                trap_lat2=c['lat'] - offset, trap_lon2=c['lon'] + offset,
            ))
        db.session.flush()

        corners = TrackCorner.query.filter_by(track_id=track.id).order_by(TrackCorner.sort_order).all()
        track_corners = [
            {
                'name': c.name, 'lat': c.lat, 'lon': c.lon,
                'trap_lat1': c.trap_lat1, 'trap_lon1': c.trap_lon1,
                'trap_lat2': c.trap_lat2, 'trap_lon2': c.trap_lon2,
            }
            for c in corners
        ]
        track_coords = (track.lat, track.lon, track.timezone)

        dates = [date(2026, 2, 27), date(2026, 3, 7), date(2026, 3, 8)]
        sessions = []
        for i, (race_dir, d) in enumerate(zip(RACE_DIRS, dates)):
            meta_path = os.path.join(race_dir, 'race.yaml')
            with open(meta_path) as f:
                meta = yaml.safe_load(f) or {}

            session = Session(
                user_id=user.id, track_id=track.id, date=d,
                session_type=meta.get('session_type'),
                session_start=meta.get('session_start'),
                kart_number=meta.get('kart_number'),
                driver_weight_kg=meta.get('driver_weight_kg'),
            )
            db.session.add(session)
            db.session.flush()

            csv_path = os.path.join(race_dir, 'telemetry.csv')
            ingest_session(csv_path, session, track_coords, track_corners)
            sessions.append(session)

        yield user, track, sessions


def _login(client, email='evo@test.com', password='test123'):
    client.post('/auth/login', data={'email': email, 'password': password})


@pytest.mark.skipif(not _has_all_data(), reason='Test data not available')
class TestEvolutionAPI:

    def test_trends_returns_3_sessions(self, client, three_sessions):
        user, track, sessions = three_sessions
        _login(client)
        resp = client.get(f'/api/evolution?track_id={track.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 3

    def test_trends_ordered_by_date(self, client, three_sessions):
        user, track, sessions = three_sessions
        _login(client)
        resp = client.get(f'/api/evolution?track_id={track.id}')
        data = resp.get_json()
        dates = [d['date'] for d in data]
        assert dates == sorted(dates)

    def test_trends_has_expected_fields(self, client, three_sessions):
        user, track, sessions = three_sessions
        _login(client)
        resp = client.get(f'/api/evolution?track_id={track.id}')
        data = resp.get_json()
        entry = data[0]
        for field in ['id', 'date', 'best_lap_time', 'average_time', 'consistency_pct', 'total_laps']:
            assert field in entry, f'Missing field: {field}'

    def test_trends_unauthenticated(self, client, three_sessions):
        resp = client.get('/api/evolution')
        assert resp.status_code == 401

    def test_corners_returns_6_corners(self, client, three_sessions):
        user, track, sessions = three_sessions
        _login(client)
        resp = client.get(f'/api/evolution/corners?track_id={track.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 6  # 6 corners at Kiltorcan

    def test_corners_each_has_3_sessions(self, client, three_sessions):
        user, track, sessions = three_sessions
        _login(client)
        resp = client.get(f'/api/evolution/corners?track_id={track.id}')
        data = resp.get_json()
        for corner in data:
            assert len(corner['sessions']) == 3, f'{corner["corner_name"]} has {len(corner["sessions"])} sessions'

    def test_corners_requires_track_id(self, client, three_sessions):
        _login(client)
        resp = client.get('/api/evolution/corners')
        assert resp.status_code == 400

    def test_raceline_cross_session(self, client, three_sessions):
        user, track, sessions = three_sessions
        _login(client)
        ids = ','.join(str(s.id) for s in sessions)
        resp = client.get(f'/api/evolution/raceline?session_ids={ids}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data['sessions']) == 3

    def test_raceline_requires_session_ids(self, client, three_sessions):
        _login(client)
        resp = client.get('/api/evolution/raceline')
        assert resp.status_code == 400

    def test_tracks_endpoint(self, client, three_sessions):
        _login(client)
        resp = client.get('/api/tracks')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) >= 1
        assert data[0]['name'] == 'Kiltorcan Raceway'

    def test_empty_track(self, client, app, three_sessions):
        _login(client)
        # Query for a track_id that has no sessions
        resp = client.get('/api/evolution?track_id=9999')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == []


@pytest.mark.skipif(not _has_all_data(), reason='Test data not available')
class TestEvolutionPage:

    def test_evolution_page_loads(self, client, three_sessions):
        _login(client)
        resp = client.get('/dashboard/evolution')
        assert resp.status_code == 200
        assert b'Evolution' in resp.data
        assert b'trackSelect' in resp.data

    def test_evolution_unauthenticated(self, client, three_sessions):
        resp = client.get('/dashboard/evolution')
        assert resp.status_code == 302  # redirect to login
