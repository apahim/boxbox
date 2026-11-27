"""Track DNA reference-lap circuit builder.

The single-lap successor to the Phase 4 consensus layer: the circuit
geometry object (``TrackConsensus``) that the braking and elevation
layers consume, built directly from ONE admin-selected reference lap's
engine output instead of a multi-driver consensus.

NumPy only — no app imports, matching the ``scripts/analysis/``
convention.

Design (owner-confirmed 2026-11-27):

- **One track = one layout** (extra layouts are separate ``Track``
  rows) and **one reference lap** defines the geometry: the track's
  scorecard is a statement about the admin's chosen lap, not a
  statistical consensus across drivers. The multi-lap alignment,
  recurrence clustering and convergence machinery of the consensus
  layer is deleted; this module keeps only what the downstream layers
  still consume.
- **The dataclasses are unchanged** (``TrackConsensus``,
  ``ConsensusLap``, ``ConsensusCorner``): braking/elevation read
  ``laps``, ``length_m``, ``shifts_m`` and ``condition`` off the
  object, so a single-lap instance (``shifts_m = [0]``,
  ``condition = None``) lets both layers run unmodified.
- **Dimensions 1-8 come from the lap's own ``LapGeometry``** —
  arclength, straight fraction, longest straight, corner set with
  radius classes, direction changes — all already computed per-lap by
  the frozen Phase 3 engine.
- **Shared aggregation utilities** (``_hierarchical``,
  ``_user_spread``, ``_recurrence_clusters`` …) live here: the braking
  and elevation layers import them from this module.
"""

import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from scripts.analysis.track_dna import LapGeometry, robust_bbox

# Radius classes for dimensions 5-7, recalibrated 2026-11-27 for
# rental karts against a production corner audit (best lap on each of
# the five official tracks, 44 corners): radii cluster 11-14 m
# (hairpins, apex 40-47 km/h), 15-25 m (mid corners) and 26 m+
# (sweepers, apex 54-67 km/h). The old provisional 20/40 thresholds
# left 'fast' essentially empty (1 of 44 corners) on rental-scale
# circuits.
SLOW_CORNER_MAX_M = 15.0
MEDIUM_CORNER_MAX_M = 26.0


@dataclass
class ConsensusLap:
    """One valid lap plus the metadata the aggregation needs."""

    user_id: int
    session_id: int
    geometry: LapGeometry
    lap_number: int | None = None
    device: str = 'unknown'    # session data_source


@dataclass
class ConsensusCorner:
    """One corner of the circuit.

    ``s_*`` are lap-frame metre positions (``s_apex`` in
    ``[0, lap length)``; ``s_start``/``s_end`` unwrapped around the
    apex and may fall outside the lap). For a reference-lap circuit
    ``n_laps``/``member_corners`` are 1 and ``recurrence`` 1.0 — the
    fields stay so the braking/elevation summaries keep their shape.
    """

    s_apex: float
    s_start: float
    s_end: float
    delta_theta_deg: float
    radius_m: float
    sign: int
    radius_class: str
    n_laps: int
    recurrence: float
    member_corners: int
    support_by_user: dict


@dataclass
class TrackConsensus:
    """Circuit geometry for one track, built from the reference lap."""

    condition: str | None           # always None (reference-lap cards
                                    # carry no wet/dry split)
    laps: list                      # ConsensusLap inputs used (non-spun)
    spun: list                      # ConsensusLap inputs excluded (spun)
    length_m: float                 # dim 1
    straight_pct: float             # dim 2
    longest_straight_m: float       # dim 3
    corner_count: int               # dim 4
    corner_density_per_km: float    # dim 4
    corner_props: dict              # dims 5-7: {'slow','medium','fast'} %
    dc_per_km: float                # dim 8
    dc_count_median: float          # dim 8 evidence
    dc_consensus_count: int         # dim 8 evidence
    corner_count_per_lap_median: float
    grid: np.ndarray                # resample grid (m)
    x: np.ndarray                   # trajectory (the lap's raw
    y: np.ndarray                   #  resampled positions)
    arclength_m: float              # trajectory polyline arclength
    bbox: tuple
    corners: list                   # ConsensusCorner, sorted by s_apex
    shifts_m: np.ndarray            # per-lap alignment shift (m); [0]
    align_r: np.ndarray             # per-lap alignment correlation; [1]
    seed: dict                      # reference lap identity
    per_user: dict                  # per-metric per-user spreads
    cross_check: dict               # engine reading of the lap line
    convergence: dict
    data_quality: dict

    def summary(self):
        """JSON-serialisable summary (card-builder input)."""
        def _r(value, nd=2):
            return round(float(value), nd)

        # per-corner apex speeds and the lap's max speed (learning-layer
        # material: humans read km/h, not radii). None without a speed
        # channel — never a fabricated zero.
        geo = self.laps[0].geometry
        speed = getattr(geo, 'speed', None)
        max_speed_kmh = None
        if speed is not None and len(speed):
            vmax = float(np.nanmax(speed))
            if np.isfinite(vmax):
                max_speed_kmh = _r(vmax * 3.6, 1)

        def _apex_speed(c):
            if speed is None or not len(speed):
                return None
            s_wrap = float(c.s_apex) % float(geo.length_m)
            v = float(np.interp(s_wrap, geo.s, speed))
            if not np.isfinite(v):
                return None
            return _r(v * 3.6, 1)

        corners = [{
            's_apex': _r(c.s_apex), 's_start': _r(c.s_start),
            's_end': _r(c.s_end),
            'delta_theta_deg': _r(c.delta_theta_deg, 1),
            'radius_m': _r(c.radius_m), 'sign': int(c.sign),
            'class': c.radius_class, 'n_laps': int(c.n_laps),
            'recurrence': _r(c.recurrence, 3),
            'member_corners': int(c.member_corners),
            'apex_speed_kmh': _apex_speed(c),
            'support_by_user': {int(u): _r(v, 3)
                                for u, v in sorted(c.support_by_user.items())},
        } for c in self.corners]

        cross = dict(self.cross_check)
        dims = {
            'track_length_m': {
                'value': _r(self.length_m),
                'evidence': {'consensus_arclength_m': _r(self.arclength_m)},
            },
            'straight_pct': {
                'value': _r(self.straight_pct),
                'evidence': {'consensus_line_pct': cross.get('straight_pct')},
            },
            'longest_straight_m': {
                'value': _r(self.longest_straight_m),
                'evidence': {'consensus_line_longest_m':
                             cross.get('longest_straight_m')},
            },
            'corner_count': {
                'value': int(self.corner_count),
                'evidence': {
                    'per_lap_median': _r(self.corner_count_per_lap_median),
                    'consensus_line_count': cross.get('corner_count'),
                },
            },
            'corner_density_per_km': {'value': _r(self.corner_density_per_km,
                                                  3)},
            'slow_corner_prop': {'value': _r(self.corner_props['slow'])},
            'medium_corner_prop': {'value': _r(self.corner_props['medium'])},
            'fast_corner_prop': {'value': _r(self.corner_props['fast'])},
            'dc_per_km': {'value': _r(self.dc_per_km, 3)},
            'dc_count': {
                'value': _r(self.dc_count_median),
                'evidence': {
                    'consensus_set_count': int(self.dc_consensus_count),
                    'consensus_line_count': cross.get('dc_count'),
                },
            },
        }
        per_user = {
            metric: {int(u): {'n_laps': stats['n_laps'],
                              'median': _r(stats['median']),
                              'p10': _r(stats['p10']),
                              'p90': _r(stats['p90'])}
                     for u, stats in sorted(users.items())}
            for metric, users in self.per_user.items()
        }
        return {
            'condition': self.condition,
            'max_speed_kmh': max_speed_kmh,
            'n_users': len({l.user_id for l in self.laps}),
            'n_sessions': len({l.session_id for l in self.laps}),
            'n_laps': len(self.laps),
            'n_spun_excluded': len(self.spun),
            'seed': self.seed,
            'alignment': {
                'shift_m': {
                    'min': _r(np.min(self.shifts_m)),
                    'median': _r(np.median(self.shifts_m)),
                    'max': _r(np.max(self.shifts_m)),
                },
                'correlation': {
                    'min': _r(np.min(self.align_r), 3),
                    'median': _r(np.median(self.align_r), 3),
                },
            },
            'dimensions': dims,
            'corners': corners,
            'consensus_trajectory': {
                'length_m': _r(self.length_m),
                'grid_points': int(self.grid.size),
                'arclength_m': _r(self.arclength_m),
                'bbox': [_r(v) for v in self.bbox],
            },
            'cross_check': cross,
            'per_user': per_user,
            'convergence': self.convergence,
            'data_quality': self.data_quality,
        }


# ---- circular clustering (braking zones) ------------------------------------


def _circular_clusters(positions, tolerance, circumference):
    """Deterministic single-linkage clustering on a circle.

    The circle is cut at the largest gap between sorted positions (so
    no cluster bridges the cut spuriously), then points chain while
    each stays within ``tolerance`` of the cluster's last member.
    Returns a list of index lists into ``positions``.
    """
    n = len(positions)
    if n == 0:
        return []
    order = np.argsort(positions, kind='stable')
    ps = np.asarray(positions, dtype=float)[order]
    if n == 1:
        return [[int(order[0])]]
    gaps = np.empty(n)
    gaps[:-1] = np.diff(ps)
    gaps[-1] = circumference - (ps[-1] - ps[0])
    cut = int(np.argmax(gaps))              # gap after index `cut`
    rot = (cut + 1) % n
    seq = np.concatenate([ps[rot:], ps[:rot]])
    idx = np.concatenate([order[rot:], order[:rot]])
    seq_un = seq - seq[0]
    seq_un[seq_un < 0.0] += circumference
    clusters = []
    current = [0]
    for i in range(1, n):
        if seq_un[i] - seq_un[current[-1]] <= tolerance:
            current.append(i)
        else:
            clusters.append(current)
            current = [i]
    clusters.append(current)
    return [[int(idx[i]) for i in c] for c in clusters]


def _split_chain(members, positions, lap_ids, min_laps, min_gap,
                 circumference):
    """Recursively split one single-linkage chain at its widest valley.

    The chain is traversed starting after its own largest circular gap
    (the gap facing the rest of the circle, so seam-wrapping chains
    unwrap correctly). It splits at the widest INTERNAL gap when that
    gap is at least ``min_gap`` AND both pieces are independently
    supported by >= ``min_laps`` distinct laps.
    """
    if len(members) < 2:
        return [list(members)]
    order = sorted(members, key=lambda j: positions[j])
    ps = [positions[j] for j in order]
    m = len(order)
    gaps = [ps[i + 1] - ps[i] for i in range(m - 1)]
    gaps.append(circumference - (ps[-1] - ps[0]))
    boundary = int(np.argmax(gaps))            # gap after `boundary`
    rot = (boundary + 1) % m
    order = order[rot:] + order[:rot]
    ps = [positions[j] for j in order]
    widest = 0.0
    cut = -1
    for i in range(m - 1):
        d = ps[i + 1] - ps[i]
        if d < 0.0:
            d += circumference
        if d > widest:
            widest = d
            cut = i
    if (cut >= 0 and widest >= min_gap
            and len({lap_ids[j] for j in order[:cut + 1]}) >= min_laps
            and len({lap_ids[j] for j in order[cut + 1:]}) >= min_laps):
        return (_split_chain(order[:cut + 1], positions, lap_ids,
                             min_laps, min_gap, circumference)
                + _split_chain(order[cut + 1:], positions, lap_ids,
                               min_laps, min_gap, circumference))
    return [order]


def _recurrence_clusters(positions, lap_ids, tolerance, circumference,
                         min_laps, min_gap):
    """Recurrence-qualified clusters on a circle: single-linkage chains
    (``tolerance`` link distance), then valley splitting where both
    pieces independently pass ``min_laps`` distinct laps."""
    clusters = []
    for chain in _circular_clusters(positions, tolerance, circumference):
        clusters.extend(_split_chain(chain, positions, lap_ids, min_laps,
                                     min_gap, circumference))
    return clusters


# ---- aggregation (D6) ----------------------------------------------------------


def _hierarchical(values, laps):
    """Equal-user-weighted median: lap -> session -> user -> circuit.

    With a single reference lap every level is the value itself.
    Returns ``(circuit_median, {user_id: {'median', 'n_sessions',
    'n_laps'}})``.
    """
    by_session = {}
    n_laps_by_user = defaultdict(int)
    for lap, value in zip(laps, values):
        by_session.setdefault((lap.user_id, lap.session_id),
                              []).append(value)
        n_laps_by_user[lap.user_id] += 1
    by_user = defaultdict(list)
    for (uid, _sid), vals in by_session.items():
        by_user[uid].append(float(np.median(vals)))
    per_user = {uid: {'median': float(np.median(vals)),
                      'n_sessions': len(vals),
                      'n_laps': n_laps_by_user[uid]}
                for uid, vals in by_user.items()}
    circuit = (float(np.median([v['median'] for v in per_user.values()]))
               if per_user else None)
    return circuit, per_user


def _user_spread(laps, values):
    """Flat per-user spread (median + p10/p90 across the user's laps)."""
    by_user = defaultdict(list)
    for lap, value in zip(laps, values):
        by_user[lap.user_id].append(value)
    return {uid: {'median': float(np.median(v)),
                  'p10': float(np.percentile(v, 10)),
                  'p90': float(np.percentile(v, 90)),
                  'n_laps': len(v)}
            for uid, v in sorted(by_user.items())}


def _circular_median(values, circumference):
    """Median of positions on a circle (clusters are tolerance-wide)."""
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ref = float(np.mean(values))
    rel = [(v - ref + circumference / 2.0) % circumference - circumference / 2.0
           for v in values]
    return (ref + float(np.median(rel))) % circumference


def _polyline_arclength(x, y):
    """Arclength of a closed polyline (closing segment included)."""
    steps = np.hypot(np.diff(x), np.diff(y))
    closing = math.hypot(x[0] - x[-1], y[0] - y[-1])
    return float(steps.sum() + closing)


# ---- circuit construction -------------------------------------------------------


def _radius_class(radius_m):
    if radius_m < SLOW_CORNER_MAX_M:
        return 'slow'
    if radius_m < MEDIUM_CORNER_MAX_M:
        return 'medium'
    return 'fast'


def _dc_count(corners, gap_m, circumference):
    """Direction changes in a corner set sorted by apex: consecutive
    opposite-sign corners with an edge-to-edge gap <= ``gap_m``
    (mirrors the engine's per-lap rule)."""
    m = len(corners)
    if m < 2:
        return 0
    count = 0
    for i in range(m):
        a = corners[i]
        b = corners[(i + 1) % m]
        gap = b.s_start - a.s_end
        if i == m - 1:
            gap += circumference
        if a.sign != b.sign and 0.0 <= gap <= gap_m:
            count += 1
    return count


def reference_consensus(record, engine_params):
    """Build the circuit geometry object from ONE reference lap.

    ``record`` is a :class:`ConsensusLap` whose ``geometry`` is a valid
    (non-spun) lap from ``analyze_session``. The lap IS the circuit:
    the trajectory is its raw resampled positions, the corner set is
    its own corners, and dimensions 1-8 read its ``LapGeometry``
    directly. Raises ``ValueError`` when the lap is spun.
    """
    geo = record.geometry
    if geo.spun:
        raise ValueError('reference lap is spun: no circuit geometry')

    corners = [ConsensusCorner(
        s_apex=float(c.s_apex), s_start=float(c.s_start),
        s_end=float(c.s_end), delta_theta_deg=float(c.delta_theta_deg),
        radius_m=float(c.radius_m) if math.isfinite(c.radius_m)
        else float('inf'),
        sign=int(c.sign), radius_class=_radius_class(c.radius_m),
        n_laps=1, recurrence=1.0, member_corners=1,
        support_by_user={int(record.user_id): 1.0},
    ) for c in geo.corners]
    corners.sort(key=lambda c: c.s_apex)

    corner_count = len(corners)
    classes = [c.radius_class for c in corners]
    props = {name: (100.0 * classes.count(name) / corner_count
                    if corner_count else 0.0)
             for name in ('slow', 'medium', 'fast')}

    engine = geo.summary()
    cross_check = {
        'length_m': engine['length_m'],
        'corner_count': len(engine['corners']),
        'straight_pct': round(100.0 * geo.straight_fraction, 2),
        'longest_straight_m': engine['longest_straight_m'],
        'dc_count': len(engine['direction_changes']),
        'spun': engine['spun'],
        'engine_summary': engine,
    }

    per_user = {
        'track_length_m': _user_spread([record], [geo.length_m]),
        'straight_pct': _user_spread(
            [record], [100.0 * geo.straight_fraction]),
        'longest_straight_m': _user_spread(
            [record], [float(geo.longest_straight_m)]),
        'corner_count': _user_spread([record], [geo.corner_count]),
        'dc_per_km': _user_spread([record], [geo.dc_per_km]),
    }

    return TrackConsensus(
        condition=None,
        laps=[record],
        spun=[],
        length_m=float(geo.length_m),
        straight_pct=100.0 * geo.straight_fraction,
        longest_straight_m=float(geo.longest_straight_m),
        corner_count=corner_count,
        corner_density_per_km=geo.corner_density_per_km,
        corner_props=props,
        dc_per_km=geo.dc_per_km,
        dc_count_median=float(geo.dc_count),
        dc_consensus_count=_dc_count(corners, engine_params.dc_gap_m,
                                     geo.length_m),
        corner_count_per_lap_median=float(geo.corner_count),
        grid=np.asarray(geo.s, dtype=float),
        x=np.asarray(geo.x, dtype=float),
        y=np.asarray(geo.y, dtype=float),
        arclength_m=_polyline_arclength(geo.x, geo.y),
        bbox=robust_bbox(geo.x, geo.y),
        corners=corners,
        shifts_m=np.zeros(1),
        align_r=np.ones(1),
        seed={'session_id': record.session_id,
              'lap_number': record.lap_number},
        per_user=per_user,
        cross_check=cross_check,
        convergence={},
        data_quality={'spun_laps': [], 'mixed_sign_corners': 0},
    )
