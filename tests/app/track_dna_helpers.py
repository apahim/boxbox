"""Shared helpers for the Track DNA app-layer tests.

Seeding utilities for the reference-lap card pipeline: synthetic
capsule-loop sessions with speed + altitude channels, plus the
make_user/make_track factories the deleted calibration tests used to
provide.
"""

import math
from datetime import date, datetime, timezone

import numpy as np

from app import db
from app.models import Lap, Session, Telemetry, Track, User

CENTER = (52.0, -7.0)
_M_PER_DEG_LAT = 110540.0
_M_PER_DEG_LON = 111320.0 * math.cos(math.radians(CENTER[0]))


def make_user(email='driver@test.com', admin=False):
    user = User(email=email, display_name=email.split('@')[0].title(),
                google_id='g-' + email, is_admin=admin,
                terms_accepted_at=datetime.now(timezone.utc))
    db.session.add(user)
    db.session.flush()
    return user


def make_track(name='Test Circuit', created_by=None):
    """A track; ``created_by=None`` makes it official (DNA-eligible)."""
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


def speed_profile(n_points, windows, cruise=20.0, slow=12.0,
                  ramp_m=25.0, spacing=0.5):
    """Cruise speed with circular trapezoid decel windows.

    ``windows``: ``(center_m, hold_m)`` pairs — path-arclength window
    centre and full-depth hold width, with ``ramp_m`` ramps on each
    side. Index space is circular, so a window may straddle index 0
    (the s=0 seam). Plateaus stay exactly ``cruise``/``slow`` so
    reduction values are exact for boundary tests.
    """
    v = np.full(n_points, cruise)
    idx = np.arange(n_points)
    r = max(3, int(round(ramp_m / spacing)))
    for center_m, hold_m in windows:
        c = int(round(center_m / spacing)) % n_points
        h = max(1, int(round(hold_m / spacing / 2)))
        d = np.abs(((idx - c + n_points // 2) % n_points) - n_points // 2)
        w = h + r
        depth = np.where(d <= h, 1.0, np.clip((w - d) / r, 0.0, 1.0))
        v = np.minimum(v, cruise - (cruise - slow) * depth)
    return v


def tent(n, spacing, center_m, half_width_m, height_m):
    """Triangular hill altitude array (circular distance)."""
    idx = np.arange(n)
    d = np.abs((idx * spacing - center_m
                + n * spacing / 2) % (n * spacing) - n * spacing / 2)
    return height_m * np.maximum(0.0, 1.0 - d / half_width_m)


def _login(client, user_id):
    """Authenticate the test client (flask_login session key). The app
    fixture keeps one context pushed for the whole test, so
    flask-login's g._login_user cache survives across requests — clear
    it so the switch actually takes effect."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
    from flask import g
    g.pop('_login_user', None)


def seed_dna_session(track, user, laps=2, day=1, windows=((100.0, 20.0),),
                     height_m=3.0, with_speed=True, with_altitude=True,
                     data_source='racechrono', date_override=None):
    """A capsule-loop session with speed + altitude channels.

    Creates the Telemetry rows (per lap) and the Lap table rows (clean,
    with times) the admin picker reads. Returns the session.
    """
    session = Session(user_id=user.id, track_id=track.id,
                      data_source=data_source,
                      date=date_override or date(2026, 1, day))
    db.session.add(session)
    db.session.flush()
    pts = capsule_points(80.0, 40.0)          # 0.5 m spacing
    speeds = (speed_profile(len(pts), list(windows))
              if with_speed else None)
    alt = tent(len(pts), 0.5, 205.0, 200.0, height_m)
    lap_seconds = []
    for lap_number in range(1, laps + 1):
        lap_time = 60.0 + 0.1 * lap_number
        lap_seconds.append(lap_time)
        for i, (px, py) in enumerate(pts):
            lat, lon = m_to_latlon(px, py)
            db.session.add(Telemetry(
                session_id=session.id,
                lap_number=lap_number,
                elapsed_time=(lap_number - 1) * lap_time + 0.05 * i,
                distance_traveled=(len(pts) * 0.5 * (lap_number - 1)
                                   + 0.5 * i),
                latitude=lat, longitude=lon,
                altitude=(float(alt[i]) if with_altitude else None),
                speed_gps=(float(speeds[i]) if with_speed else None)))
    for lap_number, seconds in enumerate(lap_seconds, start=1):
        db.session.add(Lap(session_id=session.id, lap_number=lap_number,
                           seconds=seconds, is_outlier=False))
    session.total_laps = laps
    session.clean_laps = laps
    session.best_lap_time = min(lap_seconds)
    db.session.flush()
    return session
