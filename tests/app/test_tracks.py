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


class TestTrackDetail:
    def _make_track(self, owner_id=None, name='Test Track'):
        track = Track(slug='test_track', name=name,
                      lat=52.0, lon=-7.0, created_by=owner_id)
        db.session.add(track)
        return track

    def test_owner_can_view_detail(self, app, client):
        with app.app_context():
            user = _make_user('user@test.com')
            db.session.add(user)
            db.session.flush()
            track = self._make_track(owner_id=user.id)
            db.session.commit()

            _login(client, user)
            rv = client.get(f'/tracks/{track.id}')

            assert rv.status_code == 200
            assert b'Test Track' in rv.data
            assert b'Edit Setup' in rv.data

    def test_official_detail_no_edit_button_for_non_admin(self, app, client):
        with app.app_context():
            other = _make_user('other@test.com')
            db.session.add(other)
            db.session.flush()
            track = self._make_track(owner_id=None)
            db.session.commit()

            _login(client, other)
            rv = client.get(f'/tracks/{track.id}')

            assert rv.status_code == 200
            assert b'Edit Setup' not in rv.data
            assert b'Official' in rv.data

    def test_official_detail_shows_edit_for_admin(self, app, client):
        with app.app_context():
            admin = _make_user('admin@test.com', admin=True)
            db.session.add(admin)
            db.session.flush()
            track = self._make_track(owner_id=None)
            db.session.commit()

            _login(client, admin)
            rv = client.get(f'/tracks/{track.id}')

            assert rv.status_code == 200
            assert b'Edit Setup' in rv.data

    def test_other_users_personal_track_404(self, app, client):
        with app.app_context():
            owner = _make_user('owner@test.com')
            other = _make_user('other@test.com')
            db.session.add_all([owner, other])
            db.session.flush()
            track = self._make_track(owner_id=owner.id)
            db.session.commit()

            _login(client, other)
            rv = client.get(f'/tracks/{track.id}')

            assert rv.status_code == 404

    def test_nonexistent_track_404(self, app, client):
        with app.app_context():
            user = _make_user('user@test.com')
            db.session.add(user)
            db.session.commit()

            _login(client, user)
            rv = client.get('/tracks/99999')

            assert rv.status_code == 404

    def test_anonymous_redirected(self, app, client):
        with app.app_context():
            user = _make_user('user@test.com')
            db.session.add(user)
            db.session.flush()
            track = self._make_track(owner_id=user.id)
            db.session.commit()

            rv = client.get(f'/tracks/{track.id}')

            assert rv.status_code == 302

    def test_detail_shows_sessions_and_stats(self, app, client):
        with app.app_context():
            user = _make_user('user@test.com')
            db.session.add(user)
            db.session.flush()
            track = self._make_track(owner_id=user.id)
            db.session.flush()
            db.session.add(Session(user_id=user.id, track_id=track.id,
                                   date=date(2026, 5, 1),
                                   best_lap_time=65.123, total_laps=10,
                                   clean_laps=8, top_speed_kmh=95.5))
            db.session.add(Session(user_id=user.id, track_id=track.id,
                                   date=date(2026, 6, 1),
                                   best_lap_time=61.5, total_laps=12,
                                   clean_laps=10, top_speed_kmh=98.2))
            db.session.commit()

            _login(client, user)
            rv = client.get(f'/tracks/{track.id}')
            html = rv.data.decode()

            assert rv.status_code == 200
            # Aggregates: best lap across sessions
            assert '1:01.500' in html
            assert '<div class="stat-value">2</div>' in html  # session count
            assert '<div class="stat-value">22</div>' in html  # total laps
            assert '<div class="stat-value">98</div>' in html  # top speed rounded
            assert '1 Jun 2026' in html  # last driven
            # Both sessions listed with links to their dashboards
            assert html.count('/dashboard/') == 2
            assert '1 May 2026' in html

    def test_detail_no_sessions_empty_state(self, app, client):
        with app.app_context():
            user = _make_user('user@test.com')
            db.session.add(user)
            db.session.flush()
            track = self._make_track(owner_id=user.id)
            db.session.commit()

            _login(client, user)
            rv = client.get(f'/tracks/{track.id}')

            assert rv.status_code == 200
            assert b'No sessions at this track yet' in rv.data

    def test_detail_sf_gate_and_corner_status(self, app, client):
        with app.app_context():
            user = _make_user('user@test.com')
            db.session.add(user)
            db.session.flush()
            track = self._make_track(owner_id=user.id)
            db.session.flush()
            from app.models import TrackCorner
            db.session.add(TrackCorner(track_id=track.id, name='T1', sort_order=0,
                                       trap_lat1=52.001, trap_lon1=-7.001,
                                       trap_lat2=52.002, trap_lon2=-7.002))
            db.session.commit()

            _login(client, user)
            rv = client.get(f'/tracks/{track.id}')

            assert rv.status_code == 200
            assert b'Not configured' in rv.data  # no S/F gate
            assert b'Configured' not in rv.data

    def test_list_links_to_detail(self, app, client):
        with app.app_context():
            user = _make_user('user@test.com')
            db.session.add(user)
            db.session.flush()
            track = self._make_track(owner_id=user.id)
            db.session.commit()

            _login(client, user)
            rv = client.get('/tracks/')

            assert rv.status_code == 200
            assert f'href="/tracks/{track.id}"'.encode() in rv.data
