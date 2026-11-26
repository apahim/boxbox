"""Tests for Track DNA configuration identification (plan Phase 2)."""

import math
from datetime import date, datetime, timezone

from app import db
from app.models import Session, Telemetry, Track, TrackConfig, User
from app.track_dna.configs import (
    BBOX_IOU_MIN,
    SF_MAX_M,
    UNCLUSTERED_NO_TELEMETRY,
    cluster_track_sessions,
    proposals_payload,
    session_features,
)
from app.track_dna.hygiene import MIN_SAMPLES
from scripts.analysis.track_dna import bbox_iou, robust_bbox, signed_area

# Reference track center used by every synthetic fixture.
CENTER = (52.0, -7.0)

# Inverse of scripts.analysis.utils.project_to_meters around CENTER.
_M_PER_DEG_LAT = 110540.0
_M_PER_DEG_LON = 111320.0 * math.cos(math.radians(CENTER[0]))


def m_to_latlon(x, y):
    return (CENTER[0] + y / _M_PER_DEG_LAT, CENTER[1] + x / _M_PER_DEG_LON)


def circle_xy(radius, n, direction='cw', phase=0.0):
    """Ordered (x, y) meter points around a circle starting at `phase`.

    'cw' walks the circle clockwise in the east/north frame (decreasing
    angle), 'ccw' counter-clockwise.
    """
    sign = -1.0 if direction == 'cw' else 1.0
    return [(radius * math.cos(phase + sign * 2 * math.pi * i / n),
             radius * math.sin(phase + sign * 2 * math.pi * i / n))
            for i in range(n)]


def make_lap(lap_number, radius=100.0, n=150, direction='cw', phase=0.0,
             dist_total=None, points=None):
    """Build a (lap_number, lat, lon, dist) tuple for session_features."""
    pts = points if points is not None else circle_xy(radius, n, direction,
                                                      phase)
    if dist_total is None:
        dists, d = [], 0.0
        for i, (x, y) in enumerate(pts):
            if i > 0:
                d += math.hypot(x - pts[i - 1][0], y - pts[i - 1][1])
            dists.append(d)
    else:
        dists = [dist_total * i / max(len(pts) - 1, 1) for i in range(len(pts))]
    lat = [m_to_latlon(x, y)[0] for x, y in pts]
    lon = [m_to_latlon(x, y)[1] for x, y in pts]
    return (lap_number, lat, lon, dists)


def make_user(email='driver@test.com', admin=False):
    user = User(email=email, display_name=email.split('@')[0].title(),
                google_id='g-' + email, is_admin=admin,
                terms_accepted_at=datetime.now(timezone.utc))
    db.session.add(user)
    db.session.flush()
    return user


def make_track(name='Test Circuit', created_by=None):
    track = Track(slug=name.lower().replace(' ', '_'), name=name,
                  lat=CENTER[0], lon=CENTER[1], created_by=created_by)
    db.session.add(track)
    db.session.flush()
    return track


def make_session(track, user, date_=date(2026, 1, 1), labels=None,
                 data_source='racechrono'):
    session = Session(user_id=user.id, track_id=track.id, date=date_,
                      labels=labels, data_source=data_source)
    db.session.add(session)
    db.session.flush()
    return session


def add_lap_rows(session, lap, dist_total=None):
    """Seed telemetry rows for one synthetic circle lap."""
    lap_number, lat, lon, dists = lap
    for i, (la, lo) in enumerate(zip(lat, lon)):
        db.session.add(Telemetry(
            session_id=session.id,
            lap_number=lap_number,
            elapsed_time=0.1 * i,
            distance_traveled=dists[i] if dist_total is None
            else dist_total * i / max(len(lat) - 1, 1),
            latitude=la,
            longitude=lo,
        ))
    db.session.flush()


def seed_circle_session(track, user, phase=0.0, direction='cw', radius=100.0,
                        n=150, dist_total=None, labels=None,
                        date_=date(2026, 1, 1)):
    """Session with a single valid circle lap; returns the Session."""
    session = make_session(track, user, labels=labels, date_=date_)
    add_lap_rows(session, make_lap(1, radius=radius, n=n, direction=direction,
                                   phase=phase, dist_total=dist_total))
    return session


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
    # Requests issued inside the test's pushed app context reuse it, so
    # flask-login's g._login_user cache survives across requests — clear
    # it so switching users within one test actually takes effect.
    from flask import g
    g.pop('_login_user', None)


class TestGeometry:
    def test_signed_area_direction(self):
        ccw = circle_xy(100, 200, 'ccw')
        cw = circle_xy(100, 200, 'cw')
        assert signed_area([p[0] for p in ccw], [p[1] for p in ccw]) > 0
        assert signed_area([p[0] for p in cw], [p[1] for p in cw]) < 0

    def test_signed_area_degenerate(self):
        assert signed_area([0.0, 1.0], [0.0, 1.0]) == 0.0
        assert signed_area([], []) == 0.0

    def test_robust_bbox_trims_glitches(self):
        import random
        random.seed(42)
        x = [random.uniform(0, 10) for _ in range(200)]
        y = [random.uniform(0, 10) for _ in range(200)]
        x += [3000.0, 2500.0]   # GPS glitches far outside the circuit
        y += [2800.0, -2000.0]
        x0, y0, x1, y1 = robust_bbox(x, y)
        assert -1.0 < x0 < 1.0
        assert 9.0 < x1 < 11.0
        assert -1.0 < y0 < 1.0
        assert 9.0 < y1 < 11.0

    def test_robust_bbox_empty(self):
        assert robust_bbox([], []) == (0.0, 0.0, 0.0, 0.0)

    def test_bbox_iou(self):
        a = (0.0, 0.0, 10.0, 10.0)
        assert bbox_iou(a, (0.0, 0.0, 10.0, 10.0)) == 1.0
        assert bbox_iou(a, (20.0, 20.0, 30.0, 30.0)) == 0.0
        # Fully nested: 10x10 inside 20x20.
        assert abs(bbox_iou(a, (0.0, 0.0, 20.0, 20.0)) - 0.25) < 1e-9
        # Half overlap: intersection 50, union 150.
        assert abs(bbox_iou(a, (5.0, 0.0, 15.0, 10.0)) - 1 / 3) < 1e-9


class TestSessionFeatures:
    def test_direction_from_circle(self):
        cw = session_features(1, [make_lap(1, direction='cw')], CENTER)
        ccw = session_features(2, [make_lap(1, direction='ccw')], CENTER)
        assert cw.direction == 'cw'
        assert ccw.direction == 'ccw'

    def test_no_valid_laps_returns_none(self):
        # Only short laps and lap 0 — nothing reaches MIN_SAMPLES.
        assert session_features(1, [make_lap(0, n=50)], CENTER) is None
        assert session_features(1, [make_lap(1, n=MIN_SAMPLES - 1)],
                                CENTER) is None
        assert session_features(1, [], CENTER) is None

    def test_exactly_min_samples_is_valid(self):
        f = session_features(1, [make_lap(1, n=MIN_SAMPLES)], CENTER)
        assert f is not None
        assert f.direction == 'cw'

    def test_lap_zero_ignored_for_direction_length_sf(self):
        # Lap 0 sits 500 m away (paddock); it must not affect direction,
        # length or S/F, but it does extend the session bbox.
        far = [(500.0 + 100 * math.cos(a), 100 * math.sin(a))
               for a in [2 * math.pi * i / 150 for i in range(150)]]
        laps = [make_lap(0, points=far, direction='cw'),
                make_lap(1, radius=100.0, n=150, direction='cw',
                         dist_total=1000.0)]
        f = session_features(1, laps, CENTER)
        assert f.direction == 'cw'
        assert f.length == 1000.0
        # S/F is the first point of lap 1, i.e. (100, 0) in meters.
        assert abs(f.sf[0] - 100.0) < 0.01
        assert abs(f.sf[1] - 0.0) < 0.01
        # ... but the far lap is part of the session positions.
        assert f.bbox[2] > 550.0

    def test_length_is_median_of_spans(self):
        laps = [make_lap(1, dist_total=1000.0),
                make_lap(2, dist_total=1100.0)]
        f = session_features(1, laps, CENTER)
        assert f.length == 1050.0

    def test_sf_is_median_of_first_points(self):
        laps = [make_lap(1, phase=0.0), make_lap(2, phase=math.pi / 2)]
        f = session_features(1, laps, CENTER)
        # First points (100, 0) and (0, 100) -> median (50, 50).
        assert abs(f.sf[0] - 50.0) < 0.01
        assert abs(f.sf[1] - 50.0) < 0.01

    def test_bbox_trims_glitch_points(self):
        pts = circle_xy(100, 150, 'cw')
        pts.append((5000.0, 5000.0))  # 1/151 points — below the trim
        f = session_features(1, [make_lap(1, points=pts)], CENTER)
        assert f.bbox[2] < 200.0

    def test_short_laps_do_not_count(self):
        # A 50-sample lap among valid laps contributes nothing.
        laps = [make_lap(1, dist_total=1000.0),
                make_lap(2, n=50, dist_total=5000.0)]
        f = session_features(1, laps, CENTER)
        assert f.length == 1000.0


class TestClustering:
    def test_unknown_track(self, db_session):
        assert cluster_track_sessions(99999) is None

    def test_single_cluster(self, db_session):
        track = make_track()
        user = make_user()
        s1 = seed_circle_session(track, user, phase=0.0)
        s2 = seed_circle_session(track, user, phase=0.1)
        db.session.commit()

        result = cluster_track_sessions(track.id)
        assert len(result.clusters) == 1
        assert result.clusters[0].session_ids == [s1.id, s2.id]
        assert result.clusters[0].direction == 'cw'
        assert result.unclustered == []

    def test_direction_flip_splits(self, db_session):
        track = make_track()
        user = make_user()
        s1 = seed_circle_session(track, user, direction='cw')
        s2 = seed_circle_session(track, user, direction='ccw')
        db.session.commit()

        result = cluster_track_sessions(track.id)
        assert len(result.clusters) == 2
        assert {c.direction for c in result.clusters} == {'cw', 'ccw'}

    def test_sf_distance_splits(self, db_session):
        track = make_track()
        user = make_user()
        # Phase difference 0.8 rad on R=100 -> S/F distance ~78 m > 50 m.
        s1 = seed_circle_session(track, user, phase=0.0)
        s2 = seed_circle_session(track, user, phase=0.8)
        db.session.commit()

        result = cluster_track_sessions(track.id)
        assert len(result.clusters) == 2

    def test_sf_distance_within_threshold_joins(self, db_session):
        track = make_track()
        user = make_user()
        # Phase difference 0.4 rad on R=100 -> S/F distance ~40 m <= 50 m.
        s1 = seed_circle_session(track, user, phase=0.0)
        s2 = seed_circle_session(track, user, phase=0.4)
        db.session.commit()

        result = cluster_track_sessions(track.id)
        assert len(result.clusters) == 1

    def test_bbox_iou_splits(self, db_session):
        track = make_track()
        user = make_user()
        # R=100 vs R=55 -> boxes 200x200 vs 110x110 -> IoU ~0.30 < 0.75.
        s1 = seed_circle_session(track, user, radius=100.0)
        s2 = seed_circle_session(track, user, radius=55.0)
        db.session.commit()

        result = cluster_track_sessions(track.id)
        assert len(result.clusters) == 2

    def test_bbox_iou_similar_radius_joins(self, db_session):
        track = make_track()
        user = make_user()
        # R=100 vs R=95 -> IoU ~0.90 >= 0.75.
        s1 = seed_circle_session(track, user, radius=100.0)
        s2 = seed_circle_session(track, user, radius=95.0)
        db.session.commit()

        result = cluster_track_sessions(track.id)
        assert len(result.clusters) == 1

    def test_transitive_join(self, db_session):
        track = make_track()
        user = make_user()
        # A~B and B~C within S/F threshold; A-C is beyond it (~69 m).
        a = seed_circle_session(track, user, phase=0.0)
        b = seed_circle_session(track, user, phase=0.35)
        c = seed_circle_session(track, user, phase=0.7)
        db.session.commit()

        result = cluster_track_sessions(track.id)
        assert len(result.clusters) == 1
        assert result.clusters[0].session_ids == [a.id, b.id, c.id]

    def test_length_spread_does_not_split(self, db_session):
        track = make_track()
        user = make_user()
        # Same geometry, 12% longer recorded distance (the wet-session case).
        s1 = seed_circle_session(track, user, dist_total=1000.0)
        s2 = seed_circle_session(track, user, dist_total=1120.0)
        db.session.commit()

        result = cluster_track_sessions(track.id)
        assert len(result.clusters) == 1
        cluster = result.clusters[0]
        assert abs(cluster.length_spread_pct - (120.0 / 1060.0) * 100) < 0.1
        assert cluster.length_warning is True

    def test_tight_length_spread_no_warning(self, db_session):
        track = make_track()
        user = make_user()
        s1 = seed_circle_session(track, user, dist_total=1000.0)
        s2 = seed_circle_session(track, user, dist_total=1010.0)
        db.session.commit()

        cluster = cluster_track_sessions(track.id).clusters[0]
        assert cluster.length_warning is False

    def test_insufficient_telemetry_unclustered(self, db_session):
        track = make_track()
        user = make_user()
        s1 = seed_circle_session(track, user, n=50)   # below MIN_SAMPLES
        db.session.commit()

        result = cluster_track_sessions(track.id)
        assert result.clusters == []
        assert result.unclustered == [(s1.id, UNCLUSTERED_NO_TELEMETRY)]
        assert result.features[s1.id] is None

    def test_session_without_telemetry_unclustered(self, db_session):
        track = make_track()
        user = make_user()
        s1 = make_session(track, user)
        db.session.commit()

        result = cluster_track_sessions(track.id)
        assert result.unclustered == [(s1.id, UNCLUSTERED_NO_TELEMETRY)]

    def test_demo_and_duplicate_sessions_are_clustered(self, db_session):
        track = make_track()
        user = make_user()
        s1 = seed_circle_session(track, user)
        demo = seed_circle_session(track, user, labels=['Demo'])
        db.session.commit()

        result = cluster_track_sessions(track.id)
        assert len(result.clusters) == 1
        assert result.clusters[0].session_ids == [s1.id, demo.id]
        assert result.features[demo.id] is not None

    def test_deterministic_ordering(self, db_session):
        track = make_track()
        user = make_user()
        s1 = seed_circle_session(track, user, phase=0.0, direction='cw')
        s2 = seed_circle_session(track, user, direction='ccw')
        s3 = seed_circle_session(track, user, phase=0.1, direction='cw')
        db.session.commit()

        result = cluster_track_sessions(track.id)
        assert [c.session_ids for c in result.clusters] == \
            [[s1.id, s3.id], [s2.id]]
        assert result.clusters[0].session_ids == \
            sorted(result.clusters[0].session_ids)

    def test_cluster_evidence(self, db_session):
        track = make_track()
        user = make_user()
        s1 = seed_circle_session(track, user, phase=0.0, dist_total=1000.0)
        s2 = seed_circle_session(track, user, phase=0.2, dist_total=1010.0)
        db.session.commit()

        cluster = cluster_track_sessions(track.id).clusters[0]
        assert cluster.length_min == 1000.0
        assert cluster.length_median == 1005.0
        assert cluster.length_max == 1010.0
        # Footprint ~ the 2R x 2R circle extent (percentile inset).
        assert 180.0 < cluster.footprint[0] < 200.0
        assert 180.0 < cluster.footprint[1] < 200.0
        # S/F spread = max distance from the median S/F; for two members
        # at phases 0 and 0.2 on R=100 that is ~10 m (half the ~20 m
        # pairwise distance).
        assert 8.0 < cluster.sf_spread < 12.0


class TestProposalsPayload:
    def test_unknown_track(self, db_session):
        assert proposals_payload(99999) is None

    def test_payload_shape_and_badges(self, db_session):
        track = make_track()
        user = make_user()
        s1 = seed_circle_session(track, user, labels=['Wet'])
        s2 = seed_circle_session(track, user, phase=0.1, labels=['Demo'])
        db.session.commit()

        payload = proposals_payload(track.id)
        assert payload['track_id'] == track.id
        assert payload['track_name'] == 'Test Circuit'
        assert payload['params'] == {
            'sf_max_m': SF_MAX_M,
            'bbox_iou_min': BBOX_IOU_MIN,
            'bbox_percentiles': [2.5, 97.5],
        }
        assert len(payload['clusters']) == 1
        assert payload['clusters'][0]['session_ids'] == [s1.id, s2.id]
        assert payload['clusters'][0]['direction'] == 'cw'
        assert 'length' in payload['clusters'][0]
        assert 'footprint_m' in payload['clusters'][0]
        assert payload['unclustered'] == []

        entries = {e['session_id']: e for e in payload['sessions']}
        assert entries[s1.id]['condition'] == 'wet'
        assert entries[s1.id]['included'] is True
        assert entries[s1.id]['clustered'] is True
        assert entries[s2.id]['included'] is False
        assert entries[s2.id]['exclusion_reason'] == 'demo_label'
        assert entries[s2.id]['clustered'] is True

    def test_unclustered_entries(self, db_session):
        track = make_track()
        user = make_user()
        s1 = seed_circle_session(track, user, n=50)
        db.session.commit()

        payload = proposals_payload(track.id)
        assert payload['clusters'] == []
        assert payload['unclustered'] == [
            {'session_id': s1.id, 'reason': UNCLUSTERED_NO_TELEMETRY}]
        assert payload['sessions'][0]['clustered'] is False


class TestConfigRoutes:
    def _seed_official_track(self):
        """Official track + admin + two sessions on the same layout."""
        admin = make_user('admin@test.com', admin=True)
        track = make_track('Official Circuit', created_by=None)
        s1 = seed_circle_session(track, admin, phase=0.0)
        s2 = seed_circle_session(track, admin, phase=0.1)
        db.session.commit()
        return track, admin, s1, s2

    def test_proposals_ok(self, app, client):
        track, admin, s1, s2 = self._seed_official_track()
        _login(client, admin)

        rv = client.get(f'/tracks/{track.id}/configs/proposals')
        assert rv.status_code == 200
        data = rv.get_json()
        assert len(data['clusters']) == 1
        assert data['clusters'][0]['session_ids'] == [s1.id, s2.id]
        assert len(data['sessions']) == 2

    def test_proposals_unknown_track(self, app, client):
        admin = make_user('admin@test.com', admin=True)
        db.session.commit()
        _login(client, admin)
        assert client.get('/tracks/99999/configs/proposals').status_code == 404

    def test_proposals_requires_permission(self, app, client):
        track, _admin, _s1, _s2 = self._seed_official_track()
        viewer = make_user('viewer@test.com')
        db.session.commit()
        _login(client, viewer)

        rv = client.get(f'/tracks/{track.id}/configs/proposals')
        assert rv.status_code == 403

    def test_create_config(self, app, client):
        track, admin, s1, s2 = self._seed_official_track()
        _login(client, admin)

        rv = client.post(f'/tracks/{track.id}/configs/create',
                         json={'session_ids': [s1.id, s2.id],
                               'direction': 'cw'})
        assert rv.status_code == 200
        data = rv.get_json()
        assert data['ok'] is True
        assert data['name'] == 'CW layout'
        assert data['count'] == 2

        db.session.expire_all()
        config = db.session.get(TrackConfig, data['config_id'])
        assert config.track_id == track.id
        assert config.direction == 'cw'
        assert config.confirmed is True
        assert config.created_by == admin.id
        assert db.session.get(Session, s1.id).track_config_id == config.id
        assert db.session.get(Session, s2.id).track_config_id == config.id

    def test_create_config_explicit_name(self, app, client):
        track, admin, s1, _ = self._seed_official_track()
        _login(client, admin)

        rv = client.post(f'/tracks/{track.id}/configs/create',
                         json={'session_ids': [s1.id], 'direction': 'cw',
                               'name': 'Clubhouse layout'})
        assert rv.status_code == 200
        assert rv.get_json()['name'] == 'Clubhouse layout'

    def test_create_config_auto_name_collision(self, app, client):
        track, admin, s1, s2 = self._seed_official_track()
        _login(client, admin)

        rv1 = client.post(f'/tracks/{track.id}/configs/create',
                          json={'session_ids': [s1.id], 'direction': 'cw'})
        rv2 = client.post(f'/tracks/{track.id}/configs/create',
                          json={'session_ids': [s2.id], 'direction': 'cw'})
        assert rv1.get_json()['name'] == 'CW layout'
        assert rv2.get_json()['name'] == 'CW layout 2'

    def test_create_config_validation(self, app, client):
        track, admin, s1, _ = self._seed_official_track()
        other_track = make_track('Other Circuit')
        other_session = seed_circle_session(other_track, admin)
        db.session.commit()
        _login(client, admin)

        base = f'/tracks/{track.id}/configs/create'
        assert client.post(base, json={'session_ids': [s1.id],
                                       'direction': 'north'}).status_code == 400
        assert client.post(base, json={'session_ids': [],
                                       'direction': 'cw'}).status_code == 400
        assert client.post(base, json={'direction': 'cw'}).status_code == 400
        assert client.post(base, json={'session_ids': [other_session.id],
                                       'direction': 'cw'}).status_code == 400

    def test_rename_config(self, app, client):
        track, admin, s1, _ = self._seed_official_track()
        _login(client, admin)
        cid = client.post(f'/tracks/{track.id}/configs/create',
                          json={'session_ids': [s1.id],
                                'direction': 'cw'}).get_json()['config_id']

        rv = client.post(f'/tracks/{track.id}/configs/{cid}/rename',
                         json={'name': 'Renamed'})
        assert rv.status_code == 200
        assert db.session.get(TrackConfig, cid).name == 'Renamed'

    def test_rename_config_duplicate_name(self, app, client):
        track, admin, s1, s2 = self._seed_official_track()
        _login(client, admin)
        cid1 = client.post(f'/tracks/{track.id}/configs/create',
                           json={'session_ids': [s1.id],
                                 'direction': 'cw',
                                 'name': 'Alpha'}).get_json()['config_id']
        cid2 = client.post(f'/tracks/{track.id}/configs/create',
                           json={'session_ids': [s2.id],
                                 'direction': 'cw',
                                 'name': 'Beta'}).get_json()['config_id']

        rv = client.post(f'/tracks/{track.id}/configs/{cid2}/rename',
                         json={'name': 'Alpha'})
        assert rv.status_code == 409
        assert db.session.get(TrackConfig, cid1).name == 'Alpha'
        assert db.session.get(TrackConfig, cid2).name == 'Beta'

    def test_rename_config_validation(self, app, client):
        track, admin, s1, _ = self._seed_official_track()
        _login(client, admin)
        cid = client.post(f'/tracks/{track.id}/configs/create',
                          json={'session_ids': [s1.id],
                                'direction': 'cw'}).get_json()['config_id']

        url = f'/tracks/{track.id}/configs/{cid}/rename'
        assert client.post(url, json={'name': '  '}).status_code == 400
        assert client.post(url, json={'name': 'x' * 101}).status_code == 400
        # A config id from another track is a 404.
        other = make_track('Other Circuit')
        assert client.post(f'/tracks/{other.id}/configs/{cid}/rename',
                           json={'name': 'Nope'}).status_code == 404

    def test_delete_config_unassigns_sessions(self, app, client):
        track, admin, s1, s2 = self._seed_official_track()
        _login(client, admin)
        cid = client.post(f'/tracks/{track.id}/configs/create',
                          json={'session_ids': [s1.id, s2.id],
                                'direction': 'cw'}).get_json()['config_id']

        rv = client.post(f'/tracks/{track.id}/configs/{cid}/delete')
        assert rv.status_code == 200
        db.session.expire_all()
        assert db.session.get(TrackConfig, cid) is None
        assert db.session.get(Session, s1.id).track_config_id is None
        assert db.session.get(Session, s2.id).track_config_id is None

    def test_assign_config_moves_sessions(self, app, client):
        track, admin, s1, s2 = self._seed_official_track()
        _login(client, admin)
        cid1 = client.post(f'/tracks/{track.id}/configs/create',
                           json={'session_ids': [s1.id],
                                 'direction': 'cw'}).get_json()['config_id']
        cid2 = client.post(f'/tracks/{track.id}/configs/create',
                           json={'session_ids': [s2.id],
                                 'direction': 'cw'}).get_json()['config_id']

        rv = client.post(f'/tracks/{track.id}/configs/assign',
                         json={'session_ids': [s1.id], 'config_id': cid2})
        assert rv.status_code == 200
        db.session.expire_all()
        assert db.session.get(Session, s1.id).track_config_id == cid2
        assert db.session.get(Session, s2.id).track_config_id == cid2

        # config_id null unassigns.
        rv = client.post(f'/tracks/{track.id}/configs/assign',
                         json={'session_ids': [s1.id], 'config_id': None})
        assert rv.status_code == 200
        db.session.expire_all()
        assert db.session.get(Session, s1.id).track_config_id is None

    def test_assign_config_unknown_config(self, app, client):
        track, admin, s1, _ = self._seed_official_track()
        _login(client, admin)

        rv = client.post(f'/tracks/{track.id}/configs/assign',
                         json={'session_ids': [s1.id], 'config_id': 99999})
        assert rv.status_code == 404

    def test_personal_track_permissions(self, app, client):
        owner = make_user('owner@test.com')
        track = make_track('Private Circuit', created_by=owner.id)
        s1 = seed_circle_session(track, owner)
        db.session.commit()

        other = make_user('other@test.com')
        _login(client, other)
        rv = client.post(f'/tracks/{track.id}/configs/create',
                         json={'session_ids': [s1.id], 'direction': 'cw'})
        assert rv.status_code == 403

        _login(client, owner)
        rv = client.post(f'/tracks/{track.id}/configs/create',
                         json={'session_ids': [s1.id], 'direction': 'cw'})
        assert rv.status_code == 200

    def test_readonly_edit_page_hides_actions(self, app, client):
        owner = make_user('owner@test.com')
        track = make_track('Private Circuit', created_by=owner.id)
        s1 = seed_circle_session(track, owner)
        db.session.commit()

        _login(client, owner)
        rv = client.post(f'/tracks/{track.id}/configs/create',
                         json={'session_ids': [s1.id],
                               'direction': 'cw',
                               'name': 'Main layout'})
        assert rv.status_code == 200

        viewer = make_user('viewer@test.com')
        _login(client, viewer)
        rv = client.get(f'/tracks/{track.id}/edit')
        assert rv.status_code == 200
        html = rv.get_data(as_text=True)
        assert 'detectConfigs' not in html
        assert 'Main layout' in html

        _login(client, owner)
        rv = client.get(f'/tracks/{track.id}/edit')
        assert rv.status_code == 200
        assert 'detectConfigs' in rv.get_data(as_text=True)
