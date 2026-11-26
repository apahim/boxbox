"""Track DNA geometry engine.

Phase 2 of the Track DNA implementation plan: pure geometry primitives
(``signed_area``, ``robust_bbox``, ``bbox_iou``) that the
configuration-identification clustering builds on.

Phase 3: the per-lap geometry engine — arclength resampling, circular
smoothing, heading/curvature profiles and corner/straight segmentation
(plan Section 6), plus session-level lap validity (plan Section 4.1, the
canonical resampler-based count that decision D8 reconciles).

NumPy + SciPy only — no app imports, matching the ``scripts/analysis/``
convention. All engine inputs are plain numpy arrays in *metres* (project
lat/lon with ``scripts.analysis.utils.project_to_meters`` first, passing an
explicit track centre per decision D11).
"""

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import median_filter


def signed_area(x, y):
    """Shoelace signed area of an ordered polyline (m^2).

    Positive for counter-clockwise traversal, negative for clockwise.
    The path does not need to be closed: the closing segment back to the
    first point is implicit, as required for lap loops.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size < 3:
        return 0.0
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def robust_bbox(x, y, percentiles=(2.5, 97.5)):
    """Percentile bounding box of a point cloud, glitch-robust.

    Returns ``(x0, y0, x1, y1)`` with the low/high percentiles taken
    independently per axis. Raw min/max bboxes get corrupted by GPS
    glitches (a production session showed a 2.7 x 8.5 km bbox on a
    ~230 m circuit); the percentile trim removes them while leaving
    genuine circuit extent intact.

    Returns ``(0.0, 0.0, 0.0, 0.0)`` for empty input.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size == 0:
        return (0.0, 0.0, 0.0, 0.0)
    lo, hi = percentiles
    x0, x1 = np.percentile(x, [lo, hi])
    y0, y1 = np.percentile(y, [lo, hi])
    return (float(x0), float(y0), float(x1), float(y1))


def bbox_iou(a, b):
    """Intersection-over-union of two ``(x0, y0, x1, y1)`` boxes.

    Returns 0.0 for disjoint or degenerate boxes.
    """
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b

    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)

    iw = max(ix1 - ix0, 0.0)
    ih = max(iy1 - iy0, 0.0)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0

    area_a = max(ax1 - ax0, 0.0) * max(ay1 - ay0, 0.0)
    area_b = max(bx1 - bx0, 0.0) * max(by1 - by0, 0.0)
    union = area_a + area_b - inter
    if union <= 0.0:
        return 0.0
    return inter / union


# ---------------------------------------------------------------------------
# Phase 3 — geometry engine
# ---------------------------------------------------------------------------

# Matches app.track_dna.hygiene.MIN_SAMPLES; duplicated so the engine stays
# free of app imports.
MIN_SAMPLES = 100


@dataclass(frozen=True)
class TrackDNAParams:
    """v1.0 processing parameters (plan Section 6).

    Engine-relevant subset. Braking (Phase 5), elevation (Phase 6) and
    consensus recurrence (Phase 4) parameters join the dataclass in their
    own phases so it never carries dead fields.
    """

    res_m: float = 1.0                # arclength resample spacing
    static_step_m: float = 0.05       # drop raw steps smaller than this
    pos_smooth_m: float = 10.0        # circular position smoothing window
    kappa_filter_m: float = 5.0       # median-filter window on curvature
    r_min_m: float = 200.0            # corner curvature threshold radius
    corner_gap_merge_m: float = 10.0  # merge corner runs this close
    corner_min_dtheta_deg: float = 30.0
    spin_cap_deg: float = 300.0       # per-corner heading cap: over-cap
                                      # sections split at curvature
                                      # relaxations; un-splittable ones flag
                                      # `spun` (diagnostic; segment dropped)
    radius_filter_m: float = 10.0     # rolling-median window for corner radius
    straight_window_m: float = 20.0   # sliding-window width (± half of this)
    straight_min_m: float = 20.0
    straight_gap_merge_m: float = 10.0
    dc_gap_m: float = 30.0            # max gap between opposite-sign corners


DEFAULT_PARAMS = TrackDNAParams()


@dataclass
class LapInput:
    """One lap's raw telemetry, projected to metre coordinates.

    ``x``/``y`` are required; optional channels are carried onto the
    resample grid when present. Laps are gate-to-gate loops: the segment
    from the last point back to the first closes the circuit.
    ``n_samples`` overrides the raw sample count used by the session
    validity filter (defaults to ``len(x)``) — the DB loader sets it to the
    lap group's full row count for Phase-1 parity.
    """

    x: np.ndarray
    y: np.ndarray
    altitude: np.ndarray | None = None
    speed: np.ndarray | None = None
    elapsed: np.ndarray | None = None
    n_samples: int | None = None


@dataclass
class Corner:
    """One corner, as a run of curvature above threshold.

    ``i_start``/``i_len`` are resample-grid indices (unwrapped: the run may
    extend past the grid length, i.e. wrap the s=0 seam). ``s_*`` are metre
    positions; ``s_end`` may exceed the lap length when the corner wraps.
    ``delta_theta_deg`` is signed: negative = right/clockwise turn.
    """

    i_start: int
    i_len: int
    s_start: float
    s_end: float
    s_apex: float
    delta_theta_deg: float
    sign: int
    radius_m: float


@dataclass
class Straight:
    """One straight: a maximal stretch of qualifying sliding-window tests.

    ``s_start`` is the start of the *certified* span (first qualifying
    window's leading edge), in [0, lap length); ``length_m`` is the
    certified span length.
    """

    s_start: float
    length_m: float
    delta_theta_deg: float


@dataclass
class DirectionChange:
    """Two consecutive corners of opposite sign, gap <= dc_gap_m."""

    s_mid: float
    sign_before: int
    sign_after: int


@dataclass
class LapGeometry:
    """Full per-lap analysis result."""

    lap_number: int | None
    length_m: float
    n_samples: int                      # raw rows passed in (pre-dedupe)
    duration_s: float | None
    s: np.ndarray                       # resample grid (m)
    x: np.ndarray
    y: np.ndarray
    x_smooth: np.ndarray
    y_smooth: np.ndarray
    theta: np.ndarray                   # unwrapped heading (rad)
    kappa: np.ndarray                   # median-filtered curvature (rad/m)
    altitude: np.ndarray | None
    speed: np.ndarray | None
    elapsed: np.ndarray | None
    corners: list[Corner] = field(default_factory=list)
    straights: list[Straight] = field(default_factory=list)
    direction_changes: list[DirectionChange] = field(default_factory=list)
    spun: bool = False
    heading_total_deg: float = 0.0
    heading_budget: dict = field(default_factory=dict)
    bbox: tuple = (0.0, 0.0, 0.0, 0.0)

    @property
    def corner_count(self):
        return len(self.corners)

    @property
    def corner_density_per_km(self):
        return self.corner_count / (self.length_m / 1000.0) if self.length_m else 0.0

    @property
    def straight_total_m(self):
        return sum(st.length_m for st in self.straights)

    @property
    def straight_fraction(self):
        return self.straight_total_m / self.length_m if self.length_m else 0.0

    @property
    def longest_straight_m(self):
        return max((st.length_m for st in self.straights), default=0.0)

    @property
    def dc_count(self):
        return len(self.direction_changes)

    @property
    def dc_per_km(self):
        return self.dc_count / (self.length_m / 1000.0) if self.length_m else 0.0

    def summary(self):
        """JSON-serialisable summary (golden fixtures, calibration reports)."""
        return {
            'length_m': round(self.length_m, 3),
            'n_samples': self.n_samples,
            'spun': self.spun,
            'heading_total_deg': round(self.heading_total_deg, 3),
            'heading_budget': {k: round(v, 3) for k, v in self.heading_budget.items()},
            'corners': [
                {
                    's_start': round(c.s_start, 2),
                    's_end': round(c.s_end, 2),
                    's_apex': round(c.s_apex, 2),
                    'delta_theta_deg': round(c.delta_theta_deg, 3),
                    'sign': c.sign,
                    'radius_m': round(c.radius_m, 2),
                }
                for c in self.corners
            ],
            'straights': [
                {
                    's_start': round(st.s_start, 2),
                    'length_m': round(st.length_m, 2),
                    'delta_theta_deg': round(st.delta_theta_deg, 3),
                }
                for st in self.straights
            ],
            'direction_changes': [round(dc.s_mid, 2) for dc in self.direction_changes],
            'straight_total_m': round(self.straight_total_m, 2),
            'straight_fraction': round(self.straight_fraction, 4),
            'longest_straight_m': round(self.longest_straight_m, 2),
            'corner_density_per_km': round(self.corner_density_per_km, 3),
            'dc_per_km': round(self.dc_per_km, 3),
        }


@dataclass
class RejectedLap:
    lap_number: int
    reason: str      # insufficient_samples | duration_out_of_range |
                     # length_out_of_range | degenerate
    detail: str = ''


@dataclass
class SessionGeometry:
    """Session-level result: canonical lap validity plus per-lap geometry."""

    laps: list[LapGeometry]             # valid laps, ordered by lap number
    rejected: list[RejectedLap]
    median_duration_s: float | None
    median_length_m: float | None

    @property
    def n_valid(self):
        return len(self.laps)


# ---- resampling -----------------------------------------------------------


def dedupe_static(x, y, min_step_m=DEFAULT_PARAMS.static_step_m):
    """Boolean mask dropping rows whose step from the previous raw row is
    below ``min_step_m`` (static-point dedupe; the first row always kept).

    Vectorised pairwise rule: a run of near-identical points collapses to
    its first sample. Steps are measured against the previous *raw* row,
    which matches the sequential rule for static chains (the two only
    differ on sub-threshold drift, immaterial to arclength).
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size < 2:
        return np.ones(x.size, dtype=bool)
    steps = np.hypot(np.diff(x), np.diff(y))
    return np.concatenate([[True], steps >= min_step_m])


def _arclength(x, y):
    """Cumulative arclength and total loop length (closing segment included)."""
    steps = np.hypot(np.diff(x), np.diff(y))
    s = np.zeros(x.size)
    s[1:] = np.cumsum(steps)
    closing = math.hypot(x[0] - x[-1], y[0] - y[-1]) if x.size > 1 else 0.0
    return s, float(s[-1] + closing)


def resample_lap(lap, params=DEFAULT_PARAMS):
    """Resample a lap onto a uniform arclength grid.

    Returns ``(grid, columns, length_m)``. The grid has ``ceil(length/res)``
    points at spacing ``res``; index 0 is the lap's first raw point and the
    grid is periodic (s = length is s = 0 again). Optional channels are
    interpolated onto the grid, with the closing segment bridging the last
    raw point back to the first.
    """
    keep = dedupe_static(lap.x, lap.y, params.static_step_m)
    x = np.asarray(lap.x, dtype=float)[keep]
    y = np.asarray(lap.y, dtype=float)[keep]
    if x.size < 3:
        raise ValueError('lap has fewer than 3 non-static points')
    s_in, length = _arclength(x, y)
    n = int(math.ceil(length / params.res_m))
    if n < 8:
        raise ValueError('lap too short to resample')

    s_ext = np.append(s_in, length)
    grid = np.arange(n) * params.res_m

    def _interp(values, close_value):
        v = np.asarray(values, dtype=float)[keep]
        return np.interp(grid, s_ext, np.append(v, close_value))

    columns = {'x': _interp(lap.x, x[0]), 'y': _interp(lap.y, y[0])}
    if lap.altitude is not None:
        v = np.asarray(lap.altitude, dtype=float)[keep]
        columns['altitude'] = _interp(lap.altitude, v[0])
    if lap.speed is not None:
        v = np.asarray(lap.speed, dtype=float)[keep]
        columns['speed'] = _interp(lap.speed, v[0])
    if lap.elapsed is not None:
        v = np.asarray(lap.elapsed, dtype=float)[keep]
        # Keep the closing segment monotonic in time: continue one mean step
        # past the last raw sample instead of jumping back to t[0].
        step = float(v[-1] - v[-2]) if v.size >= 2 else 0.0
        columns['elapsed'] = np.interp(grid, s_ext, np.append(v, v[-1] + step))
    return grid, columns, length


def circular_smooth(values, window_m, res_m=1.0):
    """Periodic moving average (wrap-padded, so features crossing the s=0
    seam survive smoothing). Returns the input unchanged for windows <= 1
    sample."""
    values = np.asarray(values, dtype=float)
    n = values.size
    w = int(round(window_m / res_m))
    if n == 0 or w <= 1:
        return values.copy()
    if w % 2 == 0:
        w += 1
    half = min(w // 2, n - 1)
    if half <= 0:
        return values.copy()
    idx = np.arange(-half, n + half) % n
    padded = values[idx]
    kernel = np.ones(2 * half + 1) / (2 * half + 1)
    return np.convolve(padded, kernel, mode='same')[half:half + n]


# ---- heading and curvature -------------------------------------------------


def _chord_headings(x, y, half):
    """theta[i] = direction of the chord from point i-half to i+half
    (circular indices). For constant-curvature stretches a chord heading is
    the exact tangent at its centre, so this is noise-robust without
    biasing real curvature."""
    n = x.size
    idx = np.arange(n)
    i0 = (idx - half) % n
    i1 = (idx + half) % n
    return np.arctan2(y[i1] - y[i0], x[i1] - x[i0])


def _unwrap_periodic(theta):
    """Unwrap a periodic heading sequence.

    Returns ``(theta_u, total, theta_ext)``: the unwrapped first period, the
    exact total heading change over the loop (an integer multiple of 2*pi),
    and a quadrupled array where ``theta_ext[n + j]`` is valid for any
    unwrapped index ``j`` in ``[-n, 3n)`` — seam-crossing lookups included.
    """
    n = theta.size
    unwrapped = np.unwrap(np.concatenate([theta, theta]))
    theta_u = unwrapped[:n].copy()
    total = float(unwrapped[n] - unwrapped[0])
    theta_ext = np.concatenate([theta_u + k * total for k in range(4)])
    return theta_u, total, theta_ext


def _curvature(theta_ext, n, half, res_m, filter_m):
    """kappa = central difference of the chord headings, median-filtered
    (plan Section 6: dtheta/ds with a 5 m median filter). Exact for
    constant curvature regardless of the differencing span."""
    kappa = (theta_ext[n + half:n + half + n]
             - theta_ext[n - half:n - half + n]) / (2.0 * half * res_m)
    size = int(round(filter_m / res_m))
    if size % 2 == 0:
        size += 1
    if 1 < size < n:
        kappa = median_filter(kappa, size=size, mode='wrap')
    return kappa


# ---- circular run finding ---------------------------------------------------


def _dedupe_contained(candidates, n):
    """Drop runs circularly contained in a longer representative.

    A run wrapping the s=0 seam can leave a second, partial representative
    starting near 0; containment is compared across +-n shifts."""
    out = []
    for i, (s, length) in enumerate(candidates):
        contained = False
        for j, (s2, length2) in enumerate(candidates):
            if i == j or length2 <= length:
                continue
            for shift in (-n, 0, n):
                if s2 + shift <= s and s + length <= s2 + shift + length2:
                    contained = True
                    break
            if contained:
                break
        if not contained:
            out.append((s, min(length, n)))
    return out


def _circular_runs(mask, max_gap):
    """Maximal True runs of a circular boolean mask, merging gaps
    <= ``max_gap`` samples.

    Returns ``[(start, length), ...]`` with ``start`` in ``[0, n)``; a run
    may extend past ``n`` (wrapping the seam). Computed on the doubled mask
    so seam-crossing runs and seam-adjacent gaps behave exactly like
    interior ones.
    """
    n = mask.size
    if n == 0 or not mask.any():
        return []
    m2 = np.concatenate([mask, mask]).astype(np.int8)
    d = np.diff(np.concatenate([[0], m2, [0]]))
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    runs = []  # [start, end) in doubled coordinates
    for s, e in zip(starts, ends):
        if runs and s - runs[-1][1] <= max_gap:
            runs[-1][1] = e
        else:
            runs.append([s, e])
    candidates = [(s, e - s) for s, e in runs if s < n]
    out = _dedupe_contained(candidates, n)
    out.sort()
    return out


def _merge_runs_same_sign(runs, kappa, n, max_gap):
    """Merge consecutive corner runs across gaps <= ``max_gap`` samples
    when their median curvature signs match (plan Section 6: "same-sign
    merge <= 10 m").

    Same-sign merging fuses double-apex corners split by an internal
    curvature dip. Opposite-sign neighbours stay separate — merging across
    a sign change would fuse switchback corner sequences into one
    mega-corner (the Kiltorcan failure mode this rule prevents).
    """
    if len(runs) <= 1:
        return list(runs)

    def sign_of(run):
        seq = kappa[(run[0] + np.arange(run[1])) % n]
        return 1 if float(np.median(seq)) > 0 else -1

    doubled = sorted([list(r) for r in runs]
                     + [[s + n, l] for s, l in runs])
    merged = []
    signs = []
    for run in doubled:
        sign = sign_of(run)
        if (merged and sign == signs[-1]
                and run[0] - (merged[-1][0] + merged[-1][1]) <= max_gap):
            merged[-1][1] = run[0] + run[1] - merged[-1][0]
        else:
            merged.append(run)
            signs.append(sign)
    candidates = [(s, l) for s, l in merged if s < n]
    out = _dedupe_contained(candidates, n)
    out.sort()
    return out


def _split_run_by_sign(run, kappa):
    """Split a run at curvature sign changes (zero crossings inside a merged
    run). Returns ``[(offset_start, offset_end), ...]`` run-local bounds."""
    start, length = run
    seq = kappa[(start + np.arange(length)) % kappa.size]
    signs = np.sign(seq)
    change = np.flatnonzero(signs[1:] != signs[:-1]) + 1
    bounds = np.concatenate([[0], change, [length]])
    return [(int(bounds[i]), int(bounds[i + 1]))
            for i in range(len(bounds) - 1)]


def _odd_size(window_m, res_m, n):
    size = int(round(window_m / res_m))
    if size % 2 == 0:
        size += 1
    return max(1, min(size, n - 1))


def _edge_extension(kappa, n, edge, direction, limit, sign):
    """Samples to extend a corner measurement beyond a run-outer ``edge``
    in ``direction`` (+1 forward, -1 backward).

    Up to ``limit`` (chord_half) samples, stopping at the first sample
    whose curvature sign differs from the corner's ``sign``: that is the
    zero crossing into an adjacent opposite-sign corner, whose heading
    must not be stolen (an unclamped window nets out short S-bend
    corners). Same-sign decay (a straight's ramp) extends freely.
    """
    ext = 0
    for step in range(1, limit + 1):
        k = kappa[(edge + direction * step) % n]
        if (k > 0) != (sign > 0):
            break
        ext = step
    return ext


# ---- corner segmentation ----------------------------------------------------


def segment_corners(kappa, theta_ext, n, params, chord_half, radius_abs_kappa,
                    radius_size):
    """Segment corners from the curvature profile.

    Chain (plan Section 6): maximal |kappa| >= 1/R_min runs (no gap
    merging) -> same-sign gap-merge <= corner_gap_merge_m (fuses
    double-apex corners split by a curvature dip; opposite-sign
    neighbours never merge, which would fuse switchback sequences into
    one mega-corner) -> split at kappa sign changes -> keep segments with
    |delta theta| >= corner_min_dtheta_deg.

    Delta theta is measured on the unwrapped heading from the segment's
    entry boundary to its exit boundary. Split-created inner edges sit at
    kappa sign changes (the natural inflection between opposite-sign
    bends). Run-outer edges extend by up to +-chord_half to recover the
    ramp-diluted heading, clamped at the kappa zero crossing when an
    opposite-sign corner is nearer than that (see ``_edge_extension``).

    A segment exceeding spin_cap_deg is not a spin by itself: real
    circuits contain >300 deg carousels (Kiltorcan's measures 345-359 deg
    on every lap). Such a segment is recursively split at its heading
    midpoint — a physical track property, so the resulting corner set is
    independent of where the lap's s=0 seam falls — until every piece is
    under the cap; pieces then pass through the normal min-delta filter.
    An over-cap stretch whose curvature never relaxes below half its
    median — sustained near-constant curvature over more than 300 deg —
    is the true spin signature (plan Section 4.1): it is dropped and
    flags ``spun`` as a diagnostic, never a lap rejection.

    ``radius_abs_kappa`` is the rolling-median |kappa| used for the
    representative radius (min of rolling-median radii; median for short
    corners — plan Section 3).
    """
    thr = 1.0 / params.r_min_m
    gap_samples = int(round(params.corner_gap_merge_m / params.res_m))
    mask = np.abs(kappa) >= thr
    runs = _merge_runs_same_sign(_circular_runs(mask, 0), kappa, n,
                                 gap_samples)

    # Extension caps: the +-chord_half measurement windows of two runs
    # facing each other across a gap must not overlap (double-counted
    # heading). Each outer edge may extend at most half the circular gap
    # to the adjacent run (a run wrapping most of the lap is adjacent to
    # itself across the seam).
    m_runs = len(runs)
    caps = []
    for i, (s, length) in enumerate(runs):
        end = s + length
        j = (i + 1) % m_runs
        s_next = runs[j][0]
        if s_next <= end:
            s_next += n
        k = (i - 1) % m_runs
        end_prev = runs[k][0] + runs[k][1]
        if end_prev > s:
            end_prev -= n
        cap_hi = max(0, min(chord_half, (s_next - end) // 2))
        cap_lo = max(0, min(chord_half, (s - end_prev) // 2))
        caps.append((cap_lo, cap_hi))

    corners = []
    spun = False
    subthreshold_deg = 0.0    # heading of segments below the min-delta filter
    spin_dropped_deg = 0.0    # heading of true-spin segments (dropped)

    def measure(i0, i1, lo_ext, hi_ext):
        return math.degrees(theta_ext[n + i1 + hi_ext] - theta_ext[n + i0 - lo_ext])

    def split_overspin(i0, i1, lo_ext, hi_ext, depth=0):
        """Recursively split an over-cap segment at its heading midpoint.
        Returns ``(pieces, is_spin)``: pieces are (i0, i1, lo_ext, hi_ext)
        tuples with |delta theta| <= cap; ``is_spin`` is True when a piece
        could not be split and was dropped.

        The split point is the physical sample where the unwrapped heading
        crosses the segment's midpoint heading — a property of the track,
        not of where the lap's s=0 seam falls, so corner sets are stable
        across laps (the heading changes of the pieces sum exactly to the
        segment's). A over-cap stretch whose curvature never relaxes below
        half its median (sustained near-constant curvature over the cap)
        is the true spin signature and is dropped instead."""
        d = measure(i0, i1, lo_ext, hi_ext)
        if abs(d) <= params.spin_cap_deg:
            return [(i0, i1, lo_ext, hi_ext)], False
        length = i1 - i0 + 1
        if depth >= 8 or length <= 2:
            return [], True
        absk = np.abs(kappa[(i0 + np.arange(length)) % n])
        if absk.min() >= 0.5 * float(np.median(absk)):
            return [], True
        seg_theta = theta_ext[n + i0:n + i1 + 1]
        target = (theta_ext[n + i1 + hi_ext] + theta_ext[n + i0 - lo_ext]) / 2.0
        if d > 0:
            off = int(np.searchsorted(seg_theta, target))
        else:
            off = int(np.searchsorted(-seg_theta, -target))
        off = min(max(off, 1), length - 1)
        m = i0 + off
        left, spin_l = split_overspin(i0, m, lo_ext, 0, depth + 1)
        right, spin_r = split_overspin(m, i1, 0, hi_ext, depth + 1)
        return left + right, (spin_l or spin_r)

    for run_idx, run in enumerate(runs):
        r_start, r_len = run
        cap_lo, cap_hi = caps[run_idx]
        segs = _split_run_by_sign(run, kappa)
        res = params.res_m
        for k, (o0, o1) in enumerate(segs):
            i_start = r_start + o0
            i_end = r_start + o1 - 1
            seg_sign = 1 if kappa[i_start % n] > 0 else -1
            if k == 0:
                lo_ext = _edge_extension(kappa, n, i_start % n, -1,
                                         cap_lo, seg_sign)
            else:
                lo_ext = 0
            if k == len(segs) - 1:
                hi_ext = _edge_extension(kappa, n, i_end % n, +1,
                                         cap_hi, seg_sign)
            else:
                hi_ext = 0
            dtheta = measure(i_start, i_end, lo_ext, hi_ext)
            if abs(dtheta) > params.spin_cap_deg:
                pieces, is_spin = split_overspin(i_start, i_end,
                                                 lo_ext, hi_ext)
                spun = spun or is_spin
            else:
                pieces = [(i_start, i_end, lo_ext, hi_ext)]

            for p_start, p_end, p_lo, p_hi in pieces:
                d = measure(p_start, p_end, p_lo, p_hi)
                if abs(d) < params.corner_min_dtheta_deg:
                    subthreshold_deg += d
                    continue

                seg_idx = (p_start + np.arange(p_end - p_start + 1)) % n
                roll = radius_abs_kappa[seg_idx]
                if seg_idx.size < radius_size:
                    # short corner: median |kappa| over the segment
                    peak = float(np.median(np.abs(kappa[seg_idx])))
                    apex = int(seg_idx[int(np.argmax(np.abs(kappa[seg_idx])))])
                else:
                    peak = float(np.max(roll))
                    apex = int(seg_idx[int(np.argmax(roll))])
                radius = 1.0 / peak if peak > 1e-9 else float('inf')

                corners.append(Corner(
                    i_start=p_start,
                    i_len=p_end - p_start + 1,
                    s_start=(p_start % n) * res,
                    s_end=p_end * res,
                    s_apex=apex * res,
                    delta_theta_deg=d,
                    sign=1 if d > 0 else -1,
                    radius_m=radius,
                ))
            # heading dropped by the spin guard (true-spin segments only)
            accounted = sum(measure(*p) for p in pieces)
            spin_dropped_deg += dtheta - accounted
    budget_dropped = {
        'subthreshold_deg': subthreshold_deg,
        'spin_dropped_deg': spin_dropped_deg,
    }
    return corners, spun, budget_dropped


# ---- straight classification (decision D3) -----------------------------------


def classify_straights(theta_ext, n, lap_length, params):
    """Sliding-window straight classifier (decision D3).

    A grid point qualifies when the *total heading variation* across the
    window +-straight_window_m/2 stays below ``straight_window_m / r_min_m``
    (= 20 m / 200 m = 0.1 rad at v1.0 — derived, so R_min sweeps stay
    consistent). Total variation, not net change: a symmetric S-bend nets
    ~zero heading over a window but is not straight (the plan's PoC failure
    case); this is the faithful noise-robust aggregate of "R >= R_min
    throughout the window".

    Qualifying runs are gap-merged; each run's *certified* span (union of
    its qualifying windows: run span + one full window) is trimmed against
    neighbouring spans (no overlap), then kept when it reaches
    ``straight_min_m``. A run covering the whole lap is the full lap (e.g.
    an R=250 circle is one straight). ``delta_theta_deg`` is the net heading
    change across the qualifying run, so the heading-budget invariant stays
    additive.
    """
    res = params.res_m
    hw = max(1, int(round(params.straight_window_m / 2.0 / res)))
    hw = min(hw, n // 4)
    thr = params.straight_window_m / params.r_min_m

    # total |dtheta| variation over each window, via cumulative sums on an
    # hw-padded slice of the extended heading array
    seg = theta_ext[n - hw:n + n + hw]
    ad = np.abs(np.diff(seg))
    cs = np.concatenate([[0.0], np.cumsum(ad)])
    window_span = 2 * hw
    variation = cs[window_span:window_span + n] - cs[:n]
    mask = variation <= thr

    gap_samples = int(round(params.straight_gap_merge_m / res))
    runs = _circular_runs(mask, gap_samples)

    # certified spans as unwrapped index intervals [lo, hi)
    spans = []
    for start, length in runs:
        lo = start - hw
        hi = start + length - 1 + hw + 1
        spans.append([lo, hi])
    # trim overlaps between consecutive spans (circularly, last vs first too)
    if len(spans) > 1:
        for i in range(len(spans) - 1):
            if spans[i][1] > spans[i + 1][0]:
                spans[i][1] = spans[i + 1][0]
        if spans[-1][1] > spans[0][0] + n:
            spans[-1][1] = spans[0][0] + n

    straights = []
    for (start, length), (lo, hi) in zip(runs, spans):
        span_m = min((hi - lo) * res, lap_length)
        if span_m < params.straight_min_m or hi <= lo:
            continue
        dtheta = math.degrees(theta_ext[n + start + length - 1] - theta_ext[n + start])
        s_start = (lo * res) % lap_length
        straights.append(Straight(
            s_start=s_start,
            length_m=span_m,
            delta_theta_deg=dtheta,
        ))
    return straights


# ---- direction changes --------------------------------------------------------


def direction_changes(corners, n, lap_length, params):
    """Opposite-sign consecutive corners with gap <= dc_gap_m (plan Section 6).

    Gap is measured edge-to-edge along the loop (end of one corner's run to
    the start of the next), including the pair that wraps the s=0 seam.
    """
    if len(corners) < 2:
        return []
    res = params.res_m
    out = []
    m = len(corners)
    for a in range(m):
        b = (a + 1) % m
        ca, cb = corners[a], corners[b]
        gap_start = ca.i_start + ca.i_len
        gap_end = cb.i_start + (n if b == 0 else 0)
        gap_m = (gap_end - gap_start) * res
        if ca.sign != cb.sign and 0.0 <= gap_m <= params.dc_gap_m:
            out.append(DirectionChange(
                s_mid=(((gap_start + gap_end) / 2.0) * res) % lap_length,
                sign_before=ca.sign,
                sign_after=cb.sign,
            ))
    return out


# ---- lap and session analysis ---------------------------------------------------


def analyze_lap(lap, params=DEFAULT_PARAMS, lap_number=None):
    """Full per-lap pipeline: resample -> smooth -> heading -> curvature ->
    corners/straights/direction changes -> diagnostics."""
    grid, columns, length = resample_lap(lap, params)
    x, y = columns['x'], columns['y']
    n = x.size
    res = params.res_m

    xs = circular_smooth(x, params.pos_smooth_m, res)
    ys = circular_smooth(y, params.pos_smooth_m, res)

    chord_half = max(1, min(int(round(params.pos_smooth_m / 2.0 / res)), n // 4))
    theta_raw = _chord_headings(xs, ys, chord_half)
    theta, total, theta_ext = _unwrap_periodic(theta_raw)
    kappa = _curvature(theta_ext, n, chord_half, res, params.kappa_filter_m)

    radius_size = _odd_size(params.radius_filter_m, res, n)
    radius_abs_kappa = median_filter(np.abs(kappa), size=radius_size, mode='wrap')

    corners, spun, dropped = segment_corners(kappa, theta_ext, n, params,
                                             chord_half, radius_abs_kappa,
                                             radius_size)
    straights = classify_straights(theta_ext, n, length, params)
    dcs = direction_changes(corners, n, length, params)

    total_deg = math.degrees(total)
    corner_deg = sum(c.delta_theta_deg for c in corners)
    straight_deg = sum(st.delta_theta_deg for st in straights)
    subthreshold_deg = dropped['subthreshold_deg']
    spin_dropped_deg = dropped['spin_dropped_deg']

    duration = None
    if lap.elapsed is not None and len(lap.elapsed) >= 2:
        duration = float(lap.elapsed[-1] - lap.elapsed[0])

    return LapGeometry(
        lap_number=lap_number,
        length_m=length,
        n_samples=lap.n_samples if lap.n_samples is not None else len(lap.x),
        duration_s=duration,
        s=grid,
        x=x, y=y,
        x_smooth=xs, y_smooth=ys,
        theta=theta,
        kappa=kappa,
        altitude=columns.get('altitude'),
        speed=columns.get('speed'),
        elapsed=columns.get('elapsed'),
        corners=corners,
        straights=straights,
        direction_changes=dcs,
        spun=spun,
        heading_total_deg=total_deg,
        heading_budget={
            'corners_deg': corner_deg,
            'straights_deg': straight_deg,
            'subthreshold_deg': subthreshold_deg,
            'spin_dropped_deg': spin_dropped_deg,
            'residue_deg': (total_deg - corner_deg - straight_deg
                            - subthreshold_deg - spin_dropped_deg),
        },
        bbox=robust_bbox(x, y),
    )


def analyze_session(laps, params=DEFAULT_PARAMS):
    """Canonical lap validity for one session (plan Section 4.1 / decision D8).

    ``laps`` maps lap number -> LapInput for the session's numbered laps
    (lap_number >= 1; the caller filters). Validity: >= MIN_SAMPLES raw
    samples, duration within 0.65-1.5x the session median, resampled
    arclength within +-15% of the session median. Medians are taken over
    all numbered laps, matching Phase 1's provisional rule so the D8
    reconciliation compares like with like.

    The spin guard is a per-corner diagnostic, not a lap rejection
    (recalibrated on prod evidence — see ``segment_corners``): spun laps
    stay valid with their >300 deg sections excluded from the corner set.

    Returns SessionGeometry with valid laps (full geometry) and rejected
    laps with reasons.
    """
    stats = {}
    for num in laps:
        lap = laps[num]
        keep = dedupe_static(lap.x, lap.y, params.static_step_m)
        duration = None
        if lap.elapsed is not None and len(lap.elapsed) >= 2:
            duration = float(lap.elapsed[-1] - lap.elapsed[0])
        if keep.sum() >= 3:
            _, length = _arclength(np.asarray(lap.x, float)[keep],
                                    np.asarray(lap.y, float)[keep])
        else:
            length = 0.0
        n_samples = lap.n_samples if lap.n_samples is not None else len(lap.x)
        stats[num] = (n_samples, duration, length)

    durations = [d for _, d, _ in stats.values() if d is not None]
    lengths = [l for _, _, l in stats.values()]
    median_duration = float(np.median(durations)) if durations else None
    median_length = float(np.median(lengths)) if lengths else None

    valid, rejected = [], []
    for num in sorted(laps):
        n_samples, duration, length = stats[num]
        if n_samples < MIN_SAMPLES:
            rejected.append(RejectedLap(num, 'insufficient_samples',
                                        f'{n_samples} samples'))
            continue
        if median_duration and duration is not None:
            if not (0.65 * median_duration <= duration <= 1.5 * median_duration):
                rejected.append(RejectedLap(num, 'duration_out_of_range',
                                            f'{duration:.1f}s vs median {median_duration:.1f}s'))
                continue
        if median_length and not (0.85 * median_length <= length <= 1.15 * median_length):
            rejected.append(RejectedLap(num, 'length_out_of_range',
                                        f'{length:.0f}m vs median {median_length:.0f}m'))
            continue
        try:
            geo = analyze_lap(laps[num], params, lap_number=num)
        except ValueError as exc:
            rejected.append(RejectedLap(num, 'degenerate', str(exc)))
            continue
        valid.append(geo)

    return SessionGeometry(
        laps=valid,
        rejected=rejected,
        median_duration_s=median_duration,
        median_length_m=median_length,
    )
