"""Tests for the API blueprint and dashboard route."""

import os
from datetime import date

import pytest

from app import db
from app.models import User, Track, TrackCorner, Session, ChartData
from app.sessions.ingest import ingest_session
from tests.app.conftest import seed_test_track


RACE_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'races', '2026-03-08-Kiltorcan')


def _has_test_data():
    return os.path.exists(os.path.join(RACE_DIR, 'telemetry.csv'))


@pytest.fixture
def setup_session(app):
    """Create user, track, and ingested session. Return (user, session)."""
    with app.app_context():
        user = User(email='api@test.com', display_name='API Test')
        user.set_password('test123')
        db.session.add(user)

        track, track_coords, track_corners = seed_test_track()

        from datetime import date
        session = Session(user_id=user.id, track_id=track.id, date=date(2026, 3, 8),
                          session_start='14:00')
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


class TestTrackSessionsAPI:
    """Regression tests for cross-session raceline comparison endpoints.

    These endpoints were removed with the Evolution page and need to exist
    for the Racing Line A/B comparison to work across sessions.
    """

    @pytest.fixture
    def seed_sessions(self, app, client):
        """Create user, two tracks, and sessions with raceline chart data."""
        from datetime import datetime, timezone

        with app.app_context():
            user = User(email='evo@test.com', display_name='Evo Test',
                        google_id='g_evo',
                        terms_accepted_at=datetime.now(timezone.utc))
            db.session.add(user)
            db.session.flush()

            track_a = Track(slug='track_a', name='Track A', lat=52.0, lon=-7.0)
            track_b = Track(slug='track_b', name='Track B', lat=53.0, lon=-6.0)
            db.session.add_all([track_a, track_b])
            db.session.flush()

            s1 = Session(user_id=user.id, track_id=track_a.id, date=date(2026, 4, 1))
            s2 = Session(user_id=user.id, track_id=track_a.id, date=date(2026, 4, 5))
            s3 = Session(user_id=user.id, track_id=track_b.id, date=date(2026, 4, 3))
            db.session.add_all([s1, s2, s3])
            db.session.flush()

            # Add raceline chart data for s1 and s2
            fake_laps = [{'lap': 1, 'time_fmt': '1:02.000', 'seconds': 62.0,
                          'is_best': True, 'is_outlier': False,
                          'lat': [52.0, 52.001], 'lon': [-7.0, -7.001], 't': [0, 1]}]
            for s in [s1, s2]:
                db.session.add(ChartData(
                    session_id=s.id, chart_type='raceline', chart_key='overview',
                    data={'laps': fake_laps}
                ))

            db.session.commit()
            yield user, track_a, track_b, s1, s2, s3

    def _auth(self, client, user_id):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)

    def test_track_sessions_returns_matching_sessions(self, client, seed_sessions):
        user, track_a, track_b, s1, s2, s3 = seed_sessions
        self._auth(client, user.id)

        resp = client.get(f'/api/tracks/{track_a.id}/sessions')
        assert resp.status_code == 200
        data = resp.get_json()
        ids = [s['id'] for s in data]
        assert s1.id in ids
        assert s2.id in ids
        assert s3.id not in ids  # different track
        assert all('date' in s and 'labels' in s for s in data)

    def test_track_sessions_unauthenticated(self, client, seed_sessions):
        _, track_a, *_ = seed_sessions
        resp = client.get(f'/api/tracks/{track_a.id}/sessions')
        assert resp.status_code == 401

    def test_track_sessions_filters_by_user(self, client, app, seed_sessions):
        from datetime import datetime, timezone
        _, track_a, _, s1, s2, _ = seed_sessions
        with app.app_context():
            other = User(email='other_evo@test.com', display_name='Other',
                         google_id='g_other_evo',
                         terms_accepted_at=datetime.now(timezone.utc))
            db.session.add(other)
            db.session.commit()
            self._auth(client, other.id)
        resp = client.get(f'/api/tracks/{track_a.id}/sessions')
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_sessions_raceline_returns_lap_data(self, client, seed_sessions):
        user, _, _, s1, s2, _ = seed_sessions
        self._auth(client, user.id)

        resp = client.get(f'/api/sessions/raceline?session_ids={s1.id},{s2.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        sessions = data['sessions']
        assert len(sessions) == 2
        for s in sessions:
            assert 'laps' in s
            assert 'date' in s
            assert len(s['laps']) > 0

    def test_sessions_raceline_filters_by_user(self, client, app, seed_sessions):
        from datetime import datetime, timezone
        _, _, _, s1, s2, _ = seed_sessions
        with app.app_context():
            other = User(email='other_evo2@test.com', display_name='Other2',
                         google_id='g_other_evo2',
                         terms_accepted_at=datetime.now(timezone.utc))
            db.session.add(other)
            db.session.commit()
            self._auth(client, other.id)
        resp = client.get(f'/api/sessions/raceline?session_ids={s1.id},{s2.id}')
        assert resp.status_code == 200
        assert resp.get_json()['sessions'] == []

    def test_sessions_raceline_unauthenticated(self, client, seed_sessions):
        _, _, _, s1, s2, _ = seed_sessions
        resp = client.get(f'/api/sessions/raceline?session_ids={s1.id},{s2.id}')
        assert resp.status_code == 401


class TestShareToken:
    """Regression tests for share token access to API endpoints.

    Share tokens must grant read-only access to session data without login.
    Previously broke due to naive/aware datetime comparison (a4becc5).
    """

    @pytest.fixture
    def shared_session(self, app):
        """Create a user, track, session with share token and chart data."""
        from datetime import datetime, timezone

        with app.app_context():
            user = User(email='share@test.com', display_name='Share Test',
                        google_id='g_share',
                        terms_accepted_at=datetime.now(timezone.utc))
            db.session.add(user)
            db.session.flush()

            track = Track(slug='share_track', name='Share Track', lat=52.0, lon=-7.0)
            db.session.add(track)
            db.session.flush()

            session = Session(
                user_id=user.id, track_id=track.id, date=date(2026, 4, 1),
                total_laps=10, clean_laps=9, best_lap_time=65.0,
                average_time=66.5, median_time=66.0, std_dev=1.0,
                consistency_pct=98.5,
                share_token='test_share_token_abc',
                share_token_created_at=datetime.now(timezone.utc),
            )
            db.session.add(session)
            db.session.flush()

            # Add chart data for each type the dashboard loads
            for chart_type, chart_key in [
                ('laptime_bar', 'overview'),
                ('delta_to_best', 'overview'),
                ('sector_table', 'overview'),
                ('lap_list', 'overview'),
                ('raceline', 'overview'),
            ]:
                db.session.add(ChartData(
                    session_id=session.id, chart_type=chart_type,
                    chart_key=chart_key, data={'test': True}
                ))

            db.session.commit()
            yield session

    def test_summary_with_share_token(self, client, shared_session):
        resp = client.get(
            f'/api/sessions/{shared_session.id}/summary'
            f'?share_token={shared_session.share_token}'
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['best_lap_time'] == 65.0

    def test_charts_with_share_token(self, client, shared_session):
        for chart_type in ['laptime_bar', 'delta_to_best']:
            resp = client.get(
                f'/api/sessions/{shared_session.id}/charts/{chart_type}'
                f'?share_token={shared_session.share_token}'
            )
            assert resp.status_code == 200, f'{chart_type} failed'

    def test_laps_with_share_token(self, client, shared_session):
        resp = client.get(
            f'/api/sessions/{shared_session.id}/laps'
            f'?share_token={shared_session.share_token}'
        )
        assert resp.status_code == 200

    def test_sectors_with_share_token(self, client, shared_session):
        resp = client.get(
            f'/api/sessions/{shared_session.id}/sectors'
            f'?share_token={shared_session.share_token}'
        )
        assert resp.status_code == 200

    def test_raceline_with_share_token(self, client, shared_session):
        resp = client.get(
            f'/api/sessions/{shared_session.id}/raceline'
            f'?share_token={shared_session.share_token}'
        )
        assert resp.status_code == 200

    def test_invalid_share_token(self, client, shared_session):
        resp = client.get(
            f'/api/sessions/{shared_session.id}/summary'
            f'?share_token=invalid_token'
        )
        assert resp.status_code == 401

    def test_expired_share_token(self, client, app, shared_session):
        from datetime import datetime, timezone, timedelta
        session = db.session.get(Session, shared_session.id)
        session.share_token_created_at = datetime.now(timezone.utc) - timedelta(days=31)
        db.session.commit()

        resp = client.get(
            f'/api/sessions/{shared_session.id}/summary'
            f'?share_token={shared_session.share_token}'
        )
        assert resp.status_code == 401

    def test_share_token_wrong_session(self, client, shared_session):
        """Share token for session A must not grant access to session B."""
        other = Session(
            user_id=shared_session.user_id, date=date(2026, 4, 2),
            total_laps=5,
        )
        db.session.add(other)
        db.session.commit()

        resp = client.get(
            f'/api/sessions/{other.id}/summary'
            f'?share_token={shared_session.share_token}'
        )
        assert resp.status_code == 401

    def test_share_token_naive_datetime(self, client, shared_session):
        """Regression: naive datetime in share_token_created_at must not crash.

        The DB may return a naive datetime even if stored as tz-aware.
        The decorator must handle both without TypeError.
        """
        from datetime import datetime
        session = db.session.get(Session, shared_session.id)
        # Simulate DB returning a naive datetime (no tzinfo)
        session.share_token_created_at = datetime(2026, 4, 1, 12, 0, 0)
        db.session.commit()

        resp = client.get(
            f'/api/sessions/{shared_session.id}/summary'
            f'?share_token={shared_session.share_token}'
        )
        assert resp.status_code == 200

    def test_null_timestamp_rejected(self, client, shared_session):
        """Token with no created_at timestamp should be treated as expired."""
        session = db.session.get(Session, shared_session.id)
        session.share_token_created_at = None
        db.session.commit()

        resp = client.get(
            f'/api/sessions/{shared_session.id}/summary'
            f'?share_token={shared_session.share_token}'
        )
        assert resp.status_code == 401

    def test_shared_view_valid_token(self, client, shared_session):
        """Shared view renders the dashboard for valid, non-expired tokens."""
        resp = client.get(f'/dashboard/share/{shared_session.share_token}')
        assert resp.status_code == 200
        assert b'dashboardTabs' in resp.data
        assert b'data-share-token' in resp.data

    def test_shared_view_expired_token(self, client, shared_session):
        """Shared view shows expiry error instead of empty dashboard."""
        from datetime import datetime, timezone, timedelta
        session = db.session.get(Session, shared_session.id)
        session.share_token_created_at = datetime.now(timezone.utc) - timedelta(days=31)
        db.session.commit()

        resp = client.get(f'/dashboard/share/{shared_session.share_token}')
        assert resp.status_code == 410
        assert b'expired' in resp.data.lower()
        assert b'dashboardTabs' not in resp.data

    def test_shared_view_invalid_token(self, client):
        """Shared view returns 404 for non-existent tokens."""
        resp = client.get('/dashboard/share/nonexistent_token')
        assert resp.status_code == 404

    def test_shared_view_null_timestamp(self, client, shared_session):
        """Shared view treats null timestamp as expired."""
        session = db.session.get(Session, shared_session.id)
        session.share_token_created_at = None
        db.session.commit()

        resp = client.get(f'/dashboard/share/{shared_session.share_token}')
        assert resp.status_code == 410
