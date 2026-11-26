"""Track DNA consensus layer (plan Phase 4).

Builds the multi-driver consensus driving line and the circuit-level
geometry dimensions 1-8 from the Phase 3 per-lap engine output
(``scripts.analysis.track_dna.analyze_session``). NumPy only — no app
imports, matching the ``scripts/analysis/`` convention.

Design (owner-approved 2026-11-26, plan Sections 4.5/5/15.6):

- **Corner set — recurrence clustering is canonical** (decision D6's
  "recurrence-qualified consensus objects"): per-lap corner apexes are
  mapped into the consensus frame and clustered circularly in two
  stages. Single-linkage chains (30 m link distance) keep wide corners
  whole — a real corner's apexes can spread well beyond 30 m across
  driving lines, and a diameter-capped clusterer splits such corners
  into sub-threshold pieces. Recurrence-qualified valley splitting
  then separates corners that chaining bridges: a chain splits at its
  widest internal gap only when the gap is at least the engine's own
  corner-merge distance (10 m — below that two consensus corners have
  no per-lap meaning, and alignment jitter can never fragment
  coincident apexes) AND both pieces are independently supported by
  >= 50% of laps — so bridged 100%-support corner pairs split, while
  a wide corner held by less than 2x the threshold cannot. The
  consensus trajectory is the geometric frame, and re-running the
  frozen engine on it is recorded as a *cross-check*, satisfying both
  plan readings (Section 4.5 recurrence objects and Section 5.3
  "consensus feeds corner set/straights/DCs").
- **Dimension sourcing**: dimensions 1/2/3/8 (length, straight%,
  longest straight, DC frequency) are equal-user-weighted hierarchical
  medians — lap -> session -> user -> circuit (D6: no per-lap pooling;
  one user holds 79% of Kiltorcan laps). Dimensions 4-7 (corner count,
  density, proportions) come from the consensus corner set so the
  proportions sum to 100% exactly (independent per-class medians do not
  — the PoC measured 6+2+0 of 7 corners).
- **S/F alignment**: each lap's curvature profile (the engine's
  seam-free, periodic ``kappa`` — the unwrapped heading carries a 2*pi
  step at the lap's s=0 seam and cannot be cross-correlated across
  seam-shifted laps) is sampled on a common normalized-arclength grid
  and circularly cross-correlated (FFT) against a seed lap (the valid
  lap closest to the median arclength). Near-tied shifts resolve to the
  one closest to zero shift — the plan's "+-5 m start jitter" refinement
  as a soft preference rather than a hard search cap, so seam-shifted
  laps (rolling a lap's s=0 anywhere) still re-anchor exactly. The
  zero-shift preference is what keeps symmetric layouts (a stadium's
  two-fold symmetry) from locking onto an alias half a lap away.
- **Consensus trajectory**: per-grid-point hierarchical median of the
  laps' RAW resampled positions (not ``x_smooth``) — the plan's literal
  "resampled trajectory", and it keeps the consensus arclength
  comparable to dimension 1. Cross-lap medians cancel most per-lap GPS
  noise, so the consensus arclength is expected to read slightly BELOW
  the per-lap median arclength (noise inflation); the gap is recorded
  as the Section 15.6 supporting evidence, not a bug.
- **Recurrence is counted per lap** (plan Section 4.5/6 constants),
  with per-user support fractions reported on every consensus corner so
  single-user dominance is visible in the evidence.
- **Spun laps are data-quality signals, not geometry inputs** (plan
  15.5): excluded from every consensus input and median, reported
  separately. Expected ~always empty on real data.
- **Wet is a separate bucket, never mixed** (D1/D6): the caller passes
  one condition's laps at a time.
- **Convergence acceptance** (plan 15.6, re-anchored) gates on the same
  basis the anchor was calibrated on: seeded draws' flat per-lap
  medians (length/straight%/longest/DC) plus the recurrence corner
  count — the Phase-3 ``experiment_convergence`` protocol. The
  delivered hierarchical (equal-user-weighted) values are recorded per
  draw as non-gating evidence, because a draw also resamples the user
  composition, a variance the anchor never measured.

Radius classes for dimensions 5-7 (slow < 20 m, medium 20-40 m,
fast >= 40 m) are PROVISIONAL — the original requirements spec is not
in the repo; flagged in the Phase 4 delivery notes for owner
confirmation before Phase 7 freezes normalisation anchors.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from scripts.analysis.track_dna import (
    DEFAULT_PARAMS,
    LapGeometry,
    LapInput,
    analyze_lap,
    robust_bbox,
)

# Convergence acceptance (plan 15.6, re-anchored): at n=50 seeded draws
# the spread of the anchor-basis values (flat per-lap medians for
# length/straight%/longest/DC + the recurrence corner count) must stay
# within these.
CONVERGENCE_LENGTH_M = 6.0
CONVERGENCE_CORNERS = 1.0
CONVERGENCE_STRAIGHT_PP = 2.0


@dataclass(frozen=True)
class ConsensusParams:
    """v1.0 consensus parameters (plan Sections 4.5/5/6 + 15.6).

    Deliberately a sibling of the engine's ``TrackDNAParams`` rather
    than extra fields on it: the engine is frozen at v1.0 (owner-acked
    15.6) and ``DEFAULT_PARAMS.__dict__`` is pinned byte-for-byte by the
    golden regression test.
    """

    corner_recurrence: float = 0.5     # min fraction of laps supporting
                                       # a consensus corner
    corner_cluster_m: float = 30.0     # circular apex cluster link
                                       # tolerance (single linkage)
    align_grid: int = 1024             # normalized-arclength kappa grid
    align_r_tol: float = 0.005         # near-tie band for the zero-shift
                                       # preference (correlation units)
    slow_corner_max_m: float = 20.0    # PROVISIONAL radius classes (see
    medium_corner_max_m: float = 40.0  # module docstring)
    convergence_sizes: tuple = (1, 3, 5, 10, 20, 50, None)
    convergence_draws: int = 20
    convergence_seed: int = 0


DEFAULT_CONSENSUS_PARAMS = ConsensusParams()


@dataclass
class ConsensusLap:
    """One valid lap plus the metadata the D6 hierarchy needs."""

    user_id: int
    session_id: int
    geometry: LapGeometry
    lap_number: int | None = None


@dataclass
class ConsensusCorner:
    """One consensus corner: a recurrence-qualified apex cluster.

    ``s_*`` are positions in the consensus frame (metres; ``s_apex`` in
    ``[0, consensus length)``, ``s_start``/``s_end`` unwrapped around
    the apex and may fall outside the lap). ``n_laps`` counts supporting
    laps (a lap counts once even if it contributed two corners);
    ``member_corners`` counts all contributing corner objects.
    ``support_by_user`` maps user id -> supporting laps / that user's
    laps, exposing single-user dominance in the evidence.
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
    """Full Phase 4 result for one track configuration and condition."""

    condition: str | None
    laps: list                     # ConsensusLap inputs used (non-spun)
    spun: list                     # ConsensusLap inputs excluded (spun)
    length_m: float                # dim 1: hierarchical median arclength
    straight_pct: float            # dim 2
    longest_straight_m: float      # dim 3
    corner_count: int              # dim 4 (consensus set)
    corner_density_per_km: float   # dim 4
    corner_props: dict             # dims 5-7: {'slow','medium','fast'} %
    dc_per_km: float               # dim 8
    dc_count_median: float         # dim 8 evidence (per-lap hierarchical)
    dc_consensus_count: int        # dim 8 evidence (consensus corner set)
    corner_count_per_lap_median: float
    grid: np.ndarray               # consensus grid positions (m)
    x: np.ndarray                  # consensus trajectory (median line)
    y: np.ndarray
    arclength_m: float             # consensus polyline arclength (15.6)
    bbox: tuple
    corners: list                  # ConsensusCorner, sorted by s_apex
    shifts_m: np.ndarray           # per-lap alignment shift (m)
    align_r: np.ndarray            # per-lap alignment correlation
    seed: dict                     # seed lap identity
    per_user: dict                 # per-metric per-user spreads
    cross_check: dict              # engine v1.0 on the consensus line
    convergence: dict
    data_quality: dict

    def summary(self):
        """JSON-serialisable summary (runner output, Phase 7 input)."""
        def _r(value, nd=2):
            return round(float(value), nd)

        corners = [{
            's_apex': _r(c.s_apex), 's_start': _r(c.s_start),
            's_end': _r(c.s_end),
            'delta_theta_deg': _r(c.delta_theta_deg, 1),
            'radius_m': _r(c.radius_m), 'sign': int(c.sign),
            'class': c.radius_class, 'n_laps': int(c.n_laps),
            'recurrence': _r(c.recurrence, 3),
            'member_corners': int(c.member_corners),
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


# ---- alignment ---------------------------------------------------------------


def _curvature_profile(geo, n_points):
    """Curvature profile sampled at ``n_points`` equal normalized-
    arclength positions (periodic: s = length wraps back to s = 0).

    The engine's ``kappa`` is the alignment signature of choice: it is
    genuinely periodic (the unwrapped heading carries a 2*pi seam step
    wherever the lap's s=0 falls, which corrupts cross-correlation of
    seam-shifted laps), seam-invariant, and rotation-invariant in the
    GPS frame (per-session datum offsets do not bias it).
    """
    kappa = np.asarray(geo.kappa, dtype=float)
    s = np.asarray(geo.s, dtype=float)
    length = geo.length_m
    s_ext = np.concatenate([s, [length]])
    k_ext = np.concatenate([kappa, [kappa[0]]])
    q = (np.arange(n_points) / n_points) * length
    return np.interp(q, s_ext, k_ext)


def _align_shift(profile, seed_profile, params):
    """Best circular shift of ``profile`` relative to ``seed_profile``.

    Both are equal-length curvature profiles on the normalized lap. The
    shift maximises the circular cross-correlation (mean-centred, so
    corner/straight balance differences do not bias it). Among shifts
    whose correlation ties the best within ``align_r_tol``, the one
    closest to zero shift wins — real S/F jitter is a few metres, and
    the preference is what disambiguates symmetric layouts (their
    correlation ties at the true shift and its symmetry alias).

    Returns ``(shift_fraction, best_correlation)`` with the fraction in
    (-0.5, 0.5]: the lap's position at normalized parameter ``t + frac``
    is the consensus-frame position at ``t``.
    """
    a = np.asarray(profile, dtype=float)
    b = np.asarray(seed_profile, dtype=float)
    n = a.size
    a = a - a.mean()
    b = b - b.mean()
    na = float(np.sum(a * a))
    nb = float(np.sum(b * b))
    if na <= 0.0 or nb <= 0.0:
        return 0.0, 0.0
    corr = np.fft.ifft(np.fft.fft(a) * np.conj(np.fft.fft(b))).real
    r = corr / math.sqrt(na * nb)
    best = float(np.max(r))
    candidates = np.flatnonzero(r >= best - params.align_r_tol)

    def rank(d):
        d = int(d)
        return (min(d, n - d), d)

    d = min((int(c) for c in candidates), key=rank)
    frac = d / n
    if frac > 0.5:
        frac -= 1.0
    return frac, best


def _sample_positions(geo, frac, grid_t):
    """Lap positions at normalized parameters ``(grid_t + frac) % 1``.

    Uses the lap's raw resampled positions (not smoothed) and periodic
    interpolation across the closing segment.
    """
    length = geo.length_m
    s = ((grid_t + frac) % 1.0) * length
    s_ext = np.concatenate([geo.s, [length]])
    x = np.interp(s, s_ext, np.concatenate([geo.x, [geo.x[0]]]))
    y = np.interp(s, s_ext, np.concatenate([geo.y, [geo.y[0]]]))
    return x, y


def _map_corner(geo, corner, frac, consensus_length):
    """Map one lap corner into the consensus frame.

    Returns ``(m_apex, d_start, d_end)``: the apex position in consensus
    metres (mod the consensus length) and the corner's edge offsets from
    its apex in metres. The offsets are computed with modular unwrapping
    so seam-wrapping corners (s_end > lap length, modded s_apex) keep
    their true relative extents.
    """
    length = geo.length_m
    u = ((corner.s_apex / length) - frac) % 1.0
    m_apex = u * consensus_length
    d_apex = (corner.s_apex - corner.s_start) % length   # start -> apex
    d_start = -d_apex
    d_end = corner.s_end - (corner.s_start + d_apex)
    return m_apex, d_start, d_end


# ---- circular statistics -------------------------------------------------------


def _circular_clusters(positions, tolerance, circumference):
    """Deterministic single-linkage clustering on a circle.

    The circle is cut at the largest gap between sorted positions (so
    no cluster bridges the cut spuriously), then points chain while
    each stays within ``tolerance`` of the cluster's last member —
    the validated Phase-3 holdout recipe. Single linkage is deliberate:
    a real corner's apex positions can spread well beyond the tolerance
    across driving lines (Kiltorcan's s~160 corner spans 43 m p10-p90
    with 8 m gaps), and a diameter-capped variant splits that into
    sub-threshold pieces, dropping real corners from the consensus set.
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
    gap is at least ``min_gap`` — the engine's own within-lap corner
    merge distance, below which two consensus corners have no per-lap
    meaning, and which stops alignment-quantisation jitter from ever
    fragmenting coincident apexes — AND both pieces are independently
    supported by >= ``min_laps`` distinct laps. The recurrence test
    itself thus decides whether a valley separates two real corners
    (both sides pass) or runs through one wide corner (a corner
    supported by less than 2x the threshold can never split). Only
    the widest gap is ever tried, so dense apex masses never fragment.
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
    """Recurrence-qualified corner clusters on a circle (two stages).

    1. Single-linkage chains with ``tolerance`` link distance keep
       wide corners whole: a real corner's apexes can spread well
       beyond the tolerance across driving lines (Kiltorcan's s~160
       corner spans 43 m p10-p90 in <= 8 m steps), and a
       diameter-capped clusterer splits such corners into
       sub-threshold pieces, dropping real corners.
    2. Recurrence-qualified valley splitting (``_split_chain``)
       separates corners that chaining bridges: Kiltorcan's s~695 and
       s~739 corners, each run by ~100% of laps, chain together
       through scattered line-variation apexes and only split because
       both sides independently pass the recurrence threshold.

    ``lap_ids[j]`` is the lap that contributed ``positions[j]``;
    ``min_laps`` is the recurrence threshold in distinct laps.
    """
    clusters = []
    for chain in _circular_clusters(positions, tolerance, circumference):
        clusters.extend(_split_chain(chain, positions, lap_ids, min_laps,
                                     min_gap, circumference))
    return clusters


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


# ---- aggregation (D6) ----------------------------------------------------------


def _hierarchical(values, laps):
    """Equal-user-weighted median: lap -> session -> user -> circuit.

    Returns ``(circuit_median, {user_id: {'median', 'n_sessions',
    'n_laps'}})``. Session medians first (a 20-lap session weighs the
    same as a 2-lap one), then the median across each user's sessions,
    then across users.
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


def _radius_class(radius_m, params):
    if radius_m < params.slow_corner_max_m:
        return 'slow'
    if radius_m < params.medium_corner_max_m:
        return 'medium'
    return 'fast'


def _consensus_dc_count(corners, gap_m, circumference):
    """Direction changes in the consensus corner set: consecutive
    opposite-sign corners with an edge-to-edge gap <= ``gap_m``
    (mirrors the engine's per-lap rule; corner list sorted by apex)."""
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


def _cross_check(x, y, engine_params):
    """Run frozen engine v1.0 on the consensus polyline.

    A cross-check of the recurrence corner set (and consensus-line
    straights/DCs), not the canonical value — recorded so the two
    readings of plan Sections 4.5 and 5.3 can be compared per track.
    """
    try:
        geo = analyze_lap(
            LapInput(x=np.asarray(x, dtype=float).copy(),
                     y=np.asarray(y, dtype=float).copy()),
            engine_params)
    except ValueError as exc:
        return {'error': str(exc)}
    engine = geo.summary()
    return {
        'length_m': engine['length_m'],
        'corner_count': len(engine['corners']),
        'straight_pct': round(100.0 * engine['straight_fraction'], 2),
        'longest_straight_m': engine['longest_straight_m'],
        'dc_count': len(engine['direction_changes']),
        'spun': engine['spun'],
        'engine_summary': engine,
    }


# ---- core pipeline ----------------------------------------------------------


def _lap_sort_key(lap):
    return (lap.session_id, lap.lap_number if lap.lap_number is not None
            else -1)


def _pipeline(laps, params, engine_params):
    """Alignment + consensus trajectory + corner set + scalar dims.

    Everything the convergence indicator needs to recompute on a lap
    subsample; no evidence spreads, cross-check or convergence here.
    """
    n = len(laps)
    lengths = [float(lap.geometry.length_m) for lap in laps]
    median_len = float(np.median(lengths))
    seed_i = min(range(n), key=lambda i: (abs(lengths[i] - median_len), i))
    seed_lap = laps[seed_i]
    seed_profile = _curvature_profile(seed_lap.geometry, params.align_grid)

    fracs = []
    rs = []
    for lap in laps:
        frac, r = _align_shift(
            _curvature_profile(lap.geometry, params.align_grid),
            seed_profile, params)
        fracs.append(frac)
        rs.append(r)
    fracs = np.asarray(fracs, dtype=float)
    rs = np.asarray(rs, dtype=float)
    shifts_m = fracs * np.asarray(lengths)

    # dimensions 1/2/3/8: hierarchical medians of per-lap values
    length_m, _ = _hierarchical(lengths, laps)
    straight_pct, _ = _hierarchical(
        [100.0 * lap.geometry.straight_fraction for lap in laps], laps)
    longest, _ = _hierarchical(
        [float(lap.geometry.longest_straight_m) for lap in laps], laps)
    dc_per_km, _ = _hierarchical(
        [float(lap.geometry.dc_per_km) for lap in laps], laps)
    dc_count_median, _ = _hierarchical(
        [float(lap.geometry.dc_count) for lap in laps], laps)
    corner_count_median, _ = _hierarchical(
        [float(lap.geometry.corner_count) for lap in laps], laps)

    # consensus trajectory: hierarchical per-grid-point medians of raw
    # resampled positions on the normalized consensus grid
    grid_n = max(8, int(round(length_m / engine_params.res_m)))
    grid_t = np.arange(grid_n) / grid_n
    lap_x, lap_y = [], []
    for lap, frac in zip(laps, fracs):
        x, y = _sample_positions(lap.geometry, float(frac), grid_t)
        lap_x.append(x)
        lap_y.append(y)
    session_curves = defaultdict(list)
    for i, lap in enumerate(laps):
        session_curves[(lap.user_id, lap.session_id)].append(i)
    session_med = {}
    for _key, idxs in session_curves.items():
        session_med[_key] = (
            np.median([lap_x[i] for i in idxs], axis=0),
            np.median([lap_y[i] for i in idxs], axis=0))
    user_curves = defaultdict(list)
    for (uid, _sid), curve in session_med.items():
        user_curves[uid].append(curve)
    user_med = {uid: (np.median([c[0] for c in curves], axis=0),
                      np.median([c[1] for c in curves], axis=0))
                for uid, curves in user_curves.items()}
    cx = np.median([c[0] for c in user_med.values()], axis=0)
    cy = np.median([c[1] for c in user_med.values()], axis=0)
    arclength = _polyline_arclength(cx, cy)

    # consensus corner set: recurrence clustering of mapped apexes
    n_laps_by_user = defaultdict(int)
    for lap in laps:
        n_laps_by_user[lap.user_id] += 1
    mapped = []      # (lap_index, corner, m_apex, d_start, d_end)
    for i, lap in enumerate(laps):
        for corner in lap.geometry.corners:
            m_apex, d_start, d_end = _map_corner(
                lap.geometry, corner, float(fracs[i]), length_m)
            mapped.append((i, corner, m_apex, d_start, d_end))
    min_laps = params.corner_recurrence * n
    clusters = _recurrence_clusters(
        [m[2] for m in mapped], [m[0] for m in mapped],
        params.corner_cluster_m, length_m, min_laps,
        engine_params.corner_gap_merge_m)
    corners = []
    mixed_sign = 0
    for cluster in clusters:
        member_laps = {mapped[j][0] for j in cluster}
        if len(member_laps) < min_laps:
            continue
        signs = {mapped[j][1].sign for j in cluster}
        if len(signs) > 1:
            mixed_sign += 1
        m_apex = _circular_median([mapped[j][2] for j in cluster], length_m)
        d_start = float(np.median([mapped[j][3] for j in cluster]))
        d_end = float(np.median([mapped[j][4] for j in cluster]))
        dtheta = float(np.median(
            [mapped[j][1].delta_theta_deg for j in cluster]))
        radii = [mapped[j][1].radius_m for j in cluster
                 if math.isfinite(mapped[j][1].radius_m)]
        radius = float(np.median(radii)) if radii else float('inf')
        sign = 1 if dtheta >= 0.0 else -1
        support_by_user = {}
        for uid, total in n_laps_by_user.items():
            hits = len({mapped[j][0] for j in cluster
                        if laps[mapped[j][0]].user_id == uid})
            support_by_user[uid] = hits / total
        corners.append(ConsensusCorner(
            s_apex=m_apex, s_start=m_apex + d_start, s_end=m_apex + d_end,
            delta_theta_deg=dtheta, radius_m=radius, sign=sign,
            radius_class=_radius_class(radius, params),
            n_laps=len(member_laps), recurrence=len(member_laps) / n,
            member_corners=len(cluster), support_by_user=support_by_user))
    corners.sort(key=lambda c: c.s_apex)

    corner_count = len(corners)
    density = corner_count / (length_m / 1000.0) if length_m > 0 else 0.0
    classes = [c.radius_class for c in corners]
    props = {name: (100.0 * classes.count(name) / corner_count
                    if corner_count else 0.0)
             for name in ('slow', 'medium', 'fast')}
    dc_consensus = _consensus_dc_count(corners, engine_params.dc_gap_m,
                                       length_m)

    return {
        'length_m': length_m,
        'straight_pct': straight_pct,
        'longest_straight_m': longest,
        'dc_per_km': dc_per_km,
        'dc_count_median': dc_count_median,
        'corner_count_per_lap_median': corner_count_median,
        'corner_count': corner_count,
        'corner_density_per_km': density,
        'corner_props': props,
        'dc_consensus_count': dc_consensus,
        'grid_n': grid_n,
        'grid': grid_t * length_m,
        'x': cx, 'y': cy,
        'arclength_m': arclength,
        'bbox': robust_bbox(cx, cy),
        'corners': corners,
        'mixed_sign_clusters': mixed_sign,
        'shifts_m': shifts_m,
        'align_r': rs,
        'seed': {'session_id': seed_lap.session_id,
                 'lap_number': seed_lap.lap_number},
    }


def _convergence(laps, params, engine_params):
    """Seeded-draw stability of the dimension values (plan 15.6,
    re-anchored): at n=50, length spread <= 6 m, corner count <= 1,
    straight% <= 2 pp.

    Scalar dimensions (length, straight%, longest straight, DC/km) are
    measured on the same basis the Section 15.6 anchor was calibrated
    on — the flat per-lap median over each drawn subsample (the Phase-3
    ``experiment_convergence`` protocol). The corner count is the
    recurrence set built from the subsample (dimension 4 as delivered).
    The equal-user-weighted hierarchical values are recorded per draw
    as NON-gating evidence: a seeded draw also resamples the user
    composition, a variance the Phase-3 anchor never measured, so
    their spreads are reported but do not gate acceptance.
    """
    n = len(laps)
    rng = np.random.default_rng(params.convergence_seed)
    lap_values = {
        'length_m': np.array([lap.geometry.length_m for lap in laps]),
        'straight_pct': np.array(
            [100.0 * lap.geometry.straight_fraction for lap in laps]),
        'longest_straight_m': np.array(
            [float(lap.geometry.longest_straight_m) for lap in laps]),
        'dc_per_km': np.array([float(lap.geometry.dc_per_km)
                               for lap in laps]),
    }
    entries = []
    for size in params.convergence_sizes:
        k = n if size is None else min(size, n)
        flat = defaultdict(list)
        counts = []
        hier = defaultdict(list)
        for _ in range(params.convergence_draws):
            if k < n:
                idx = rng.choice(n, size=k, replace=False)
                sub = [laps[int(i)] for i in idx]
                drawn = {key: values[idx]
                         for key, values in lap_values.items()}
            else:
                sub = laps
                drawn = lap_values
            for key, values in drawn.items():
                flat[key].append(float(np.median(values)))
            core = _pipeline(sub, params, engine_params)
            counts.append(core['corner_count'])
            hier['length_m'].append(core['length_m'])
            hier['straight_pct'].append(core['straight_pct'])
        entry = {'n_laps': int(k), 'draws': int(params.convergence_draws)}
        for key, vals in flat.items():
            entry[key] = {'median': round(float(np.median(vals)), 3),
                          'spread': round(float(max(vals) - min(vals)), 3)}
        entry['corner_count'] = {
            'median': float(np.median(counts)),
            'spread': float(max(counts) - min(counts)),
        }
        entry['hierarchical_evidence'] = {
            key: {'median': round(float(np.median(vals)), 3),
                  'spread': round(float(max(vals) - min(vals)), 3)}
            for key, vals in hier.items()}
        entries.append(entry)

    ref = None
    for entry in entries:
        if entry['n_laps'] <= 50 and (ref is None
                                      or entry['n_laps'] > ref['n_laps']):
            ref = entry
    acceptance = None
    if ref is not None:
        acceptance = {
            'n_laps': ref['n_laps'],
            'basis': ('flat per-lap medians + recurrence corner count '
                      '(plan 15.6 anchor protocol)'),
            'length_spread_m': ref['length_m']['spread'],
            'length_ok': ref['length_m']['spread'] <= CONVERGENCE_LENGTH_M,
            'corner_spread': ref['corner_count']['spread'],
            'corners_ok': ref['corner_count']['spread'] <= CONVERGENCE_CORNERS,
            'straight_pct_spread': ref['straight_pct']['spread'],
            'straight_ok': (ref['straight_pct']['spread']
                            <= CONVERGENCE_STRAIGHT_PP),
            'hierarchical_evidence': ref['hierarchical_evidence'],
        }
    return {'draws': entries, 'acceptance': acceptance}


# ---- public entry point -------------------------------------------------------


def build_consensus(laps, params=DEFAULT_CONSENSUS_PARAMS,
                    engine_params=DEFAULT_PARAMS, condition=None):
    """Build the consensus trajectory, corner set and dimensions 1-8.

    ``laps`` is a list of :class:`ConsensusLap` (valid laps from
    ``analyze_session`` plus user/session metadata). Spun laps are
    excluded as data-quality signals (plan 15.5). Raises ``ValueError``
    when there is nothing to build from.
    """
    if not laps:
        raise ValueError('no laps to build a consensus from')
    laps = sorted(laps, key=_lap_sort_key)
    spun = [lap for lap in laps if lap.geometry.spun]
    used = [lap for lap in laps if not lap.geometry.spun]
    if not used:
        raise ValueError('every lap is spun: no geometry input (plan 15.5)')

    core = _pipeline(used, params, engine_params)

    per_user = {
        'track_length_m': _user_spread(
            used, [lap.geometry.length_m for lap in used]),
        'straight_pct': _user_spread(
            used, [100.0 * lap.geometry.straight_fraction for lap in used]),
        'longest_straight_m': _user_spread(
            used, [lap.geometry.longest_straight_m for lap in used]),
        'corner_count': _user_spread(
            used, [lap.geometry.corner_count for lap in used]),
        'dc_per_km': _user_spread(
            used, [lap.geometry.dc_per_km for lap in used]),
    }

    cross = _cross_check(core['x'], core['y'], engine_params)
    conv = _convergence(used, params, engine_params)

    return TrackConsensus(
        condition=condition,
        laps=used,
        spun=spun,
        length_m=core['length_m'],
        straight_pct=core['straight_pct'],
        longest_straight_m=core['longest_straight_m'],
        corner_count=core['corner_count'],
        corner_density_per_km=core['corner_density_per_km'],
        corner_props=core['corner_props'],
        dc_per_km=core['dc_per_km'],
        dc_count_median=core['dc_count_median'],
        dc_consensus_count=core['dc_consensus_count'],
        corner_count_per_lap_median=core['corner_count_per_lap_median'],
        grid=core['grid'],
        x=core['x'], y=core['y'],
        arclength_m=core['arclength_m'],
        bbox=core['bbox'],
        corners=core['corners'],
        shifts_m=core['shifts_m'],
        align_r=core['align_r'],
        seed=core['seed'],
        per_user=per_user,
        cross_check=cross,
        convergence=conv,
        data_quality={
            'spun_laps': [{'session_id': lap.session_id,
                           'lap_number': lap.lap_number}
                          for lap in spun],
            'mixed_sign_corners': core['mixed_sign_clusters'],
        },
    )
