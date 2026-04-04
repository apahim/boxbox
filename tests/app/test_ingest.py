"""Integration tests for the ingest pipeline.

Uses SQLite in-memory via the TestingConfig. Tests verify that the ingest
pipeline produces correct results by comparing against known-good values
from summary_generated.yaml.
"""

import os

import pytest

from app import db
from app.models import (
    User, Track, TrackCorner, Session, Lap, Telemetry,
    CornerRecord, CornerSummary, SectorTime, ChartData, SessionUpload,
)
from app.sessions.ingest import ingest_session
from tests.app.conftest import seed_test_track


RACE_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'races', '2026-03-08-Kiltorcan')


def _has_test_data():
    return os.path.exists(os.path.join(RACE_DIR, 'telemetry.csv'))


@pytest.fixture
def ingested_session(app):
    """Create a session and run the ingest pipeline on it."""
    with app.app_context():
        # Create user
        user = User(email='test@test.com', display_name='Test')
        user.set_password('test123')
        db.session.add(user)

        track, track_coords, track_corners = seed_test_track()

        # Create session
        from datetime import date
        session = Session(
            user_id=user.id,
            track_id=track.id,
            date=date(2026, 3, 8),
            session_start='14:00',
        )
        db.session.add(session)
        db.session.flush()

        csv_path = os.path.join(RACE_DIR, 'telemetry.csv')
        ingest_session(csv_path, session, track_coords, track_corners)

        yield session


@pytest.fixture
def expected_summary():
    """Load known-good summary values."""
    summary_path = os.path.join(RACE_DIR, 'summary_generated.yaml')
    with open(summary_path) as f:
        return yaml.safe_load(f)


@pytest.mark.skipif(not _has_test_data(), reason='Test data not available')
class TestIngestPipeline:

    def test_lap_count(self, ingested_session, expected_summary):
        assert ingested_session.total_laps == expected_summary['total_laps']

    def test_clean_laps(self, ingested_session, expected_summary):
        assert ingested_session.clean_laps == expected_summary['clean_laps']

    def test_best_lap_time(self, ingested_session, expected_summary):
        assert ingested_session.best_lap_time == expected_summary['best_lap']['time']

    def test_consistency(self, ingested_session, expected_summary):
        assert ingested_session.consistency_pct == expected_summary['consistency_pct']

    def test_top_speed(self, ingested_session, expected_summary):
        assert ingested_session.top_speed_kmh == expected_summary['top_speed_kmh']

    def test_laps_in_db(self, ingested_session, expected_summary):
        laps = Lap.query.filter_by(session_id=ingested_session.id).all()
        assert len(laps) == expected_summary['total_laps']

    def test_outlier_laps(self, ingested_session, expected_summary):
        outliers = Lap.query.filter_by(
            session_id=ingested_session.id, is_outlier=True
        ).all()
        expected_excluded = expected_summary.get('excluded_laps', [])
        assert len(outliers) == len(expected_excluded)

    def test_telemetry_rows(self, ingested_session):
        count = Telemetry.query.filter_by(session_id=ingested_session.id).count()
        assert count == 117020

    def test_corner_records(self, ingested_session):
        records = CornerRecord.query.filter_by(session_id=ingested_session.id).all()
        # 6 corners * ~25 laps (not all laps have all corners)
        assert len(records) > 100

    def test_corner_summaries(self, ingested_session):
        summaries = CornerSummary.query.filter_by(session_id=ingested_session.id).all()
        assert len(summaries) == 6  # 6 corners at Kiltorcan

    def test_sector_times(self, ingested_session):
        sectors = SectorTime.query.filter_by(session_id=ingested_session.id).all()
        assert len(sectors) > 0

    def test_chart_data_overview(self, ingested_session):
        """Verify overview chart types are present."""
        overview_types = [
            'laptime_bar', 'delta_to_best', 'braking_consistency',
            'gg_diagram', 'brake_release', 'corner_analysis',
            'corner_map', 'raceline', 'sector_table', 'lap_list',
        ]
        for chart_type in overview_types:
            charts = ChartData.query.filter_by(
                session_id=ingested_session.id,
                chart_type=chart_type,
            ).all()
            assert len(charts) >= 1, f"Missing chart type: {chart_type}"

    def test_chart_data_per_lap(self, ingested_session, expected_summary):
        """Verify per-lap charts exist for clean laps."""
        clean_laps = expected_summary['clean_laps']
        for chart_type in ['speed_map', 'braking_map', 'throttle_brake']:
            charts = ChartData.query.filter_by(
                session_id=ingested_session.id,
                chart_type=chart_type,
            ).all()
            assert len(charts) == clean_laps, f"{chart_type}: expected {clean_laps}, got {len(charts)}"
        # cumulative_delta may have one fewer (best lap has no delta to itself)
        cum_delta = ChartData.query.filter_by(
            session_id=ingested_session.id,
            chart_type='cumulative_delta',
        ).all()
        assert len(cum_delta) >= clean_laps - 1

    def test_compressed_csv(self, ingested_session):
        upload = SessionUpload.query.filter_by(session_id=ingested_session.id).first()
        assert upload is not None
        assert upload.csv_compressed is not None
        assert len(upload.csv_compressed) > 0

    def test_weather(self, ingested_session, expected_summary):
        assert ingested_session.weather is not None
        assert ingested_session.weather['condition'] == expected_summary['weather']['condition']
        assert ingested_session.weather['temp_c'] == expected_summary['weather']['temp_c']


@pytest.mark.skipif(not _has_test_data(), reason='Test data not available')
class TestSessionRoutes:

    def test_sessions_list(self, client, app):
        with app.app_context():
            user = User(email='test@test.com', display_name='Test')
            user.set_password('test123')
            db.session.add(user)
            db.session.commit()

        # Login
        client.post('/auth/login', data={
            'email': 'test@test.com',
            'password': 'test123',
        })
        resp = client.get('/sessions/')
        assert resp.status_code == 200
        assert b'Sessions' in resp.data

    def test_sessions_create_page(self, client, app):
        with app.app_context():
            user = User(email='test@test.com', display_name='Test')
            user.set_password('test123')
            db.session.add(user)
            db.session.commit()

        client.post('/auth/login', data={
            'email': 'test@test.com',
            'password': 'test123',
        })
        resp = client.get('/sessions/create')
        assert resp.status_code == 200
        assert b'Upload Session' in resp.data
