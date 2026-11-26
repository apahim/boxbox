"""Streaming telemetry loader for the Track DNA compute path.

Promoted from ``app/track_dna/calibration.py`` in Phase 4 (plan 15.5:
"copy the loader or promote it"). Loads a track's hygiene-included
sessions' numbered laps as engine inputs with ONE streamed telemetry
query; optionally restricted to a track configuration's member sessions
— the Phase 4+ compute filter: config membership first, Phase-1 hygiene
exclusions on top (plan 14.3/15.6 — demo/duplicate sessions are config
members but excluded at compute time).

Read-only: SELECTs only.
"""

import math

import numpy as np

from app import db
from app.models import Session, Telemetry, Track
from app.track_dna.hygiene import classify_track_sessions
from scripts.analysis.track_dna import LapInput
from scripts.analysis.utils import project_to_meters

STREAM_CHUNK = 5000


def load_track_laps(track_id, condition=None, track_config_id=None):
    """Load hygiene-included sessions' numbered laps as engine inputs.

    Returns ``(track, sessions, dataset)`` where ``dataset`` is the Phase-1
    TrackDataset and ``sessions`` is a list of dicts (session id order)
    with ``session_id``, ``user_id``, ``device``, ``condition``, ``date``
    and ``laps`` mapping lap number -> LapInput (metres, track-centred
    frame). With ``track_config_id`` set, only that configuration's
    member sessions are loaded (still hygiene-filtered).

    Per-lap sample counts follow Phase 1's basis (every telemetry row in
    the lap group, GPS-bearing or not) so the D8 reconciliation compares
    like with like; position arrays use the GPS-bearing rows in telemetry
    order. ONE streamed telemetry query for the whole track.
    """
    track = db.session.get(Track, track_id)
    if track is None:
        return None, [], None

    dataset = classify_track_sessions(track_id)
    verdicts = [v for v in dataset.included
                if condition is None or v.condition == condition]
    if track_config_id is not None:
        member_ids = {row[0] for row in db.session.query(Session.id).filter(
            Session.track_config_id == track_config_id).all()}
        verdicts = [v for v in verdicts if v.session_id in member_ids]
    if not verdicts:
        return track, [], dataset

    session_ids = [v.session_id for v in verdicts]
    meta = {s.id: s for s in
            Session.query.filter(Session.id.in_(session_ids)).all()}
    loaded = []
    by_id = {}
    for verdict in verdicts:
        session = meta[verdict.session_id]
        entry = {
            'session_id': verdict.session_id,
            'user_id': verdict.user_id,
            'device': session.data_source,
            'condition': verdict.condition,
            'date': session.date.isoformat() if session.date else None,
            'provisional_laps': verdict.provisional_laps,
            'laps': {},
        }
        loaded.append(entry)
        by_id[verdict.session_id] = entry

    center = (track.lat, track.lon)
    rows = db.session.execute(
        db.select(Telemetry.session_id,
                  Telemetry.lap_number,
                  Telemetry.latitude,
                  Telemetry.longitude,
                  Telemetry.altitude,
                  Telemetry.speed_gps,
                  Telemetry.speed_calc,
                  Telemetry.elapsed_time)
        .where(Telemetry.session_id.in_(session_ids),
               Telemetry.lap_number >= 1)
        .order_by(Telemetry.session_id, Telemetry.lap_number, Telemetry.id)
        .execution_options(yield_per=STREAM_CHUNK)
    )

    state = {}  # (sid, lap) -> accumulator

    def finalize(key):
        acc = state.pop(key)
        sid, _ = key
        entry = by_id[sid]
        if not acc['lat']:
            return
        x, y = project_to_meters(acc['lat'], acc['lon'], center)
        altitude = _fill_gaps(acc['alt']) if acc['alt'] else None
        speed = _fill_gaps(acc['speed']) if acc['speed'] else None
        elapsed = (np.asarray(acc['elapsed'], dtype=float)
                   if acc['elapsed'] else None)
        # n_samples counts every row of the lap group (Phase-1 parity),
        # including positionless calc/IMU rows
        entry['laps'][key[1]] = LapInput(
            x=x, y=y, altitude=altitude, speed=speed, elapsed=elapsed,
            n_samples=acc['n_rows'])

    for (sid, lap_number, lat, lon, alt, sgps, scalc, elapsed) in rows:
        if sid is None or lap_number is None:
            continue
        key = (sid, int(lap_number))
        if key not in state:
            state[key] = {'lat': [], 'lon': [], 'alt': [], 'speed': [],
                          'elapsed': [], 'n_rows': 0}
        acc = state[key]
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
    for key in sorted(state):
        finalize(key)

    return track, loaded, dataset


def _fill_gaps(values):
    """Float array with NaN gaps linearly interpolated (None if all NaN)."""
    arr = np.asarray(values, dtype=float)
    if np.isnan(arr).all():
        return None
    ok = ~np.isnan(arr)
    if not ok.all():
        arr = np.interp(np.arange(arr.size), np.flatnonzero(ok), arr[ok])
    return arr
