"""Tests for the leaderboard feature."""

from datetime import date, datetime, timedelta, timezone

import pytest

from app import db
from app.models import (
    User, Track, Session, Leaderboard, LeaderboardShare,
    format_driver_name, format_laptime,
)


@pytest.fixture
def users(app):
    """Create two users and a track with sessions."""
    with app.app_context():
        now = datetime.now(timezone.utc)
        u1 = User(email='alice@test.com', display_name='Alice Smith',
                   google_id='g-alice', terms_accepted_at=now)
        u2 = User(email='bob@test.com', display_name='Bob Jones',
                   google_id='g-bob', terms_accepted_at=now)
        admin = User(email='admin@test.com', display_name='Admin User',
                     google_id='g-admin', is_admin=True, terms_accepted_at=now)
        db.session.add_all([u1, u2, admin])
        db.session.flush()

        track = Track(slug='test_track', name='Test Track',
                      lat=52.0, lon=-7.0)
        db.session.add(track)
        db.session.flush()

        # Alice: two sessions at the track
        s1 = Session(user_id=u1.id, track_id=track.id,
                     date=date.today() - timedelta(days=5),
                     best_lap_time=65.123, clean_laps=10, total_laps=12,
                     labels=['Dry', 'Race'], data_source='racechrono')
        s2 = Session(user_id=u1.id, track_id=track.id,
                     date=date.today() - timedelta(days=100),
                     best_lap_time=66.500, clean_laps=8, total_laps=10,
                     labels=['Wet'], data_source='racechrono')
        # Bob: one session
        s3 = Session(user_id=u2.id, track_id=track.id,
                     date=date.today() - timedelta(days=10),
                     best_lap_time=64.000, clean_laps=15, total_laps=18,
                     labels=['Dry'], data_source='gopro')
        db.session.add_all([s1, s2, s3])
        db.session.commit()

        yield {'alice': u1, 'bob': u2, 'admin': admin,
               'track': track, 'sessions': [s1, s2, s3]}


def _login(client, app, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)


# ── Model tests ──

class TestFormatDriverName:
    def test_self_returns_full_name(self, app):
        with app.app_context():
            user = User(email='x@x.com', display_name='Amador Pahim',
                        google_id='g-x')
            db.session.add(user)
            db.session.flush()
            assert format_driver_name(user, user.id) == 'Amador Pahim'

    def test_other_returns_first_and_initial(self, app):
        with app.app_context():
            user = User(email='x@x.com', display_name='Amador Pahim',
                        google_id='g-x')
            db.session.add(user)
            db.session.flush()
            assert format_driver_name(user, user.id + 999) == 'Amador P.'

    def test_single_name(self, app):
        with app.app_context():
            user = User(email='x@x.com', display_name='Amador',
                        google_id='g-x')
            db.session.add(user)
            db.session.flush()
            assert format_driver_name(user, user.id + 999) == 'Amador'

    def test_empty_name(self, app):
        with app.app_context():
            user = User(email='x@x.com', display_name='',
                        google_id='g-x')
            db.session.add(user)
            db.session.flush()
            assert format_driver_name(user, user.id + 999) == 'Anonymous'

    def test_multi_part_name(self, app):
        with app.app_context():
            user = User(email='x@x.com', display_name='Jean Pierre Dupont',
                        google_id='g-x')
            db.session.add(user)
            db.session.flush()
            assert format_driver_name(user, user.id + 999) == 'Jean D.'


class TestFormatLaptime:
    def test_formats_seconds(self):
        assert format_laptime(65.123) == '1:05.123'

    def test_formats_sub_minute(self):
        assert format_laptime(45.5) == '0:45.500'

    def test_formats_none(self):
        assert format_laptime(None) == '—'


class TestLeaderboardModel:
    def test_create_leaderboard(self, users):
        lb = Leaderboard(
            name='Test LB', track_id=users['track'].id,
            created_by=users['alice'].id,
        )
        db.session.add(lb)
        db.session.commit()
        assert lb.id is not None
        assert lb.visibility == 'personal'
        assert lb.max_drivers == 10

    def test_share_unique_constraint(self, users):
        lb = Leaderboard(
            name='Test LB', track_id=users['track'].id,
            created_by=users['alice'].id,
        )
        db.session.add(lb)
        db.session.flush()

        s1 = LeaderboardShare(leaderboard_id=lb.id, user_id=users['bob'].id)
        db.session.add(s1)
        db.session.commit()

        s2 = LeaderboardShare(leaderboard_id=lb.id, user_id=users['bob'].id)
        db.session.add(s2)
        with pytest.raises(Exception):
            db.session.commit()
        db.session.rollback()

    def test_cascade_delete(self, users):
        lb = Leaderboard(
            name='Test LB', track_id=users['track'].id,
            created_by=users['alice'].id,
        )
        db.session.add(lb)
        db.session.flush()

        s = LeaderboardShare(leaderboard_id=lb.id, user_id=users['bob'].id)
        db.session.add(s)
        db.session.commit()

        db.session.delete(lb)
        db.session.commit()
        assert LeaderboardShare.query.count() == 0


# ── Access tests ──

class TestLeaderboardAccess:
    def test_personal_only_visible_to_creator(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='Personal', track_id=users['track'].id,
                created_by=users['alice'].id, visibility='personal',
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['bob'])
        resp = client.get(f'/leaderboard/{lb_id}')
        assert resp.status_code == 403

    def test_creator_can_view_personal(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='Personal', track_id=users['track'].id,
                created_by=users['alice'].id, visibility='personal',
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['alice'])
        resp = client.get(f'/leaderboard/{lb_id}')
        assert resp.status_code == 200

    def test_shared_visible_to_shared_user(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='Shared', track_id=users['track'].id,
                created_by=users['alice'].id, visibility='shared',
            )
            db.session.add(lb)
            db.session.flush()
            s = LeaderboardShare(leaderboard_id=lb.id, user_id=users['bob'].id)
            db.session.add(s)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['bob'])
        resp = client.get(f'/leaderboard/{lb_id}')
        assert resp.status_code == 200

    def test_shared_not_visible_to_unshared(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='Shared', track_id=users['track'].id,
                created_by=users['alice'].id, visibility='shared',
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['bob'])
        resp = client.get(f'/leaderboard/{lb_id}')
        assert resp.status_code == 403

    def test_official_visible_to_all(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='Official', track_id=users['track'].id,
                created_by=users['admin'].id, visibility='official',
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['bob'])
        resp = client.get(f'/leaderboard/{lb_id}')
        assert resp.status_code == 200


# ── Results API tests ──

class TestLeaderboardResults:
    def test_results_best_per_driver(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='All Time', track_id=users['track'].id,
                created_by=users['alice'].id, visibility='official',
                period_type='all_time', max_drivers=10,
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id
            bob_session_date = users['sessions'][2].date

        _login(client, app, users['alice'])
        resp = client.get(f'/api/leaderboard/{lb_id}/results')
        assert resp.status_code == 200
        data = resp.get_json()
        results = data['results']

        assert len(results) == 2
        # Bob has the best time (64.000)
        assert results[0]['best_time'] == 64.0
        assert results[0]['position'] == 1
        assert results[0]['gap_fmt'] == ''
        assert results[0]['lap_date'] == bob_session_date.isoformat()
        assert results[0]['lap_date_fmt'] != ''
        # Alice's best is 65.123 (not 66.500)
        assert results[1]['best_time'] == 65.123
        assert results[1]['position'] == 2
        assert results[1]['is_self'] is True
        assert 'lap_date' in results[1]

    def test_results_ordered_asc(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='Test', track_id=users['track'].id,
                created_by=users['alice'].id, visibility='official',
                period_type='all_time',
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['alice'])
        resp = client.get(f'/api/leaderboard/{lb_id}/results')
        results = resp.get_json()['results']
        times = [r['best_time'] for r in results]
        assert times == sorted(times)

    def test_results_limited_to_max_drivers(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='Top 1', track_id=users['track'].id,
                created_by=users['alice'].id, visibility='official',
                period_type='all_time', max_drivers=1,
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['alice'])
        resp = client.get(f'/api/leaderboard/{lb_id}/results')
        results = resp.get_json()['results']
        assert len(results) == 1

    def test_results_period_filter(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='Last 30', track_id=users['track'].id,
                created_by=users['alice'].id, visibility='official',
                period_type='last_30',
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['alice'])
        resp = client.get(f'/api/leaderboard/{lb_id}/results')
        results = resp.get_json()['results']
        # Alice's 100-day-old session (66.500, Wet) should be excluded
        # Only Alice's recent (65.123) and Bob's (64.000) remain
        assert len(results) == 2
        for r in results:
            assert r['best_time'] != 66.5

    def test_results_label_filter(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='Dry Only', track_id=users['track'].id,
                created_by=users['alice'].id, visibility='official',
                period_type='all_time', labels=['Dry'],
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['alice'])
        resp = client.get(f'/api/leaderboard/{lb_id}/results')
        results = resp.get_json()['results']
        # Alice's Dry session: 65.123, Bob's Dry session: 64.000
        # Alice's Wet session (66.5) excluded
        assert len(results) == 2

    def test_results_label_filter_no_match(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='No Match', track_id=users['track'].id,
                created_by=users['alice'].id, visibility='official',
                period_type='all_time', labels=['Nonexistent'],
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['alice'])
        resp = client.get(f'/api/leaderboard/{lb_id}/results')
        results = resp.get_json()['results']
        assert len(results) == 0

    def test_results_gap_calculation(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='Gaps', track_id=users['track'].id,
                created_by=users['alice'].id, visibility='official',
                period_type='all_time',
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['alice'])
        resp = client.get(f'/api/leaderboard/{lb_id}/results')
        results = resp.get_json()['results']
        assert results[0]['gap'] == 0
        assert results[1]['gap'] == pytest.approx(1.123, abs=0.001)

    def test_results_privacy(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='Privacy', track_id=users['track'].id,
                created_by=users['alice'].id, visibility='official',
                period_type='all_time',
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['alice'])
        resp = client.get(f'/api/leaderboard/{lb_id}/results')
        results = resp.get_json()['results']
        # Bob (other user) should show as "Bob J."
        bob_result = [r for r in results if not r['is_self']][0]
        assert bob_result['name'] == 'Bob J.'
        # Alice (self) should show full name
        alice_result = [r for r in results if r['is_self']][0]
        assert alice_result['name'] == 'Alice Smith'

    def test_results_unauthenticated(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='Test', track_id=users['track'].id,
                created_by=users['alice'].id, visibility='official',
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        resp = client.get(f'/api/leaderboard/{lb_id}/results')
        assert resp.status_code == 401

    def test_results_access_denied(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='Personal', track_id=users['track'].id,
                created_by=users['alice'].id, visibility='personal',
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['bob'])
        resp = client.get(f'/api/leaderboard/{lb_id}/results')
        assert resp.status_code == 403

    def test_results_include_source_and_labels(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='Source Check', track_id=users['track'].id,
                created_by=users['alice'].id, visibility='official',
                period_type='all_time',
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['alice'])
        resp = client.get(f'/api/leaderboard/{lb_id}/results')
        results = resp.get_json()['results']
        # Bob is P1 with gopro source
        assert results[0]['source'] == 'gopro'
        assert results[0]['labels'] == ['Dry']
        # Alice is P2 with racechrono source (best lap from s1)
        assert results[1]['source'] == 'racechrono'
        assert 'Dry' in results[1]['labels']
        assert 'Race' in results[1]['labels']

    def test_results_exclude_demo_sessions(self, client, app, users):
        with app.app_context():
            demo = Session(
                user_id=users['bob'].id, track_id=users['track'].id,
                date=date.today() - timedelta(days=1),
                best_lap_time=50.0, clean_laps=5, total_laps=5,
                labels=['Demo'],
            )
            db.session.add(demo)
            lb = Leaderboard(
                name='No Demos', track_id=users['track'].id,
                created_by=users['alice'].id, visibility='official',
                period_type='all_time',
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['alice'])
        resp = client.get(f'/api/leaderboard/{lb_id}/results')
        results = resp.get_json()['results']
        # Bob's demo session (50.0) should be excluded; his real session (64.0) used
        assert results[0]['best_time'] == 64.0


# ── Route tests ──

class TestLeaderboardRoutes:
    def test_list_unauthenticated(self, client):
        resp = client.get('/leaderboard/')
        assert resp.status_code == 302

    def test_list_authenticated(self, client, app, users):
        _login(client, app, users['alice'])
        resp = client.get('/leaderboard/')
        assert resp.status_code == 200
        assert b'Leaderboards' in resp.data

    def test_create_leaderboard(self, client, app, users):
        _login(client, app, users['alice'])
        resp = client.post('/leaderboard/create', data={
            'name': 'My Board',
            'track_id': users['track'].id,
            'labels': '[]',
            'period_type': 'all_time',
            'max_drivers': 5,
        }, follow_redirects=False)
        assert resp.status_code == 302

        with app.app_context():
            lb = Leaderboard.query.filter_by(name='My Board').first()
            assert lb is not None
            assert lb.max_drivers == 5
            assert lb.created_by == users['alice'].id

    def test_delete_own(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='To Delete', track_id=users['track'].id,
                created_by=users['alice'].id,
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['alice'])
        resp = client.post(f'/leaderboard/{lb_id}/delete',
                           headers={'X-Requested-With': 'fetch'})
        assert resp.status_code == 200

        with app.app_context():
            assert db.session.get(Leaderboard, lb_id) is None

    def test_delete_others_forbidden(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='Not Yours', track_id=users['track'].id,
                created_by=users['alice'].id,
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['bob'])
        resp = client.post(f'/leaderboard/{lb_id}/delete',
                           headers={'X-Requested-With': 'fetch'})
        assert resp.status_code == 403

    def test_share(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='Shareable', track_id=users['track'].id,
                created_by=users['alice'].id,
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['alice'])
        resp = client.post(f'/leaderboard/{lb_id}/share',
                           json={'emails': 'bob@test.com'},
                           content_type='application/json')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'bob@test.com' in data['added']

        with app.app_context():
            lb = db.session.get(Leaderboard, lb_id)
            assert lb.visibility == 'shared'
            assert LeaderboardShare.query.filter_by(
                leaderboard_id=lb_id
            ).count() == 1

    def test_publish_non_admin_forbidden(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='Publishable', track_id=users['track'].id,
                created_by=users['alice'].id,
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['alice'])
        resp = client.post(f'/leaderboard/{lb_id}/publish')
        assert resp.status_code == 403

    def test_publish_admin(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='Publishable', track_id=users['track'].id,
                created_by=users['alice'].id,
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['admin'])
        resp = client.post(f'/leaderboard/{lb_id}/publish',
                           headers={'X-Requested-With': 'fetch'})
        assert resp.status_code == 200

        with app.app_context():
            lb = db.session.get(Leaderboard, lb_id)
            assert lb.visibility == 'official'

    def test_unpublish_admin(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='Official LB', track_id=users['track'].id,
                created_by=users['alice'].id, visibility='official',
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['admin'])
        resp = client.post(f'/leaderboard/{lb_id}/unpublish',
                           headers={'X-Requested-With': 'fetch'})
        assert resp.status_code == 200

        with app.app_context():
            lb = db.session.get(Leaderboard, lb_id)
            assert lb.visibility == 'personal'

    def test_unpublish_non_admin_forbidden(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='Official LB', track_id=users['track'].id,
                created_by=users['alice'].id, visibility='official',
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['alice'])
        resp = client.post(f'/leaderboard/{lb_id}/unpublish',
                           headers={'X-Requested-With': 'fetch'})
        assert resp.status_code == 403

    def test_edit_leaderboard(self, client, app, users):
        with app.app_context():
            lb = Leaderboard(
                name='Original', track_id=users['track'].id,
                created_by=users['alice'].id,
            )
            db.session.add(lb)
            db.session.commit()
            lb_id = lb.id

        _login(client, app, users['alice'])
        resp = client.post(f'/leaderboard/{lb_id}/edit', data={
            'name': 'Updated Name',
            'track_id': users['track'].id,
            'labels': '["Dry"]',
            'period_type': 'last_30',
            'max_drivers': 3,
        }, follow_redirects=False)
        assert resp.status_code == 302

        with app.app_context():
            lb = db.session.get(Leaderboard, lb_id)
            assert lb.name == 'Updated Name'
            assert lb.labels == ['Dry']
            assert lb.max_drivers == 3
