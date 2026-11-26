"""Tests for the Track DNA UI layer (plan Phase 9, spec 21): the
consensus trajectory block, the admin scorecard trigger + staleness
display, the similarity visibility filter and the track-detail section
shell."""

from app import db
from app.models import Track, TrackConfig, TrackDnaScorecard, User

from tests.app.test_track_dna_calibration import make_track, make_user
from tests.app.test_track_dna_scorecards import (
    _login,
    seed_dna_laps,
)
from tests.app.test_track_dna_consensus import make_config


def _seed(owner_email='driver@test.com', laps=2, day=1,
          name='Test Circuit'):
    """Owner + private track + config + laps (no card built yet)."""
    owner = make_user(email=owner_email)
    track = make_track(name=name, created_by=owner.id)
    config = make_config(track, owner)
    seed_dna_laps(track, config, owner, laps=laps, day=day)
    return owner, track, config


# ---- trajectory block (plan 21.3) ------------------------------------------------


def test_trajectory_block_shape(app):
    with app.app_context():
        owner, track, config = _seed()
        from app.track_dna.consensus import compute_config

        result = compute_config(config.id, 'dry')
        assert 'error' not in result
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
        owner, track, config = _seed()
        from scripts.analysis.utils import project_to_meters

        from app.track_dna.consensus import compute_config

        traj = compute_config(config.id, 'dry')['trajectory']
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
        owner, track, config = _seed()
        monkeypatch.setattr('app.track_dna.consensus.'
                            'MAX_TRAJECTORY_POINTS', 10)
        from app.track_dna.consensus import compute_config

        traj = compute_config(config.id, 'dry')['trajectory']
        assert traj['n_points'] <= 10
        assert len(traj['points']) <= 10


def test_builder_stores_trajectory(app):
    with app.app_context():
        owner, track, config = _seed()
        from app.track_dna.scorecards import build_scorecard, card_payload

        card, result = build_scorecard(config.id, 'dry')
        assert card is not None
        assert card.support_json['trajectory'] == result['trajectory']
        assert card.support_json['trajectory']['n_points'] > 0

        served = card_payload(card)
        assert served['support']['trajectory'] == \
            card.support_json['trajectory']


# ---- similarity visibility filter (plan 21.6) ------------------------------------


def test_similar_payload_visibility_filter(app):
    with app.app_context():
        owner_a, track_a, config_a = _seed('a@test.com',
                                           name='Circuit A')
        owner_b, track_b, config_b = _seed('b@test.com',
                                           name='Circuit B')
        from app.track_dna.scorecards import build_scorecard, \
            similar_payload

        card_a, _ = build_scorecard(config_a.id, 'dry')
        card_b, _ = build_scorecard(config_b.id, 'dry')
        assert card_a is not None and card_b is not None
        id_a, id_b = track_a.id, track_b.id

        # default (None): the CLI/test behaviour — every configuration
        payload = similar_payload(id_a, 'dry')
        assert [c['track_id']
                for cfg in payload['configs']
                for c in cfg['comparisons']] == [id_b]

        # viewer B cannot see A's private track -> excluded
        payload = similar_payload(id_b, 'dry', visible_track_ids={id_b})
        assert all(not cfg['comparisons']
                   for cfg in payload['configs'])

        # viewer B with both visible -> included again
        payload = similar_payload(id_b, 'dry',
                                  visible_track_ids={id_a, id_b})
        assert [c['track_id']
                for cfg in payload['configs']
                for c in cfg['comparisons']] == [id_a]


def test_api_similar_respects_visibility(app, client):
    with app.app_context():
        owner_a, track_a, config_a = _seed('a@test.com',
                                           name='Circuit A')
        owner_b, track_b, config_b = _seed('b@test.com',
                                           name='Circuit B')
        from app.track_dna.scorecards import build_scorecard

        assert build_scorecard(config_a.id, 'dry')[0] is not None
        assert build_scorecard(config_b.id, 'dry')[0] is not None
        id_a, id_b = track_a.id, track_b.id
        owner_b_id = owner_b.id

    _login(client, owner_b_id)
    resp = client.get(f'/api/tracks/{id_b}/dna/similar?condition=dry')
    assert resp.status_code == 200
    payload = resp.get_json()
    # B sees only own + official tracks; A's private track is filtered
    assert all(c['track_id'] != id_a
               for cfg in payload['configs']
               for c in cfg['comparisons'])


# ---- staleness (plan 21.4, display-only) ------------------------------------------


def test_current_fingerprint_matches_after_build(app):
    with app.app_context():
        owner, track, config = _seed()
        from app.track_dna.scorecards import (
            build_scorecard,
            current_fingerprint,
        )

        card, _ = build_scorecard(config.id, 'dry')
        assert card is not None
        stored = card.dataset_json['session_fingerprint']
        assert current_fingerprint(config.id, 'dry') == stored
        assert current_fingerprint(config.id, 'wet') != stored

        # a new member session changes the compute input set
        seed_dna_laps(track, config, owner, laps=2, day=2)
        db.session.commit()
        assert current_fingerprint(config.id, 'dry') != stored


def test_admin_dashboard_marks_stale_cards(app, client):
    with app.app_context():
        owner, track, config = _seed()
        from app.track_dna.scorecards import build_scorecard

        card, _ = build_scorecard(config.id, 'dry')
        assert card is not None
        admin = make_user(email='admin@test.com', admin=True)
        db.session.commit()
        track_id, config_id, owner_id, admin_id = \
            track.id, config.id, owner.id, admin.id

    _login(client, admin_id)
    resp = client.get('/admin/')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Track DNA' in body
    assert 'current' in body

    # new session -> fingerprint drift -> the badge flips
    with app.app_context():
        seed_dna_laps(db.session.get(Track, track_id),
                      db.session.get(TrackConfig, config_id),
                      db.session.get(User, owner_id), laps=2, day=2)
        db.session.commit()

    resp = client.get('/admin/')
    body = resp.get_data(as_text=True)
    assert 'inputs changed' in body


# ---- admin trigger (plan 21.4) -----------------------------------------------------


def test_admin_trigger_requires_admin(app, client):
    with app.app_context():
        owner, track, config = _seed()
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
        owner, track, config = _seed()
        admin = make_user(email='admin@test.com', admin=True)
        db.session.commit()
        track_id, config_id, admin_id = track.id, config.id, admin.id

    _login(client, admin_id)
    resp = client.post(f'/admin/tracks/{track_id}/compute-dna',
                       follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # dry computed (seed laps), wet honestly reported as empty
    assert 'Rental Layout dry:' in body
    assert 'wet: no valid laps' in body

    with app.app_context():
        cards = TrackDnaScorecard.query.filter_by(
            track_config_id=config_id).all()
        assert len(cards) == 1
        assert cards[0].condition == 'dry'
        assert cards[0].overall_score is not None
        assert cards[0].support_json['trajectory'] is not None


def test_admin_trigger_no_configs_flashes_warning(app, client):
    with app.app_context():
        owner = make_user()
        track = make_track(created_by=owner.id)
        admin = make_user(email='admin@test.com', admin=True)
        db.session.commit()
        track_id, admin_id = track.id, admin.id

    _login(client, admin_id)
    resp = client.post(f'/admin/tracks/{track_id}/compute-dna',
                       follow_redirects=True)
    assert resp.status_code == 200
    assert 'has no configurations' in resp.get_data(as_text=True)


# ---- track-detail section shell -----------------------------------------------------


def test_detail_page_has_dna_shell(app, client):
    with app.app_context():
        owner, track, config = _seed()
        db.session.commit()
        track_id, owner_id = track.id, owner.id

    _login(client, owner_id)
    resp = client.get(f'/tracks/{track_id}')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'id="track-dna"' in body
    assert 'track-dna.js' in body
    assert f'data-track-id="{track_id}"' in body


def test_api_dna_serves_trajectory(app, client):
    with app.app_context():
        owner, track, config = _seed()
        from app.track_dna.scorecards import build_scorecard

        card, _ = build_scorecard(config.id, 'dry')
        assert card is not None
        db.session.commit()
        track_id, owner_id = track.id, owner.id

    _login(client, owner_id)
    resp = client.get(f'/api/tracks/{track_id}/dna')
    assert resp.status_code == 200
    served = resp.get_json()['scorecards'][0]
    assert served['support']['trajectory']['n_points'] > 0
