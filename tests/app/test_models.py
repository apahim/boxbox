import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import User, Track, TrackCorner


class TestUser:
    def test_user_creation(self, db_session):
        user = User(email='test@test.com', display_name='Test', google_id='g-123')
        db_session.add(user)
        db_session.commit()
        assert user.id is not None
        assert user.email == 'test@test.com'
        assert user.google_id == 'g-123'

    def test_email_unique(self, db_session):
        u1 = User(email='dup@test.com', display_name='A', google_id='g-1')
        db_session.add(u1)
        db_session.commit()

        u2 = User(email='dup@test.com', display_name='B', google_id='g-2')
        db_session.add(u2)
        with pytest.raises(IntegrityError):
            db_session.commit()


class TestTrack:
    def test_track_creation_with_corners(self, db_session):
        track = Track(slug='test_track', name='Test Track', lat=52.0, lon=-7.0)
        db_session.add(track)
        db_session.flush()

        offset = 0.00005
        for i, name in enumerate(['T1', 'T2', 'T3']):
            lat = 52.0 + i * 0.001
            lon = -7.0 + i * 0.001
            corner = TrackCorner(
                track_id=track.id, name=name, sort_order=i,
                trap_lat1=lat + offset, trap_lon1=lon - offset,
                trap_lat2=lat - offset, trap_lon2=lon + offset,
            )
            db_session.add(corner)
        db_session.commit()

        assert track.id is not None
        assert track.corners.count() == 3
        assert track.corners.first().name == 'T1'

    def test_track_slug_unique(self, db_session):
        t1 = Track(slug='dup', name='Track A', lat=52.0, lon=-7.0)
        db_session.add(t1)
        db_session.commit()

        t2 = Track(slug='dup', name='Track B', lat=53.0, lon=-6.0)
        db_session.add(t2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_seed_tracks_cli(self, app):
        runner = app.test_cli_runner()
        result = runner.invoke(args=['seed-tracks', '--file', 'tests/data/tracks.yaml'])
        assert 'Imported "Kiltorcan Raceway"' in result.output
        assert '6 corners' in result.output

        track = Track.query.filter_by(slug='kiltorcan_raceway').first()
        assert track is not None
        assert track.name == 'Kiltorcan Raceway'
        assert track.corners.count() == 6
        assert track.corners.first().name == 'T1'

    def test_seed_tracks_idempotent(self, app):
        runner = app.test_cli_runner()
        runner.invoke(args=['seed-tracks', '--file', 'tests/data/tracks.yaml'])
        result = runner.invoke(args=['seed-tracks', '--file', 'tests/data/tracks.yaml'])
        assert 'Skipping' in result.output
        assert Track.query.count() == 1
