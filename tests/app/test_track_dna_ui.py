"""Tests for the Track DNA UI layer: the reference-lap trajectory
block, the admin picker endpoints, the admin compute trigger, the API
endpoints (official-tracks-only) and the track-detail section shell."""

from app import db
from app.models import Session, TrackDnaCard, Track as TrackModel, User

from tests.app.track_dna_helpers import (
    _login,
    make_track,
    make_user,
    seed_dna_session,
)


_seed_counter = [0]


def _seed_official(name='Test Circuit', laps=2, **kwargs):
    """Admin + official track + one seeded session (no reference yet).
    Each call gets a distinct admin user (unique email/google_id)."""
    _seed_counter[0] += 1
    admin = make_user(admin=True,
                      email=f'driver{_seed_counter[0]}@test.com')
    track = make_track(name=name)               # created_by=None: official
    session = seed_dna_session(track, admin, laps=laps, **kwargs)
    return admin, track, session


def _set_reference(track, session, lap_number=1):
    track.reference_session_id = session.id
    track.reference_lap_number = lap_number
    db.session.commit()


# ---- trajectory block ------------------------------------------------


def test_trajectory_block_shape(app):
    with app.app_context():
        _admin, track, session = _seed_official()
        _set_reference(track, session)
        from app.track_dna.cards import build_card

        card, result = build_card(track.id)
        assert card is not None
        traj = result['trajectory']
        assert traj is not None
        assert traj['n_points'] == len(traj['points'])
        assert 8 <= traj['n_points'] <= 300
        assert traj['length_m'] > 0

        points = traj['points']
        # s monotone from 0; points are [s, lat, lon]
        assert points[0][0] == 0.0
        assert all(points[i][0] < points[i + 1][0]
                   for i in range(len(points) - 1))
        assert points[-1][0] < traj['length_m'] + 0.1

        # bbox sanity: the whole loop sits within ~2 km of the datum
        for _s, lat, lon in points:
            assert abs(lat - track.lat) < 0.02
            assert abs(lon - track.lon) < 0.02


def test_trajectory_projection_round_trip(app):
    """The trajectory inverts the loader's projection: projecting its
    lat/lon back about the track datum lands inside the seed capsule's
    metre bbox, and the loop closes (last point near the first)."""
    with app.app_context():
        _admin, track, session = _seed_official()
        _set_reference(track, session)
        from scripts.analysis.utils import project_to_meters

        from app.track_dna.cards import build_card

        traj = build_card(track.id)[1]['trajectory']
        lats = [p[1] for p in traj['points']]
        lons = [p[2] for p in traj['points']]
        x, y = project_to_meters(lats, lons,
                                 center=(track.lat, track.lon))
        # capsule: straight 80 m + radius 40 m -> bbox x [-40, 120],
        # y [-80, 0]; allow margin for the median line and rounding
        assert -60.0 <= float(x.min()) and float(x.max()) <= 140.0
        assert -90.0 <= float(y.min()) and float(y.max()) <= 10.0

        # closed loop: first and last points coincide within a few
        # metres (one grid step + rounding)
        first, last = traj['points'][0], traj['points'][-1]
        dlat = (last[1] - first[1]) * 110540.0
        dlon = (last[2] - first[2]) * 111320.0
        assert (dlat ** 2 + dlon ** 2) ** 0.5 < 10.0


def test_trajectory_decimation_cap(app, monkeypatch):
    with app.app_context():
        _admin, track, session = _seed_official()
        _set_reference(track, session)
        monkeypatch.setattr('app.track_dna.cards.'
                            'MAX_TRAJECTORY_POINTS', 10)
        from app.track_dna.cards import build_card

        traj = build_card(track.id)[1]['trajectory']
        assert traj['n_points'] <= 10
        assert len(traj['points']) <= 10


# ---- admin picker endpoints -------------------------------------------


def test_reference_lap_laps_requires_admin(app, client):
    with app.app_context():
        owner = make_user()
        track = make_track(created_by=owner.id)
        session = seed_dna_session(track, owner)
        db.session.commit()
        track_id, session_id, owner_id = track.id, session.id, owner.id

    _login(client, owner_id)
    resp = client.get(f'/tracks/{track_id}/reference-lap/laps'
                      f'?session_id={session_id}')
    assert resp.status_code == 403


def test_reference_lap_laps_official_only(app, client):
    with app.app_context():
        admin = make_user(admin=True)
        owner = make_user(email='owner@test.com')
        track = make_track(created_by=owner.id)    # personal
        session = seed_dna_session(track, owner)
        db.session.commit()
        track_id, session_id, admin_id = track.id, session.id, admin.id

    _login(client, admin_id)
    resp = client.get(f'/tracks/{track_id}/reference-lap/laps'
                      f'?session_id={session_id}')
    assert resp.status_code == 404


def test_reference_lap_laps_lists_clean_laps(app, client):
    with app.app_context():
        admin, track, session = _seed_official(laps=3)
        db.session.commit()
        track_id, session_id, admin_id = track.id, session.id, admin.id

    _login(client, admin_id)
    resp = client.get(f'/tracks/{track_id}/reference-lap/laps'
                      f'?session_id={session_id}')
    assert resp.status_code == 200
    laps = resp.get_json()['laps']
    assert [lap['lap'] for lap in laps] == [1, 2, 3]
    best = min(lap['seconds'] for lap in laps)
    assert [lap for lap in laps if lap['is_best']] == \
        [lap for lap in laps if lap['seconds'] == best]


def test_reference_lap_laps_session_must_be_on_track(app, client):
    with app.app_context():
        admin, track, _session = _seed_official()
        _other, track2, session2 = _seed_official(name='Other')
        db.session.commit()
        track_id, session2_id, admin_id = track.id, session2.id, admin.id

    _login(client, admin_id)
    resp = client.get(f'/tracks/{track_id}/reference-lap/laps'
                      f'?session_id={session2_id}')
    assert resp.status_code == 404


def test_set_reference_lap_validates_before_storing(app, client):
    with app.app_context():
        admin, track, session = _seed_official()
        db.session.commit()
        track_id, session_id, admin_id = track.id, session.id, admin.id

    _login(client, admin_id)
    # lap 99 does not exist -> rejected, nothing stored
    resp = client.post(f'/tracks/{track_id}/reference-lap',
                       json={'session_id': session_id, 'lap_number': 99})
    assert resp.status_code == 400
    assert 'lap 99' in resp.get_json()['error']

    with app.app_context():
        track = db.session.get(TrackModel, track_id)
        assert track.reference_session_id is None

    # lap 1 -> stored + card computed
    resp = client.post(f'/tracks/{track_id}/reference-lap',
                       json={'session_id': session_id, 'lap_number': 1})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['ok'] is True
    assert data['overall_score'] is not None

    with app.app_context():
        track = db.session.get(TrackModel, track_id)
        assert track.reference_session_id == session_id
        assert track.reference_lap_number == 1
        assert TrackDnaCard.query.filter_by(track_id=track_id).count() == 1


def test_set_reference_lap_requires_admin_and_official(app, client):
    with app.app_context():
        admin, track, session = _seed_official()
        owner = make_user(email='owner@test.com')
        db.session.commit()
        ids = (track.id, session.id, admin.id, owner.id)

    # non-admin
    _login(client, ids[3])
    resp = client.post(f'/tracks/{ids[0]}/reference-lap',
                       json={'session_id': ids[1], 'lap_number': 1})
    assert resp.status_code == 403

    # admin but personal track
    with app.app_context():
        owner = db.session.get(User, ids[3])
        personal = make_track(name='Personal', created_by=owner.id)
        p_session = seed_dna_session(personal, owner)
        db.session.commit()
        p_ids = (personal.id, p_session.id)

    _login(client, ids[2])
    resp = client.post(f'/tracks/{p_ids[0]}/reference-lap',
                       json={'session_id': p_ids[1], 'lap_number': 1})
    assert resp.status_code == 404


# ---- admin trigger ------------------------------------------------------


def test_admin_trigger_requires_admin(app, client):
    with app.app_context():
        _admin, track, _session = _seed_official()
        owner = make_user(email='owner@test.com')
        db.session.commit()
        track_id, owner_id = track.id, owner.id

    _login(client, owner_id)
    resp = client.post(f'/admin/tracks/{track_id}/compute-dna')
    assert resp.status_code == 403


def test_admin_trigger_unknown_track_404(app, client):
    with app.app_context():
        admin = make_user(email='admin@test.com', admin=True)
        db.session.commit()
        admin_id = admin.id

    _login(client, admin_id)
    resp = client.post('/admin/tracks/99999/compute-dna')
    assert resp.status_code == 404


def test_admin_trigger_computes_and_flashes(app, client):
    with app.app_context():
        admin, track, session = _seed_official()
        _set_reference(track, session)
        db.session.commit()
        track_id, admin_id = track.id, admin.id

    _login(client, admin_id)
    resp = client.post(f'/admin/tracks/{track_id}/compute-dna',
                       follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'overall' in body

    with app.app_context():
        cards = TrackDnaCard.query.filter_by(track_id=track_id).all()
        assert len(cards) == 1
        assert cards[0].overall_score is not None
        assert cards[0].support_json['trajectory'] is not None


def test_admin_trigger_no_reference_flashes_warning(app, client):
    with app.app_context():
        _admin, track, _session = _seed_official()
        admin = make_user(email='admin2@test.com', admin=True)
        db.session.commit()
        track_id, admin_id = track.id, admin.id

    _login(client, admin_id)
    resp = client.post(f'/admin/tracks/{track_id}/compute-dna',
                       follow_redirects=True)
    assert resp.status_code == 200
    assert 'no reference lap' in resp.get_data(as_text=True)


def test_admin_dashboard_shows_reference_state(app, client):
    with app.app_context():
        admin, track, session = _seed_official()
        _set_reference(track, session)
        from app.track_dna.cards import build_card

        assert build_card(track.id)[0] is not None
        db.session.commit()
        track_id, admin_id = track.id, admin.id

    _login(client, admin_id)
    resp = client.get('/admin/')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Track DNA' in body
    assert 'valid' in body

    # break the reference (a re-ingest renumbered the laps away) ->
    # the dashboard shows the broken badge
    with app.app_context():
        track = db.session.get(TrackModel, track_id)
        track.reference_lap_number = 99
        db.session.commit()

    resp = client.get('/admin/')
    body = resp.get_data(as_text=True)
    assert 'broken' in body


# ---- API endpoints -------------------------------------------------------


def test_api_dna_requires_auth(app, client):
    with app.app_context():
        _admin, track, _session = _seed_official()
        db.session.commit()
        track_id = track.id

    resp = client.get(f'/api/tracks/{track_id}/dna')
    assert resp.status_code == 401


def test_api_dna_official_only(app, client):
    with app.app_context():
        owner = make_user()
        track = make_track(created_by=owner.id)    # personal
        db.session.commit()
        track_id, owner_id = track.id, owner.id

    _login(client, owner_id)
    resp = client.get(f'/api/tracks/{track_id}/dna')
    assert resp.status_code == 404
    resp = client.get(f'/api/tracks/{track_id}/dna/similar')
    assert resp.status_code == 404


def test_api_dna_card_lifecycle(app, client):
    with app.app_context():
        admin, track, session = _seed_official()
        db.session.commit()
        track_id, admin_id = track.id, admin.id

    _login(client, admin_id)
    # no card yet -> card None (the UI section stays hidden)
    resp = client.get(f'/api/tracks/{track_id}/dna')
    assert resp.status_code == 200
    assert resp.get_json()['card'] is None

    # set the reference through the picker endpoint (computes the card)
    with app.app_context():
        session_id = (Session.query.filter_by(track_id=track_id)
                      .order_by(Session.id).first().id)

    resp = client.post(f'/tracks/{track_id}/reference-lap',
                       json={'session_id': session_id, 'lap_number': 1})
    assert resp.status_code == 200

    resp = client.get(f'/api/tracks/{track_id}/dna')
    assert resp.status_code == 200
    card = resp.get_json()['card']
    assert card is not None
    assert card['support']['trajectory']['n_points'] > 0
    assert card['dataset']['source'] == 'reference-lap'
    assert card['reference_ok'] is True


def test_api_similar_no_condition(app, client):
    with app.app_context():
        _a, track_a, session_a = _seed_official(name='Circuit A')
        _b, track_b, session_b = _seed_official(name='Circuit B')
        _set_reference(track_a, session_a)
        _set_reference(track_b, session_b)
        from app.track_dna.cards import build_card

        assert build_card(track_a.id)[0] is not None
        assert build_card(track_b.id)[0] is not None
        db.session.commit()
        id_a, admin_id = track_a.id, _a.id

    _login(client, admin_id)
    resp = client.get(f'/api/tracks/{id_a}/dna/similar')
    assert resp.status_code == 200
    payload = resp.get_json()
    assert [c['track_name'] for c in payload['comparisons']] == \
        ['Circuit B']
    assert payload['comparisons'][0]['similarity_pct'] == 100.0


# ---- track-detail section shell ------------------------------------------


def test_detail_page_has_dna_shell_official_only(app, client):
    with app.app_context():
        admin, track, _session = _seed_official()
        owner = make_user(email='viewer@test.com')
        personal = make_track(name='Personal', created_by=owner.id)
        db.session.commit()
        track_id, personal_id, owner_id = track.id, personal.id, owner.id

    _login(client, owner_id)
    resp = client.get(f'/tracks/{track_id}')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'id="track-dna"' in body
    assert 'track-dna.js' in body
    assert f'data-track-id="{track_id}"' in body

    # personal tracks carry no DNA section at all
    resp = client.get(f'/tracks/{personal_id}')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'id="track-dna"' not in body


def test_edit_page_shows_picker_for_admin(app, client):
    with app.app_context():
        admin, track, session = _seed_official()
        db.session.commit()
        track_id, admin_id, session_id = track.id, admin.id, session.id

    _login(client, admin_id)
    resp = client.get(f'/tracks/{track_id}/edit')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'id="dna-picker"' in body
    assert 'Set reference' in body
    # session options are built client-side from the seeded JSON
    assert f'"id": {session_id}' in body
