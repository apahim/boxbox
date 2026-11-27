"""Reference-lap loader and validation for the Track DNA compute path.

Loads the admin-selected reference lap (``tracks.reference_session_id``
+ ``tracks.reference_lap_number``), runs the frozen engine on the
session, and validates that the chosen lap is among the session's valid
(non-spun) laps. Read-only: SELECTs only.
"""

import math

import numpy as np

from app import db
from app.models import Session, Telemetry, Track
from scripts.analysis.track_dna import DEFAULT_PARAMS, LapInput, \
    analyze_session
from scripts.analysis.utils import project_to_meters

STREAM_CHUNK = 5000


def load_reference(track, engine_params=DEFAULT_PARAMS):
    """Load and validate the track's reference lap.

    Returns a dict: ``ok`` plus either the analysis inputs (``session``,
    ``geometry`` — the session's ``SessionGeometry`` — and ``lap``, the
    chosen lap's ``LapGeometry``) or an ``error`` message. All failure
    modes are data problems (unset reference, missing session, invalid
    lap), never exceptions.
    """
    if track is None:
        return {'ok': False, 'error': 'track not found'}
    if track.reference_session_id is None or \
            track.reference_lap_number is None:
        return {'ok': False, 'error': 'no reference lap selected'}

    session = db.session.get(Session, track.reference_session_id)
    if session is None or session.track_id != track.id:
        return {'ok': False,
                'error': 'reference session is gone or moved tracks'}

    laps = _load_session_laps(session, (track.lat, track.lon))
    if not laps:
        return {'ok': False,
                'error': f'session {session.id} has no numbered laps'}

    geometry = analyze_session(laps, engine_params)
    lap_number = int(track.reference_lap_number)
    for geo in geometry.laps:
        if geo.lap_number == lap_number:
            return {'ok': True, 'session': session,
                    'geometry': geometry, 'lap': geo}

    rejected = {r.lap_number: r for r in geometry.rejected}
    if lap_number in rejected:
        reason = rejected[lap_number]
        return {'ok': False,
                'error': (f'lap {lap_number} is not usable: '
                          f'{reason.reason} ({reason.detail})')}
    return {'ok': False,
            'error': f'lap {lap_number} does not exist in '
                     f'session {session.id}'}


def reference_verdict(track):
    """Cheap validity check for display (admin health, API payloads).

    Returns ``{'ok': bool, 'error': str | None}`` — the same verdict
    ``load_reference`` reaches, computed on demand (nothing is stored).
    """
    result = load_reference(track)
    return {'ok': result['ok'], 'error': result.get('error')}


def _load_session_laps(session, center):
    """One session's numbered laps as engine inputs, from ONE streamed
    telemetry query. Returns ``{lap_number: LapInput}`` (metres,
    track-centred frame); laps without GPS positions are dropped."""
    rows = db.session.execute(
        db.select(Telemetry.lap_number,
                  Telemetry.latitude,
                  Telemetry.longitude,
                  Telemetry.altitude,
                  Telemetry.speed_gps,
                  Telemetry.speed_calc,
                  Telemetry.elapsed_time)
        .where(Telemetry.session_id == session.id,
               Telemetry.lap_number >= 1)
        .order_by(Telemetry.lap_number, Telemetry.id)
        .execution_options(yield_per=STREAM_CHUNK)
    )

    state = {}  # lap_number -> accumulator

    def finalize(lap_number):
        acc = state.pop(lap_number)
        if not acc['lat']:
            return
        x, y = project_to_meters(acc['lat'], acc['lon'], center)
        altitude = _fill_gaps(acc['alt']) if acc['alt'] else None
        speed = _fill_gaps(acc['speed']) if acc['speed'] else None
        elapsed = (np.asarray(acc['elapsed'], dtype=float)
                   if acc['elapsed'] else None)
        laps[lap_number] = LapInput(
            x=x, y=y, altitude=altitude, speed=speed, elapsed=elapsed,
            n_samples=acc['n_rows'])

    laps = {}
    current = None
    for lap_number, lat, lon, alt, sgps, scalc, elapsed in rows:
        if lap_number is None:
            continue
        lap_number = int(lap_number)
        if lap_number != current:
            if current is not None:
                finalize(current)
            current = lap_number
            if lap_number not in state:
                state[lap_number] = {'lat': [], 'lon': [], 'alt': [],
                                     'speed': [], 'elapsed': [],
                                     'n_rows': 0}
        acc = state[lap_number]
        acc['n_rows'] += 1
        if lat is None or lon is None:
            continue
        acc['lat'].append(float(lat))
        acc['lon'].append(float(lon))
        acc['alt'].append(float(alt) if alt is not None else math.nan)
        speed = sgps if sgps is not None else scalc
        acc['speed'].append(float(speed) if speed is not None else math.nan)
        if elapsed is not None:
            acc['elapsed'].append(float(elapsed))
    if current is not None:
        finalize(current)
    return laps


def _fill_gaps(values):
    """Float array with NaN gaps linearly interpolated (None if all NaN)."""
    arr = np.asarray(values, dtype=float)
    if np.isnan(arr).all():
        return None
    ok = ~np.isnan(arr)
    if not ok.all():
        arr = np.interp(np.arange(arr.size), np.flatnonzero(ok), arr[ok])
    return arr
