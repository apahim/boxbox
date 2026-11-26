"""Read-only Track DNA consensus verification runner (plan Phase 4).

Follows the ``calibration.py`` precedent: nothing imports this module —
no routes, no CLI registration, no writes — and it only SELECTs. It is
the prototype of the Phase 7 compute path. Run inside the container:

    docker compose -f docker-compose.prod.yml --env-file .env.production \\
        exec web python -c \\
        "from app.track_dna.consensus import run; run(1, 'dry')"

Computation scope per plan 14.3/15.6: config membership first
(``sessions.track_config_id``), Phase-1 hygiene exclusions on top
(demo/duplicate sessions are config members but excluded at compute
time), then one condition at a time (wet is a separate bucket, never
mixed — D1/D6).
"""

import json
import math

from app import db
from app.models import TrackConfig
from app.track_dna.loader import load_track_laps
from scripts.analysis.track_dna import DEFAULT_PARAMS, analyze_session
from scripts.analysis.track_dna_braking import (
    DEFAULT_BRAKING_PARAMS,
    analyze_braking,
)
from scripts.analysis.track_dna_consensus import (
    DEFAULT_CONSENSUS_PARAMS,
    ConsensusLap,
    build_consensus,
)
from scripts.analysis.track_dna_elevation import (
    DEFAULT_ELEVATION_PARAMS,
    analyze_elevation,
)

# Phase 9 (plan 21.3): cap on the emitted trajectory's point count —
# enough for a smooth satellite-map polyline at ~3-5 m spacing on a
# 1 km circuit while keeping the stored card small.
MAX_TRAJECTORY_POINTS = 300


def _trajectory_block(consensus, track):
    """Decimated (s, lat, lon) consensus trajectory (plan 21.3).

    The loader projects telemetry about the track datum
    (``project_to_meters`` with ``center=(track.lat, track.lon)``); this
    is its exact inverse, so the UI can place any consensus-frame
    s-position (zone troughs, corner apexes) on a map by linear
    interpolation. The grid starts at s=0 and carries no periodic
    duplicate; the loop is closed implicitly. Returns ``None`` when the
    track has no datum (no map possible) or the consensus is empty.
    """
    if track.lat is None or track.lon is None:
        return None
    n = int(consensus.grid.size)
    if n == 0:
        return None
    stride = max(1, -(-n // MAX_TRAJECTORY_POINTS))
    kx = 111320.0 * math.cos(math.radians(track.lat))
    points = []
    for i in range(0, n, stride):
        s = float(consensus.grid[i])
        x = float(consensus.x[i])
        y = float(consensus.y[i])
        points.append([round(s, 1),
                       round(track.lat + y / 110540.0, 6),
                       round(track.lon + x / kx, 6)])
    return {
        'length_m': round(float(consensus.length_m), 2),
        'n_points': len(points),
        'points': points,
    }


def compute_config(track_config_id, condition='dry',
                   params=DEFAULT_CONSENSUS_PARAMS,
                   engine_params=DEFAULT_PARAMS,
                   braking_params=DEFAULT_BRAKING_PARAMS,
                   elevation_params=DEFAULT_ELEVATION_PARAMS):
    """Compute the Phase 4 consensus, dimensions 1-8, the Phase 5
    braking section (dimension 9 + zones) and the Phase 6 elevation
    section (dimension 10 + profile) for one track configuration and
    condition. Returns a JSON-serialisable dict."""
    config = db.session.get(TrackConfig, track_config_id)
    if config is None:
        return {'error': f'no track config {track_config_id!r}'}

    track, sessions, _dataset = load_track_laps(
        config.track_id, condition=condition, track_config_id=config.id)

    result = {
        'track_config_id': config.id,
        'track_id': config.track_id,
        'config_name': config.name,
        'direction': config.direction,
        'condition': condition,
    }
    if track is None:
        result['error'] = f'no track {config.track_id}'
        return result

    inputs = []
    spun = []
    n_valid = 0
    rejected = {}
    for entry in sessions:
        geometry = analyze_session(entry['laps'], engine_params)
        n_valid += geometry.n_valid
        for rej in geometry.rejected:
            rejected[rej.reason] = rejected.get(rej.reason, 0) + 1
        for geo in geometry.laps:
            record = ConsensusLap(user_id=entry['user_id'],
                                  session_id=entry['session_id'],
                                  lap_number=geo.lap_number,
                                  device=entry['device'] or 'unknown',
                                  geometry=geo)
            if geo.spun:
                spun.append(record)
            else:
                inputs.append(record)

    users = {}
    for entry in sessions:
        users[entry['user_id']] = users.get(entry['user_id'], 0) + 1
    dates = [entry['date'] for entry in sessions if entry['date']]
    result['dataset'] = {
        'users': dict(sorted(users.items())),
        'session_ids': [entry['session_id'] for entry in sessions],
        'devices': sorted({entry['device'] for entry in sessions
                           if entry['device']}),
        'date_range': [min(dates), max(dates)] if dates else None,
        'laps': {'valid': n_valid, 'rejected': rejected, 'spun': len(spun)},
    }
    if not inputs:
        result['error'] = 'no valid laps for this condition'
        return result

    consensus = build_consensus(inputs, params=params,
                                engine_params=engine_params,
                                condition=condition)
    result['consensus'] = consensus.summary()
    result['trajectory'] = _trajectory_block(consensus, track)
    braking = analyze_braking(consensus, params=braking_params)
    result['braking'] = braking.summary()
    elevation = analyze_elevation(consensus, params=elevation_params)
    result['elevation'] = elevation.summary()
    return result


def run(track_config_id, condition='dry', **kwargs):
    """Compute, print and return one configuration's consensus result."""
    result = compute_config(track_config_id, condition, **kwargs)
    print(json.dumps(result, indent=2, default=str))
    return result
