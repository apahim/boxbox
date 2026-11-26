"""Track DNA confidence and quality classes (plan Phase 8, spec 20).

Pure module (no app imports, no NumPy): turns the Phase 4-6 layer
summaries into the scorecard's confidence layer — per-dimension
quality classes (Measured / Estimated / Unavailable; 'Assumed' is
reserved, see the module docstring of the plan's Section 20.1),
provenance, counts and warnings, plus the card-level evidence block.

Owner-confirmed 2026-11-26 (plan 20.1/20.3):

- **No invented coefficients.** Every threshold reuses a plan anchor:
  >=2 users and >=20 laps (the minimum-data row's *preferred* basis),
  convergence at the Section 15.6 anchors demonstrated at k=50 draws
  (the anchor's calibration basis), elevation cross-user agreement
  +-20% (the Section 18 ascent/descent tolerance).
- **Elevation gates on cross-user agreement, not the scatter flag.**
  Elevation gain is line-invariant, so user disagreement indicates
  measurement error (device wander); on geometry and braking, user
  spread is driving-line variance the D6 hierarchy exists to aggregate
  — reported as evidence, never a class trigger. Measured basis: on
  prod, Whiteriver dry flags 50/50 scatter laps yet its users agree
  within 16% (real relief inflates the detrended std), while
  Kiltorcan dry flags 22/323 yet disagrees by 80% (the u16 wander).
- **Missing is never zero.** A missing channel (no speed -> dimension
  9, no altitude -> dimension 10) is 'Unavailable', keeping the Phase 7
  shape (value/score None).
- Classes are per dimension; a single-user circuit reads Estimated on
  every present dimension (no cross-user corroboration anywhere).
"""

MIN_USERS = 2          # plan minimum-data row: ">=2 users for
#                    # cross-user confidence; single-user = 'Estimated'"
MIN_LAPS = 20          # plan minimum-data row: ">=20 preferred"
CONVERGENCE_DEMONSTRATED_N = 50   # 15.6 anchors' calibration basis
ELEVATION_GAP_MAX = 0.20          # Section 18 ascent/descent tolerance

GEOMETRY_KEYS = (
    'track_length_m', 'straight_pct', 'longest_straight_m',
    'corner_density_per_km', 'slow_corner_prop', 'medium_corner_prop',
    'fast_corner_prop', 'dc_per_km',
)

PROVENANCE = {
    'track_length_m':
        'per-lap GPS measurement -> D6 hierarchical median',
    'straight_pct':
        'per-lap GPS measurement -> D6 hierarchical median',
    'longest_straight_m':
        'per-lap GPS measurement -> D6 hierarchical median',
    'corner_density_per_km':
        'consensus corner set (reconstructed geometry) '
        '-> recurrence-qualified count per km',
    'slow_corner_prop': 'consensus corner set radii -> proportions',
    'medium_corner_prop': 'consensus corner set radii -> proportions',
    'fast_corner_prop': 'consensus corner set radii -> proportions',
    'dc_per_km':
        'per-lap GPS measurement -> D6 hierarchical median',
    'heavy_braking_freq':
        'per-lap speed event detection -> D6 hierarchical median',
    'elevation_gain':
        'per-lap altitude profile -> D6 hierarchical median',
}


def _convergence_verdict(consensus):
    """Demonstrated = real subsampling at k=50 with the 15.6 anchors
    passing (Phase 8 honesty fix: k=n draws are flagged and never back
    the verdict — plan 20.1)."""
    acc = (consensus.get('convergence') or {}).get('acceptance')
    if acc is None:
        return {'demonstrated': False, 'demonstrated_n': None,
                'length_spread_m': None, 'length_ok': None,
                'corner_spread': None, 'corners_ok': None,
                'straight_pct_spread': None, 'straight_ok': None}
    demonstrated_n = acc.get('demonstrated_n')
    demonstrated = (
        demonstrated_n is not None
        and demonstrated_n >= CONVERGENCE_DEMONSTRATED_N
        and bool(acc.get('length_ok')) and bool(acc.get('corners_ok'))
        and bool(acc.get('straight_ok')))
    return {'demonstrated': demonstrated,
            'demonstrated_n': demonstrated_n,
            'length_spread_m': acc.get('length_spread_m'),
            'length_ok': acc.get('length_ok'),
            'corner_spread': acc.get('corner_spread'),
            'corners_ok': acc.get('corners_ok'),
            'straight_pct_spread': acc.get('straight_pct_spread'),
            'straight_ok': acc.get('straight_ok')}


def _user_medians(per_user_metric):
    """{user_id: median} from a layer's per-user spread section."""
    if not per_user_metric:
        return {}
    return {uid: stats.get('median')
            for uid, stats in per_user_metric.items()
            if stats.get('median') is not None}


def _cross_user_gap(medians):
    """(max - min) / min over per-user medians, or None when undefined
    (fewer than 2 users, or a zero minimum)."""
    values = [v for v in medians.values() if v is not None]
    if len(values) < 2 or min(values) <= 0:
        return None
    return (max(values) - min(values)) / min(values)


def _geometry_confidence(key, n_users, n_laps, conv):
    warnings = []
    if n_users < MIN_USERS:
        warnings.append(f'single_user: {n_users} user')
    if n_laps < MIN_LAPS:
        warnings.append(f'thin_data: {n_laps} laps (<{MIN_LAPS})')
    if not conv['demonstrated']:
        if conv['demonstrated_n'] is None:
            warnings.append(
                'convergence_not_demonstrated: no subsampling evidence')
        elif conv['demonstrated_n'] < CONVERGENCE_DEMONSTRATED_N:
            warnings.append(
                f"convergence_not_demonstrated: demonstrated at "
                f"{conv['demonstrated_n']}, not "
                f"{CONVERGENCE_DEMONSTRATED_N}")
        else:
            warnings.append(
                'convergence_anchors_failed: spreads exceed the 15.6 '
                'anchors at k=50')
    return {
        'key': key,
        'quality': 'Estimated' if warnings else 'Measured',
        'provenance': PROVENANCE[key],
        'counts': {'n_users': n_users, 'n_laps': n_laps},
        'warnings': warnings,
    }


def _braking_confidence(braking):
    key = 'heavy_braking_freq'
    value = braking['dimensions']['heavy_braking_freq']['value']
    n_speed = braking.get('n_laps_with_speed') or 0
    if value is None or n_speed == 0:
        return {'key': key, 'quality': 'Unavailable',
                'provenance': PROVENANCE[key],
                'counts': {'n_users': 0, 'n_laps': 0},
                'warnings': ['no_speed_channel']}
    medians = _user_medians(braking.get('per_user', {}).get(key))
    n_users = len(medians)
    warnings = []
    if n_users < MIN_USERS:
        warnings.append(f'single_user: {n_users} user')
    if n_speed < MIN_LAPS:
        warnings.append(f'thin_data: {n_speed} laps (<{MIN_LAPS})')
    coverage = braking.get('speed_coverage')
    if coverage is not None and coverage < 1.0:
        warnings.append(f'low_speed_coverage: {coverage}')
    return {
        'key': key,
        'quality': 'Estimated' if (n_users < MIN_USERS
                                   or n_speed < MIN_LAPS) else 'Measured',
        'provenance': PROVENANCE[key],
        'counts': {'n_users': n_users, 'n_laps': n_speed},
        'warnings': warnings,
    }


def _elevation_confidence(elevation):
    key = 'elevation_gain'
    value = elevation['dimensions']['elevation_gain']['value']
    n_alt = elevation.get('n_laps_with_altitude') or 0
    if value is None or n_alt == 0:
        return {'key': key, 'quality': 'Unavailable',
                'provenance': PROVENANCE[key],
                'counts': {'n_users': 0, 'n_laps': 0},
                'warnings': ['no_altitude_channel']}
    medians = _user_medians(elevation.get('per_user', {}).get(key))
    n_users = len(medians)
    gap = _cross_user_gap(medians)
    warnings = []
    if n_users < MIN_USERS:
        warnings.append(f'single_user: {n_users} user')
    elif gap is None:
        warnings.append('cross_user_gap: undefined (zero-median user)')
    elif gap > ELEVATION_GAP_MAX:
        warnings.append(f'cross_user_gap: {gap:.2f} > '
                        f'{ELEVATION_GAP_MAX:.2f}')
    measured = n_users >= MIN_USERS and gap is not None \
        and gap <= ELEVATION_GAP_MAX
    return {
        'key': key,
        'quality': 'Measured' if measured else 'Estimated',
        'provenance': PROVENANCE[key],
        'counts': {'n_users': n_users, 'n_laps': n_alt},
        'warnings': warnings,
    }


def assign_confidence(consensus, braking, elevation, dataset=None):
    """Layer summaries -> (per-dimension confidence keyed by dimension
    key, card-level evidence block).

    ``consensus``/``braking``/``elevation`` are the layer ``summary()``
    dicts exactly as the compute runner produces them (and as
    ``support_json`` stores them); ``dataset`` is the runner's dataset
    dict (users, devices, ...). Pure function — no DB, no globals.
    """
    conv = _convergence_verdict(consensus)
    n_users = consensus.get('n_users') or 0
    n_laps = consensus.get('n_laps') or 0

    dimensions = {}
    for key in GEOMETRY_KEYS:
        dimensions[key] = _geometry_confidence(key, n_users, n_laps, conv)
    dimensions['heavy_braking_freq'] = _braking_confidence(braking)
    dimensions['elevation_gain'] = _elevation_confidence(elevation)

    # card-level evidence: per-user medians and cross-user gaps per
    # layer metric (evidence only — geometry/braking gaps are
    # driving-line variance, never class triggers; the elevation gap
    # additionally gates its dimension above)
    per_user_medians = {}
    cross_user_gaps = {}
    for metric, users in (consensus.get('per_user') or {}).items():
        medians = _user_medians(users)
        if medians:
            per_user_medians[metric] = medians
            cross_user_gaps[metric] = _cross_user_gap(medians)
    for summary, metric in ((braking, 'heavy_braking_freq'),
                            (elevation, 'elevation_gain')):
        medians = _user_medians((summary.get('per_user') or {}).get(metric))
        if medians:
            per_user_medians[metric] = medians
            cross_user_gaps[metric] = _cross_user_gap(medians)

    scatter = ((elevation.get('evidence') or {}).get('scatter') or {})
    flagged = scatter.get('flagged_laps')
    n_alt = elevation.get('n_laps_with_altitude') or 0
    scatter_fraction = (round(flagged / n_alt, 3)
                        if flagged is not None and n_alt else None)

    devices = (dataset or {}).get('devices') or []
    card = {
        'n_users': n_users,
        'n_sessions': consensus.get('n_sessions'),
        'n_laps': n_laps,
        'devices': devices,
        'single_device': len(devices) == 1,
        'convergence': conv,
        'per_user_medians': per_user_medians,
        'cross_user_gaps': cross_user_gaps,
        'elevation_scatter_flagged_fraction': scatter_fraction,
    }
    return dimensions, card
