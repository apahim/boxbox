"""Smoke tests for the read-only Track DNA calibration runner (Phase 3).

The experiments themselves run against production telemetry in-container;
these tests just pin the loader and dispatch behaviour on synthetic data.
"""

import json
import math
import os
from datetime import date

import numpy as np
import pytest

from app import db
from app.models import Session, Telemetry, Track, User
from app.track_dna.calibration import (
    export_golden,
    experiment_lap_counts,
    load_track_laps,
    run,
)

CENTER = (52.0, -7.0)
_M_PER_DEG_LAT = 110540.0
_M_PER_DEG_LON = 111320.0 * math.cos(math.radians(CENTER[0]))


def make_user(email='driver@test.com', admin=False):
    from datetime import datetime, timezone
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


def m_to_latlon(x, y):
    return (CENTER[0] + y / _M_PER_DEG_LAT, CENTER[1] + x / _M_PER_DEG_LON)


def capsule_points(straight=80.0, radius=40.0, spacing=0.5):
    """A closed stadium loop in metre space (two straights + two arcs)."""
    pts = []
    x, y, heading = 0.0, 0.0, 0.0

    def advance(length):
        nonlocal x, y
        n = max(2, int(round(length / spacing)))
        for i in range(1, n + 1):
            d = length * i / n
            pts.append((x + d * math.cos(heading), y + d * math.sin(heading)))
        x += length * math.cos(heading)
        y += length * math.sin(heading)

    def arc(radius, dtheta_deg):
        nonlocal x, y, heading
        rad = math.radians(dtheta_deg)
        cx = x + radius * math.sin(heading)
        cy = y - radius * math.cos(heading)
        n = max(2, int(round(abs(rad) * radius / spacing)))
        bx, by = x - cx, y - cy
        for i in range(1, n + 1):
            a = rad * i / n
            ca, sa = math.cos(a), math.sin(a)
            pts.append((cx + bx * ca - by * sa, cy + bx * sa + by * ca))
        ca, sa = math.cos(rad), math.sin(rad)
        x, y = cx + bx * ca - by * sa, cy + bx * sa + by * ca
        heading += rad

    advance(straight)
    arc(radius, -180)
    advance(straight)
    arc(radius, -180)
    return pts


def seed_session_laps(track, user, labels=None, laps=3):
    session = Session(user_id=user.id, track_id=track.id,
                      labels=labels, data_source='racechrono',
                      date=date(2026, 1, 1))
    db.session.add(session)
    db.session.flush()
    pts = capsule_points()
    for lap_number in range(1, laps + 1):
        for i, (px, py) in enumerate(pts):
            lat, lon = m_to_latlon(px, py)
            db.session.add(Telemetry(
                session_id=session.id,
                lap_number=lap_number,
                elapsed_time=0.05 * i,
                distance_traveled=len(pts) * 0.5 * (lap_number - 1) + 0.5 * i,
                latitude=lat,
                longitude=lon,
                altitude=10.0,
                speed_gps=12.0,
            ))
    db.session.flush()
    return session


def test_load_track_laps_and_lap_counts(app):
    user = make_user()
    track = make_track(created_by=user.id)
    seed_session_laps(track, user, laps=3)

    loaded_track, sessions, dataset = load_track_laps(track.id)
    assert loaded_track.id == track.id
    assert len(sessions) == 1
    entry = sessions[0]
    assert entry['condition'] == 'dry'
    assert entry['device'] == 'racechrono'
    assert sorted(entry['laps']) == [1, 2, 3]
    lap = entry['laps'][1]
    assert len(lap.x) == len(lap.y)
    # projection puts the loop near the track centre in metres
    assert abs(np.mean(lap.x)) < 200
    assert abs(np.mean(lap.y)) < 200
    # channels carried
    assert lap.altitude is not None and np.allclose(lap.altitude, 10.0)
    assert lap.elapsed is not None and np.all(np.diff(lap.elapsed) >= 0)

    result = experiment_lap_counts(track.id)
    assert result['totals']['canonical'] == 3
    assert result['totals']['provisional'] == 3
    assert result['sessions'][0]['canonical_laps'] == 3


def test_load_track_laps_excludes_demo(app):
    user = make_user()
    track = make_track(created_by=user.id)
    seed_session_laps(track, user, labels=['Demo'])
    other = make_user(email='other@test.com')
    seed_session_laps(track, other)

    _, sessions, _ = load_track_laps(track.id)
    assert [s['condition'] for s in sessions] == ['dry']
    assert len(sessions) == 1


def test_export_golden_writes_fixture(app, tmp_path):
    user = make_user()
    track = make_track(created_by=user.id)
    session = seed_session_laps(track, user, laps=2)

    out = export_golden(track.id, [(session.id, 1), (session.id, 2)],
                        str(tmp_path))
    assert out['laps'] == 2
    assert os.path.exists(out['npz'])
    assert os.path.exists(out['json'])

    data = np.load(out['npz'])
    assert data['lap0_x'].size == data['lap0_y'].size
    assert data['lap0_alt'].size == data['lap0_x'].size

    expected = json.load(open(out['json']))
    assert expected['params']['res_m'] == 1.0
    assert len(expected['laps']) == 2
    summary = expected['laps'][0]['summary']
    assert summary['corners'], 'capsule should have corners'
    assert summary['length_m'] == pytest.approx(
        2 * 80 + 2 * math.pi * 40, abs=2.0)
    # the fixture is anonymised: metre-space arrays only
    assert set(data.files) == {f'lap{i}_{k}'
                               for i in (0, 1)
                               for k in ('x', 'y', 'alt', 'speed', 'elapsed')}


def test_run_dispatch(app, capsys):
    user = make_user()
    track = make_track(created_by=user.id)
    seed_session_laps(track, user, laps=2)

    result = run(track.id, 'lap_counts')
    assert result['track_id'] == track.id
    printed = capsys.readouterr().out
    assert 'canonical' in printed
    try:
        run(track.id, 'nope')
        assert False, 'unknown experiment should raise'
    except ValueError:
        pass
