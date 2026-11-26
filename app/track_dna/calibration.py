"""Read-only calibration experiments for the Track DNA geometry engine.

Phase 3 of the implementation plan (Section 11): parameter sweeps and
dataset studies run against real telemetry to confirm the v1.0 defaults.
Nothing here is wired into the app — no routes, no CLI registration, no
writes. Run inside the container (Phase-2 precedent), e.g.:

    docker compose -f docker-compose.prod.yml --env-file .env.production \\
        exec web python -c \\
        "from app.track_dna.calibration import run; run(4, 'lap_counts')"

Every experiment only SELECTs; the golden export writes a local file, never
the database.

The telemetry loader was promoted to ``app.track_dna.loader`` in Phase 4
(plan 15.5) and is re-exported here so the Phase-3 surface is unchanged.
"""

import json
import math
import os
from dataclasses import replace

import numpy as np

from app.track_dna.loader import load_track_laps  # noqa: F401 — re-export
from scripts.analysis.track_dna import (
    DEFAULT_PARAMS,
    analyze_lap,
    analyze_session,
)


def _analyze_sessions(sessions, params=DEFAULT_PARAMS):
    """Run the canonical session analysis; returns [(entry, SessionGeometry)]."""
    out = []
    for entry in sessions:
        result = analyze_session(entry['laps'], params)
        out.append((entry, result))
    return out


# ---- experiments ----------------------------------------------------------------


def experiment_lap_counts(track_id, condition=None):
    """D8 reconciliation: canonical resampler-based valid-lap counts vs the
    Phase-1 provisional rule, per session, with rejection breakdown."""
    track, sessions, dataset = load_track_laps(track_id, condition)
    if track is None:
        return None
    rows = []
    total_prov = total_canon = 0
    for entry, result in _analyze_sessions(sessions):
        reasons = {}
        for rej in result.rejected:
            reasons[rej.reason] = reasons.get(rej.reason, 0) + 1
        rows.append({
            'session_id': entry['session_id'],
            'condition': entry['condition'],
            'device': entry['device'],
            'provisional_laps': entry['provisional_laps'],
            'canonical_laps': result.n_valid,
            'delta': result.n_valid - entry['provisional_laps'],
            'rejected': reasons,
        })
        total_prov += entry['provisional_laps']
        total_canon += result.n_valid
    return {
        'track_id': track_id,
        'track': track.name,
        'condition': condition or 'all',
        'sessions': rows,
        'totals': {'provisional': total_prov, 'canonical': total_canon,
                   'delta': total_canon - total_prov},
    }


def _valid_geometries(sessions, params=DEFAULT_PARAMS):
    """All valid LapGeometry objects across sessions (once per lap)."""
    geos = []
    for entry, result in _analyze_sessions(sessions, params):
        for geo in result.laps:
            geos.append((entry, geo))
    return geos


def _summary_row(geo):
    return {
        'length_m': geo.length_m,
        'corners': geo.corner_count,
        'straight_pct': 100.0 * geo.straight_fraction,
        'dc': geo.dc_count,
        'longest_straight_m': geo.longest_straight_m,
        'budget_residue_deg': abs(geo.heading_budget['residue_deg']),
    }


def experiment_convergence(track_id, condition='dry',
                           sizes=(1, 3, 5, 10, 20, 50, None), draws=20,
                           seed=0):
    """Section 11: metric stability vs number of laps (seeded draws).
    Acceptance: length +-2 m, corners +-1, straight% +-2 pp at n=10."""
    track, sessions, _ = load_track_laps(track_id, condition)
    if track is None:
        return None
    geos = [geo for _, geo in _valid_geometries(sessions)]
    if not geos:
        return {'track_id': track_id, 'error': 'no valid laps'}
    summaries = [_summary_row(geo) for geo in geos]

    rng = np.random.default_rng(seed)
    n_total = len(summaries)
    results = []
    for size in sizes:
        k = n_total if size is None else min(size, n_total)
        lengths, corners, straights = [], [], []
        for _ in range(draws):
            sample = [summaries[i] for i in
                      rng.choice(n_total, size=k, replace=False)]
            lengths.append(float(np.median([s['length_m'] for s in sample])))
            corners.append(float(np.median([s['corners'] for s in sample])))
            straights.append(float(np.median([s['straight_pct'] for s in sample])))
        results.append({
            'n_laps': k,
            'draws': draws,
            'length_m': {
                'median': round(float(np.median(lengths)), 2),
                'spread': round(float(np.max(lengths) - np.min(lengths)), 2),
            },
            'corners': {
                'median': round(float(np.median(corners)), 2),
                'spread': round(float(np.max(corners) - np.min(corners)), 2),
            },
            'straight_pct': {
                'median': round(float(np.median(straights)), 2),
                'spread': round(float(np.max(straights) - np.min(straights)), 2),
            },
        })
    return {'track_id': track_id, 'condition': condition,
            'n_valid_laps': n_total, 'convergence': results}


def _sweep(track_id, condition, param_name, values, label):
    """Generic parameter sweep over the valid laps of a track."""
    track, sessions, _ = load_track_laps(track_id, condition)
    if track is None:
        return None
    out = []
    for value in values:
        params = replace(DEFAULT_PARAMS, **{param_name: value})
        geos = [geo for _, geo in _valid_geometries(sessions, params)]
        if not geos:
            continue
        corners = [g.corner_count for g in geos]
        radii = [c.radius_m for g in geos for c in g.corners
                 if math.isfinite(c.radius_m)]
        residues = [abs(g.heading_budget['residue_deg']) for g in geos]
        out.append({
            label: value,
            'n_laps': len(geos),
            'corners_median': round(float(np.median(corners)), 2),
            'corners_min_max': [int(np.min(corners)), int(np.max(corners))],
            'radius_p10_median_p90': [
                round(float(np.percentile(radii, 10)), 1),
                round(float(np.median(radii)), 1),
                round(float(np.percentile(radii, 90)), 1)] if radii else [],
            'straight_pct_median': round(100.0 * float(np.median(
                [g.straight_fraction for g in geos])), 2),
            'longest_straight_median_m': round(float(np.median(
                [g.longest_straight_m for g in geos])), 1),
            'budget_residue_p95_deg': round(float(np.percentile(residues, 95)), 2),
        })
    return {'track_id': track_id, 'condition': condition, 'sweep': out}


def experiment_smoothing(track_id, condition='dry', windows=(5.0, 10.0, 15.0)):
    """Section 11: position smoothing window — corner count stability and
    hairpin radius preservation."""
    return _sweep(track_id, condition, 'pos_smooth_m', windows, 'pos_smooth_m')


def experiment_gap_merge(track_id, condition='dry', gaps=(5.0, 10.0, 20.0)):
    """Section 11: corner gap-merge distance — corner count and the
    heading-budget invariant."""
    return _sweep(track_id, condition, 'corner_gap_merge_m', gaps,
                  'corner_gap_merge_m')


def experiment_straight_window(track_id, condition='dry',
                               windows=(10.0, 20.0, 30.0),
                               r_mins=(150.0, 200.0, 250.0)):
    """Section 11: straight window and R_min — straight% and longest
    straight, plus bbox-feasibility violations (longest straight vs the
    driven bbox diagonal)."""
    track, sessions, _ = load_track_laps(track_id, condition)
    if track is None:
        return None
    out = []
    for window in windows:
        for r_min in r_mins:
            params = replace(DEFAULT_PARAMS, straight_window_m=window,
                             r_min_m=r_min)
            geos = [geo for _, geo in _valid_geometries(sessions, params)]
            if not geos:
                continue
            violations = 0
            for geo in geos:
                x0, y0, x1, y1 = geo.bbox
                diagonal = math.hypot(x1 - x0, y1 - y0)
                if geo.longest_straight_m > diagonal:
                    violations += 1
            out.append({
                'straight_window_m': window,
                'r_min_m': r_min,
                'straight_pct_median': round(100.0 * float(np.median(
                    [g.straight_fraction for g in geos])), 2),
                'longest_straight_median_m': round(float(np.median(
                    [g.longest_straight_m for g in geos])), 1),
                'bbox_infeasible_laps': violations,
            })
    return {'track_id': track_id, 'condition': condition, 'sweep': out}


def experiment_radius_method(track_id, condition='dry'):
    """Section 11: representative radius — engine (min of 10 m
    rolling-median radii) vs corner-median vs corner-min |kappa|."""
    track, sessions, _ = load_track_laps(track_id, condition)
    if track is None:
        return None
    engine_r, median_r, min_r = [], [], []
    for _, geo in _valid_geometries(sessions):
        n = geo.kappa.size
        for corner in geo.corners:
            idx = (corner.i_start + np.arange(corner.i_len)) % n
            absk = np.abs(geo.kappa[idx])
            if absk.max() <= 0:
                continue
            engine_r.append(corner.radius_m)
            median_r.append(1.0 / float(np.median(absk)))
            min_r.append(1.0 / float(np.max(absk)))
    if not engine_r:
        return {'track_id': track_id, 'error': 'no corners'}
    return {
        'track_id': track_id,
        'n_corners': len(engine_r),
        'engine_rolling_median_min': _rstats(engine_r),
        'corner_median': _rstats(median_r),
        'corner_min': _rstats(min_r),
    }


def _rstats(values):
    return {
        'p10': round(float(np.percentile(values, 10)), 1),
        'median': round(float(np.median(values)), 1),
        'p90': round(float(np.percentile(values, 90)), 1),
    }


def experiment_device(track_id, condition='dry'):
    """Section 11: GoPro-only vs RaceBox-only vs combined geometry."""
    track, sessions, _ = load_track_laps(track_id, condition)
    if track is None:
        return None

    def _stats(entries):
        geos = [geo for _, geo in _valid_geometries(entries)]
        if not geos:
            return None
        return {
            'sessions': len(entries),
            'laps': len(geos),
            'length_median_m': round(float(np.median(
                [g.length_m for g in geos])), 1),
            'corners_median': round(float(np.median(
                [g.corner_count for g in geos])), 2),
            'straight_pct_median': round(100.0 * float(np.median(
                [g.straight_fraction for g in geos])), 2),
            'longest_straight_median_m': round(float(np.median(
                [g.longest_straight_m for g in geos])), 1),
        }

    devices = sorted({entry['device'] for entry in sessions})
    return {
        'track_id': track_id,
        'by_device': {device: _stats([e for e in sessions
                                      if e['device'] == device])
                      for device in devices},
        'combined': _stats(sessions),
    }


def experiment_holdout(track_id, condition='dry', tolerance_m=20.0):
    """Section 11: user holdout — corner-set overlap between the
    leave-one-user-out split (develop on the others, validate on the held
    user, and the reverse). Acceptance: overlap >= 80%."""
    track, sessions, _ = load_track_laps(track_id, condition)
    if track is None:
        return None
    users = sorted({entry['user_id'] for entry in sessions})
    if len(users) < 2:
        return {'track_id': track_id, 'error': 'single user'}

    def _corner_positions(entries):
        positions = []
        for _, geo in _valid_geometries(entries):
            positions.extend(c.s_apex % geo.length_m for c in geo.corners)
        return [float(v) for v in positions]

    def _median_set(positions):
        # cluster greedily at the tolerance and keep the median position of
        # each cluster — a light stand-in for Phase 4's consensus corners
        if not positions:
            return []
        positions = sorted(positions)
        clusters = [[positions[0]]]
        for p in positions[1:]:
            if p - clusters[-1][-1] <= tolerance_m:
                clusters[-1].append(p)
            else:
                clusters.append([p])
        return [float(np.median(c)) for c in clusters]

    results = []
    for user in users:
        dev = _median_set(_corner_positions(
            [e for e in sessions if e['user_id'] != user]))
        val = _median_set(_corner_positions(
            [e for e in sessions if e['user_id'] == user]))
        overlap = _match_overlap(dev, val, tolerance_m)
        results.append({
            'held_out_user': user,
            'dev_corners': len(dev),
            'val_corners': len(val),
            'matched': overlap,
            'overlap_pct': round(100.0 * overlap / max(1, min(len(dev), len(val))), 1),
        })
    return {'track_id': track_id, 'tolerance_m': tolerance_m, 'results': results}


def _match_overlap(a, b, tolerance):
    """Greedy nearest matching within tolerance between two corner lists."""
    used = [False] * len(b)
    matched = 0
    for pa in a:
        best, best_d = None, tolerance
        for j, pb in enumerate(b):
            if used[j]:
                continue
            d = abs(pa - pb)
            if d <= best_d:
                best, best_d = j, d
        if best is not None:
            used[best] = True
            matched += 1
    return matched


# ---- golden fixture export -----------------------------------------------------


def export_golden(track_id, picks, out_dir, params=DEFAULT_PARAMS):
    """Write the anonymised golden fixture: metre-space lap arrays (npz)
    plus the engine's expected summaries (json).

    ``picks`` is a list of ``(session_id, lap_number)``. Arrays are stored
    in the track-centred metre frame — no lat/lon, no user metadata — so
    the fixture carries circuit geometry and noise character only.
    """
    track, sessions, _ = load_track_laps(track_id)
    if track is None:
        return None
    by_id = {entry['session_id']: entry for entry in sessions}
    arrays = {}
    expected = {'params': params.__dict__, 'laps': []}
    for i, (session_id, lap_number) in enumerate(picks):
        entry = by_id.get(session_id)
        if entry is None or lap_number not in entry['laps']:
            raise ValueError(f'lap ({session_id}, {lap_number}) not available')
        lap = entry['laps'][lap_number]
        arrays[f'lap{i}_x'] = np.asarray(lap.x, dtype=np.float64)
        arrays[f'lap{i}_y'] = np.asarray(lap.y, dtype=np.float64)
        arrays[f'lap{i}_alt'] = (np.asarray(lap.altitude, dtype=np.float64)
                                 if lap.altitude is not None
                                 else np.full(len(lap.x), np.nan))
        arrays[f'lap{i}_speed'] = (np.asarray(lap.speed, dtype=np.float64)
                                   if lap.speed is not None
                                   else np.full(len(lap.x), np.nan))
        arrays[f'lap{i}_elapsed'] = (np.asarray(lap.elapsed, dtype=np.float64)
                                     if lap.elapsed is not None
                                     else np.full(len(lap.x), np.nan))
        geo = analyze_lap(lap, params, lap_number=lap_number)
        expected['laps'].append({
            'session_id': session_id,
            'lap_number': lap_number,
            'summary': geo.summary(),
        })

    os.makedirs(out_dir, exist_ok=True)
    npz_path = os.path.join(out_dir, 'track_dna_kiltorcan.npz')
    json_path = os.path.join(out_dir, 'track_dna_kiltorcan_expected.json')
    np.savez_compressed(npz_path, **arrays)
    with open(json_path, 'w') as fh:
        json.dump(expected, fh, indent=2)
    return {'npz': npz_path, 'json': json_path, 'laps': len(picks)}


# ---- dispatch ----------------------------------------------------------------


EXPERIMENTS = {
    'lap_counts': experiment_lap_counts,
    'convergence': experiment_convergence,
    'smoothing': experiment_smoothing,
    'gap_merge': experiment_gap_merge,
    'straight_window': experiment_straight_window,
    'radius_method': experiment_radius_method,
    'device': experiment_device,
    'holdout': experiment_holdout,
}


def run(track_id, experiment, **kwargs):
    """Run one experiment by name, print the result, return the dict."""
    func = EXPERIMENTS.get(experiment)
    if func is None:
        raise ValueError(f'unknown experiment {experiment!r}; '
                         f'choose from {sorted(EXPERIMENTS)}')
    result = func(track_id, **kwargs)
    print(json.dumps(result, indent=2, default=str))
    return result
