"""Tests for the Track DNA scorecard builder, storage, API endpoints
and CLI (plan Phase 7, spec 19)."""

import pytest

from app import db
from app.models import TrackDnaScorecard, User

from tests.app.test_track_dna_calibration import (
    capsule_points,
    make_track,
    make_user,
    m_to_latlon,
)
from tests.app.test_track_dna_braking import speed_profile
from tests.app.test_track_dna_consensus import make_config
from tests.app.test_track_dna_elevation import tent


def seed_dna_laps(track, config, user, laps=2, labels=None, day=1,
                  windows=((100.0, 20.0),), height_m=3.0,
                  with_speed=True, data_source='racechrono'):
    """Capsule laps with speed + altitude channels (both conditions of
    the braking and elevation layers satisfied)."""
    from datetime import date

    from app.models import Session, Telemetry

    session = Session(user_id=user.id, track_id=track.id,
                      track_config_id=config.id if config else None,
                      labels=labels, data_source=data_source,
                      date=date(2026, 1, day))
    db.session.add(session)
    db.session.flush()
    pts = capsule_points(80.0, 40.0)          # 0.5 m spacing
    speeds = (speed_profile(len(pts), list(windows), spacing=0.5)
              if with_speed else None)
    alt = tent(len(pts), 0.5, 205.0, 200.0, height_m)
    for lap_number in range(1, laps + 1):
        for i, (px, py) in enumerate(pts):
            lat, lon = m_to_latlon(px, py)
            db.session.add(Telemetry(
                session_id=session.id,
                lap_number=lap_number,
                elapsed_time=0.05 * i,
                distance_traveled=(len(pts) * 0.5 * (lap_number - 1)
                                   + 0.5 * i),
                latitude=lat, longitude=lon, altitude=float(alt[i]),
                speed_gps=(float(speeds[i]) if with_speed else None)))
    db.session.flush()
    return session


def _seed_track_with_card(with_speed=True):
    owner = make_user()
    track = make_track(created_by=owner.id)
    config = make_config(track, owner)
    seed_dna_laps(track, config, owner, laps=2, day=1,
                  with_speed=with_speed)
    from app.track_dna.scorecards import build_scorecard
    card, result = build_scorecard(config.id, 'dry')
    assert card is not None
    return owner, track, config, card


# ---- builder and storage --------------------------------------------------------


def test_build_scorecard_stores_and_upserts(app):
    with app.app_context():
        owner, track, config, card = _seed_track_with_card()
        assert TrackDnaScorecard.query.count() == 1
        assert card.track_config_id == config.id
        assert card.condition == 'dry'
        assert card.methodology_version == '1.0'
        assert card.stale is False

        dims = card.dimensions_json
        assert len(dims) == 10
        by_key = {d['key']: d for d in dims}
        assert by_key['track_length_m']['value'] > 0
        assert 0.0 <= by_key['straight_pct']['value'] <= 100.0
        assert by_key['longest_straight_m']['value'] <= \
            by_key['track_length_m']['value']
        assert all(d['score'] is None or 0.0 <= d['score'] <= 10.0
                   for d in dims)
        assert sum(d['weight'] for d in dims) == 100
        assert by_key['heavy_braking_freq']['sensitivity'] is not None
        assert by_key['elevation_gain']['evidence'][
            'window_by_device'] == {'racechrono': 25.0}
        assert 0.0 <= card.overall_score <= 10.0

        # invariants against the support payload
        consensus = card.support_json['consensus']['dimensions']
        assert consensus['dc_count']['evidence']['consensus_set_count'] \
            <= consensus['corner_count']['value']
        assert card.dataset_json['session_fingerprint']
        assert card.dataset_json['session_ids']
        assert card.params_json.keys() == {'engine', 'consensus',
                                           'braking', 'elevation'}

        # reproducibility: same data -> identical dimensions
        first = card.dimensions_json
        from app.track_dna.scorecards import build_scorecard
        card2, _ = build_scorecard(config.id, 'dry')
        assert card2.id == card.id            # upsert, not a new row
        assert TrackDnaScorecard.query.count() == 1
        assert card2.dimensions_json == first


def test_build_scorecard_retains_old_versions(app):
    with app.app_context():
        owner, track, config, card = _seed_track_with_card()
        from app import track_dna
        from app.track_dna import scorecards
        try:
            scorecards.METHODOLOGY_VERSION = '0.9'
            old, _ = scorecards.build_scorecard(config.id, 'dry')
            assert old is not None
            assert old.methodology_version == '0.9'
        finally:
            scorecards.METHODOLOGY_VERSION = '1.0'
        fresh, _ = scorecards.build_scorecard(config.id, 'dry')
        assert fresh.methodology_version == '1.0'
        assert TrackDnaScorecard.query.count() == 2    # history kept


def test_missing_speed_is_missing_not_zero(app):
    with app.app_context():
        owner, track, config, card = _seed_track_with_card(with_speed=False)
        by_key = {d['key']: d for d in card.dimensions_json}
        assert by_key['heavy_braking_freq']['value'] is None
        assert by_key['heavy_braking_freq']['score'] is None
        assert by_key['heavy_braking_freq']['class'] is None
        # overall excludes the missing dimension (never zero)
        present = [d for d in card.dimensions_json if d['score'] is not None]
        expected = round(sum(d['score'] * d['weight'] for d in present)
                         / sum(d['weight'] for d in present), 2)
        assert card.overall_score == pytest.approx(expected, abs=0.01)


def test_build_scorecard_no_data_condition(app):
    with app.app_context():
        owner = make_user()
        track = make_track(created_by=owner.id)
        config = make_config(track, owner)
        from app.track_dna.scorecards import build_scorecard
        card, result = build_scorecard(config.id, 'dry')
        assert card is None
        assert 'error' in result


# ---- API ------------------------------------------------------------------------


def _login(client, user_id):
    """Authenticate the test client (flask_login session key). The app
    fixture keeps one context pushed for the whole test, so
    flask-login's g._login_user cache survives across requests — clear
    it so the switch actually takes effect."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
    from flask import g
    g.pop('_login_user', None)


def test_api_dna_requires_auth_and_track_access(app, client):
    with app.app_context():
        owner, track, config, card = _seed_track_with_card()
        track_id = track.id

    resp = client.get(f'/api/tracks/{track_id}/dna')
    assert resp.status_code == 401

    with app.app_context():
        viewer = make_user(email='viewer@test.com')
        db.session.commit()
        viewer_id = viewer.id

    _login(client, viewer_id)
    # the viewer owns nothing and the track is not official -> 404
    resp = client.get(f'/api/tracks/{track_id}/dna')
    assert resp.status_code == 404

    resp = client.get('/api/tracks/99999/dna')
    assert resp.status_code == 404


def test_api_dna_returns_card(app, client):
    with app.app_context():
        owner, track, config, card = _seed_track_with_card()
        track_id, config_id, owner_id = track.id, config.id, owner.id

    _login(client, owner_id)
    resp = client.get(f'/api/tracks/{track_id}/dna')
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload['track_id'] == track_id
    assert len(payload['scorecards']) == 1
    served = payload['scorecards'][0]
    assert served['track_config_id'] == config_id
    assert served['condition'] == 'dry'
    assert served['methodology_version'] == '1.0'
    assert served['overall_score'] is not None
    assert len(served['dimensions']) == 10
    assert served['dataset']['session_fingerprint']
    assert 'consensus' in served['support']


def test_api_similar_endpoint(app, client):
    with app.app_context():
        owner, track_a, config_a, card_a = _seed_track_with_card()
        # a second, different track: no braking windows, bigger hill
        track_b = make_track(name='Circuit B', created_by=owner.id)
        config_b = make_config(track_b, owner)
        seed_dna_laps(track_b, config_b, owner, laps=2, day=2,
                      windows=(), height_m=10.0)
        from app.track_dna.scorecards import build_scorecard
        card_b, _ = build_scorecard(config_b.id, 'dry')
        assert card_b is not None
        id_a, id_b, owner_id = track_a.id, track_b.id, owner.id

    _login(client, owner_id)
    resp = client.get(f'/api/tracks/{id_a}/dna/similar?condition=dry')
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload['condition'] == 'dry'
    configs = payload['configs']
    assert len(configs) == 1
    comparisons = configs[0]['comparisons']
    assert len(comparisons) == 1
    comp = comparisons[0]
    assert comp['track_id'] == id_b
    assert 0.0 <= comp['similarity_pct'] <= 100.0
    assert comp['coverage'] == pytest.approx(1.0)
    assert comp['contributions']

    # symmetric from the other side
    resp_b = client.get(f'/api/tracks/{id_b}/dna/similar?condition=dry')
    assert resp_b.status_code == 200
    comp_b = resp_b.get_json()['configs'][0]['comparisons'][0]
    assert comp_b['similarity_pct'] == comp['similarity_pct']
    assert comp_b['track_id'] == id_a

    # identical card similarity is 100 (compare the card with itself
    # via the pure function on served dimensions)
    from scripts.analysis.track_dna_score import similarity
    served = client.get(f'/api/tracks/{id_a}/dna').get_json()
    dims = served['scorecards'][0]['dimensions']
    assert similarity(dims, dims)['similarity_pct'] == 100.0

    # unknown condition and missing scorecards
    assert client.get(
        f'/api/tracks/{id_a}/dna/similar?condition=snow').status_code == 400
    assert client.get(
        f'/api/tracks/{id_a}/dna/similar?condition=wet').status_code == 404


# ---- CLI ------------------------------------------------------------------------


def test_cli_compute_track_dna(app):
    with app.app_context():
        owner, track, config, card = _seed_track_with_card()
        track_id = track.id
        TrackDnaScorecard.query.delete()
        db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(args=['compute-track-dna', str(track_id)])
    assert result.exit_code == 0
    assert 'scorecard(s) stored' in result.output
    assert 'Track length' in result.output
    assert 'Elevation gain' in result.output

    with app.app_context():
        assert TrackDnaScorecard.query.count() == 1

    # --all backfills every configuration
    result = runner.invoke(args=['compute-track-dna', '--all'])
    assert result.exit_code == 0
    with app.app_context():
        assert TrackDnaScorecard.query.count() == 1     # upsert, not dup

    # argument errors
    assert runner.invoke(args=['compute-track-dna']).exit_code != 0
    assert runner.invoke(args=['compute-track-dna', '99999']).exit_code != 0


def test_cli_compute_condition_and_skip(app):
    with app.app_context():
        owner = make_user()
        track = make_track(created_by=owner.id)
        config = make_config(track, owner)
        seed_dna_laps(track, config, owner, laps=2, labels=['Wet'], day=1)
        track_id = track.id
        db.session.commit()               # the CLI runs after this
                                          # context pops
    runner = app.test_cli_runner()
    result = runner.invoke(args=['compute-track-dna', str(track_id),
                                 '--condition', 'all'])
    assert result.exit_code == 0
    assert 'skipped' in result.output          # dry has no data
    with app.app_context():
        cards = TrackDnaScorecard.query.all()
        assert len(cards) == 1
        assert cards[0].condition == 'wet'
