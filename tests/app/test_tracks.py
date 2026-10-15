"""Tests for making tracks official/personal (admin actions)."""

from datetime import date, datetime, timezone

from app import db
from app.models import User, Track, Session, visible_tracks_for_user


def _make_user(email, admin=False):
    return User(
        email=email,
        display_name=email.split('@')[0].title(),
        google_id='g-' + email,
        is_admin=admin,
        terms_accepted_at=datetime.now(timezone.utc),
    )


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)


class TestMakeOfficial:
    def test_admin_makes_own_track_official(self, app, client):
        with app.app_context():
            admin = _make_user('admin@test.com', admin=True)
            db.session.add(admin)
            db.session.flush()
            track = Track(slug='test_track', name='Test Track',
                          lat=52.0, lon=-7.0, created_by=admin.id)
            db.session.add(track)
            db.session.commit()
            track_id = track.id

            _login(client, admin)
            rv = client.post(f'/tracks/{track_id}/make-official')

            assert rv.status_code == 302
            assert db.session.get(Track, track_id).created_by is None

    def test_official_track_visible_to_other_users(self, app, client):
        with app.app_context():
            admin = _make_user('admin@test.com', admin=True)
            other = _make_user('other@test.com')
            db.session.add_all([admin, other])
            db.session.flush()
            track = Track(slug='test_track', name='Test Track',
                          lat=52.0, lon=-7.0, created_by=admin.id)
            db.session.add(track)
            db.session.commit()
            track_id = track.id

            # Not visible to others while personal
            assert track_id not in [t.id for t in visible_tracks_for_user(other.id).all()]

            _login(client, admin)
            client.post(f'/tracks/{track_id}/make-official')

            assert track_id in [t.id for t in visible_tracks_for_user(other.id).all()]

    def test_non_admin_gets_403(self, app, client):
        with app.app_context():
            user = _make_user('user@test.com')
            db.session.add(user)
            db.session.flush()
            track = Track(slug='test_track', name='Test Track',
                          lat=52.0, lon=-7.0, created_by=user.id)
            db.session.add(track)
            db.session.commit()

            _login(client, user)
            rv = client.post(f'/tracks/{track.id}/make-official')

            assert rv.status_code == 403
            assert track.created_by == user.id

    def test_anonymous_redirected(self, app, client):
        with app.app_context():
            user = _make_user('user@test.com')
            db.session.add(user)
            db.session.flush()
            track = Track(slug='test_track', name='Test Track',
                          lat=52.0, lon=-7.0, created_by=user.id)
            db.session.add(track)
            db.session.commit()

            rv = client.post(f'/tracks/{track.id}/make-official')

            assert rv.status_code == 302

    def test_already_official_is_noop(self, app, client):
        with app.app_context():
            admin = _make_user('admin@test.com', admin=True)
            db.session.add(admin)
            db.session.commit()
            track = Track(slug='test_track', name='Test Track',
                          lat=52.0, lon=-7.0, created_by=None)
            db.session.add(track)
            db.session.commit()

            _login(client, admin)
            rv = client.post(f'/tracks/{track.id}/make-official')

            assert rv.status_code == 302
            assert track.created_by is None

    def test_nonexistent_track_404(self, app, client):
        with app.app_context():
            admin = _make_user('admin@test.com', admin=True)
            db.session.add(admin)
            db.session.commit()

            _login(client, admin)
            rv = client.post('/tracks/99999/make-official')

            assert rv.status_code == 404


class TestMakePersonal:
    def test_admin_reverts_official_track(self, app, client):
        with app.app_context():
            admin = _make_user('admin@test.com', admin=True)
            db.session.add(admin)
            db.session.commit()
            track = Track(slug='test_track', name='Test Track',
                          lat=52.0, lon=-7.0, created_by=None)
            db.session.add(track)
            db.session.commit()

            _login(client, admin)
            rv = client.post(f'/tracks/{track.id}/make-personal')

            assert rv.status_code == 302
            assert track.created_by == admin.id

    def test_non_admin_gets_403(self, app, client):
        with app.app_context():
            user = _make_user('user@test.com')
            db.session.add(user)
            db.session.commit()
            track = Track(slug='test_track', name='Test Track',
                          lat=52.0, lon=-7.0, created_by=None)
            db.session.add(track)
            db.session.commit()

            _login(client, user)
            rv = client.post(f'/tracks/{track.id}/make-personal')

            assert rv.status_code == 403
            assert track.created_by is None

    def test_blocked_when_other_users_have_sessions(self, app, client):
        with app.app_context():
            admin = _make_user('admin@test.com', admin=True)
            other = _make_user('other@test.com')
            db.session.add_all([admin, other])
            db.session.flush()
            track = Track(slug='test_track', name='Test Track',
                          lat=52.0, lon=-7.0, created_by=None)
            db.session.add(track)
            db.session.flush()
            db.session.add(Session(user_id=other.id, track_id=track.id,
                                   date=date.today()))
            db.session.commit()

            _login(client, admin)
            rv = client.post(f'/tracks/{track.id}/make-personal')

            # Redirected back with a flash error; track stays official
            assert rv.status_code == 302
            assert track.created_by is None

    def test_fetch_returns_409_when_blocked(self, app, client):
        with app.app_context():
            admin = _make_user('admin@test.com', admin=True)
            other = _make_user('other@test.com')
            db.session.add_all([admin, other])
            db.session.flush()
            track = Track(slug='test_track', name='Test Track',
                          lat=52.0, lon=-7.0, created_by=None)
            db.session.add(track)
            db.session.flush()
            db.session.add(Session(user_id=other.id, track_id=track.id,
                                   date=date.today()))
            db.session.commit()

            _login(client, admin)
            rv = client.post(f'/tracks/{track.id}/make-personal',
                             headers={'X-Requested-With': 'fetch'})

            assert rv.status_code == 409
            assert b'other users' in rv.data
            assert track.created_by is None

    def test_allowed_with_only_own_sessions(self, app, client):
        with app.app_context():
            admin = _make_user('admin@test.com', admin=True)
            db.session.add(admin)
            db.session.flush()
            track = Track(slug='test_track', name='Test Track',
                          lat=52.0, lon=-7.0, created_by=None)
            db.session.add(track)
            db.session.flush()
            db.session.add(Session(user_id=admin.id, track_id=track.id,
                                   date=date.today()))
            db.session.commit()

            _login(client, admin)
            rv = client.post(f'/tracks/{track.id}/make-personal')

            assert rv.status_code == 302
            assert track.created_by == admin.id


class TestOfficialTrackLifecycle:
    def test_official_track_survives_creator_account_deletion(self, app, client):
        with app.app_context():
            admin = _make_user('admin@test.com', admin=True)
            db.session.add(admin)
            db.session.flush()
            track = Track(slug='test_track', name='Test Track',
                          lat=52.0, lon=-7.0, created_by=admin.id)
            db.session.add(track)
            db.session.commit()
            track_id = track.id

            _login(client, admin)
            client.post(f'/tracks/{track_id}/make-official')
            rv = client.post('/auth/profile/delete')

            assert rv.status_code == 302
            assert db.session.get(Track, track_id) is not None
            assert db.session.get(Track, track_id).created_by is None
