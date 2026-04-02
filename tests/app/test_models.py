import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import User, Team, TeamMember, Track, TrackCorner


class TestUser:
    def test_set_and_check_password(self, app):
        user = User(email='test@test.com', display_name='Test')
        user.set_password('secret123')
        assert user.check_password('secret123')
        assert not user.check_password('wrong')

    def test_email_unique(self, db_session):
        u1 = User(email='dup@test.com', display_name='A')
        u1.set_password('pass')
        db_session.add(u1)
        db_session.commit()

        u2 = User(email='dup@test.com', display_name='B')
        u2.set_password('pass')
        db_session.add(u2)
        with pytest.raises(IntegrityError):
            db_session.commit()


class TestTeam:
    def _make_user(self, session, email='owner@test.com'):
        user = User(email=email, display_name='Owner')
        user.set_password('pass')
        session.add(user)
        session.commit()
        return user

    def test_team_creation(self, db_session):
        user = self._make_user(db_session)
        team = Team(name='Speed Demons', slug='speed-demons', created_by=user.id)
        db_session.add(team)
        db_session.commit()

        assert team.id is not None
        assert team.slug == 'speed-demons'

    def test_team_member_owner(self, db_session):
        user = self._make_user(db_session)
        team = Team(name='Test Team', slug='test-team', created_by=user.id)
        db_session.add(team)
        db_session.flush()

        member = TeamMember(team_id=team.id, user_id=user.id, role='owner')
        db_session.add(member)
        db_session.commit()

        assert team.members.count() == 1
        assert team.members.first().role == 'owner'

    def test_team_member_unique_constraint(self, db_session):
        user = self._make_user(db_session)
        team = Team(name='Test', slug='test', created_by=user.id)
        db_session.add(team)
        db_session.flush()

        m1 = TeamMember(team_id=team.id, user_id=user.id, role='owner')
        db_session.add(m1)
        db_session.commit()

        m2 = TeamMember(team_id=team.id, user_id=user.id, role='member')
        db_session.add(m2)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_add_member(self, db_session):
        owner = self._make_user(db_session, 'owner@test.com')
        member_user = self._make_user(db_session, 'member@test.com')

        team = Team(name='Test', slug='test', created_by=owner.id)
        db_session.add(team)
        db_session.flush()

        db_session.add(TeamMember(team_id=team.id, user_id=owner.id, role='owner'))
        db_session.add(TeamMember(team_id=team.id, user_id=member_user.id, role='member'))
        db_session.commit()

        assert team.members.count() == 2


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
        result = runner.invoke(args=['seed-tracks', '--file', 'data/tracks.yaml'])
        assert 'Imported "Kiltorcan Raceway"' in result.output
        assert '6 corners' in result.output

        track = Track.query.filter_by(slug='kiltorcan_raceway').first()
        assert track is not None
        assert track.name == 'Kiltorcan Raceway'
        assert track.corners.count() == 6
        assert track.corners.first().name == 'T1'

    def test_seed_tracks_idempotent(self, app):
        runner = app.test_cli_runner()
        runner.invoke(args=['seed-tracks', '--file', 'data/tracks.yaml'])
        result = runner.invoke(args=['seed-tracks', '--file', 'data/tracks.yaml'])
        assert 'Skipping' in result.output
        assert Track.query.count() == 1
