"""Tests for the API blueprint and dashboard route."""

import os

import pytest
import yaml

from app import db
from app.models import (
    User, Track, TrackCorner, Session, Team, TeamMember, ChartData,
)
from app.sessions.ingest import ingest_session


RACE_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'races', '2026-03-08-Kiltorcan')
TRACKS_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'tracks.yaml')


def _has_test_data():
    return os.path.exists(os.path.join(RACE_DIR, 'telemetry.csv'))


@pytest.fixture
def setup_session(app):
    """Create user, track, and ingested session. Return (user, session)."""
    with app.app_context():
        user = User(email='api@test.com', display_name='API Test')
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

        from datetime import date
        session = Session(user_id=user.id, track_id=track.id, date=date(2026, 3, 8),
                          session_type='Open Sprint', session_start='14:00',
                          kart_number=11, driver_weight_kg=93.9)
        db.session.add(session)
        db.session.flush()

        csv_path = os.path.join(RACE_DIR, 'telemetry.csv')
        ingest_session(csv_path, session, track_coords, track_corners)

        yield user, session


def _login(client, email='api@test.com', password='test123'):
    return client.post('/auth/login', data={'email': email, 'password': password})


@pytest.mark.skipif(not _has_test_data(), reason='Test data not available')
class TestAPI:

    def test_summary_unauthenticated(self, client, setup_session):
        _, session = setup_session
        resp = client.get(f'/api/sessions/{session.id}/summary')
        assert resp.status_code == 401

    def test_summary_authenticated(self, client, setup_session):
        user, session = setup_session
        _login(client)
        resp = client.get(f'/api/sessions/{session.id}/summary')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['total_laps'] == 25
        assert data['best_lap_time'] == 69.731
        assert data['consistency_pct'] == 99.4

    def test_summary_not_found(self, client, setup_session):
        _login(client)
        resp = client.get('/api/sessions/9999/summary')
        assert resp.status_code == 404

    def test_summary_wrong_user(self, client, app, setup_session):
        _, session = setup_session
        with app.app_context():
            other = User(email='other@test.com', display_name='Other')
            other.set_password('test123')
            db.session.add(other)
            db.session.commit()
        _login(client, email='other@test.com')
        resp = client.get(f'/api/sessions/{session.id}/summary')
        assert resp.status_code == 403

    def test_summary_team_member_access(self, client, app, setup_session):
        user, session = setup_session
        with app.app_context():
            team = Team(name='Test Team', slug='test-team', created_by=user.id)
            db.session.add(team)
            db.session.flush()

            session.team_id = team.id
            db.session.add(TeamMember(team_id=team.id, user_id=user.id, role='owner'))

            other = User(email='member@test.com', display_name='Member')
            other.set_password('test123')
            db.session.add(other)
            db.session.flush()
            db.session.add(TeamMember(team_id=team.id, user_id=other.id, role='member'))
            db.session.commit()

        _login(client, email='member@test.com')
        resp = client.get(f'/api/sessions/{session.id}/summary')
        assert resp.status_code == 200

    def test_chart_overview(self, client, setup_session):
        _, session = setup_session
        _login(client)
        for chart_type in ['laptime_bar', 'delta_to_best', 'lap_list']:
            resp = client.get(f'/api/sessions/{session.id}/charts/{chart_type}')
            assert resp.status_code == 200, f'{chart_type} failed'

    def test_chart_per_lap(self, client, setup_session):
        _, session = setup_session
        _login(client)
        resp = client.get(f'/api/sessions/{session.id}/charts/speed_map/13')
        assert resp.status_code == 200

    def test_chart_not_found(self, client, setup_session):
        _, session = setup_session
        _login(client)
        resp = client.get(f'/api/sessions/{session.id}/charts/nonexistent')
        assert resp.status_code == 404

    def test_laps_endpoint(self, client, setup_session):
        _, session = setup_session
        _login(client)
        resp = client.get(f'/api/sessions/{session.id}/laps')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 23  # clean laps

    def test_corners_endpoint(self, client, setup_session):
        _, session = setup_session
        _login(client)
        resp = client.get(f'/api/sessions/{session.id}/corners')
        assert resp.status_code == 200

    def test_corner_map_endpoint(self, client, setup_session):
        _, session = setup_session
        _login(client)
        resp = client.get(f'/api/sessions/{session.id}/corners/map')
        assert resp.status_code == 200

    def test_sectors_endpoint(self, client, setup_session):
        _, session = setup_session
        _login(client)
        resp = client.get(f'/api/sessions/{session.id}/sectors')
        assert resp.status_code == 200

    def test_raceline_endpoint(self, client, setup_session):
        _, session = setup_session
        _login(client)
        resp = client.get(f'/api/sessions/{session.id}/raceline')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'laps' in data


@pytest.mark.skipif(not _has_test_data(), reason='Test data not available')
class TestDashboardRoute:

    def test_dashboard_unauthenticated(self, client, setup_session):
        _, session = setup_session
        resp = client.get(f'/dashboard/{session.id}')
        assert resp.status_code == 302  # redirect to login

    def test_dashboard_authenticated(self, client, setup_session):
        _, session = setup_session
        _login(client)
        resp = client.get(f'/dashboard/{session.id}')
        assert resp.status_code == 200
        assert b'dashboardTabs' in resp.data

    def test_dashboard_not_found(self, client, setup_session):
        _login(client)
        resp = client.get('/dashboard/9999')
        assert resp.status_code == 404

    def test_dashboard_wrong_user(self, client, app, setup_session):
        _, session = setup_session
        with app.app_context():
            other = User(email='other2@test.com', display_name='Other2')
            other.set_password('test123')
            db.session.add(other)
            db.session.commit()
        _login(client, email='other2@test.com')
        resp = client.get(f'/dashboard/{session.id}')
        assert resp.status_code == 403
