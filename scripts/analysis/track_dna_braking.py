"""Track DNA braking layer (plan Phase 5, spec Section 17).

Dimension 9 (``heavy_braking_freq``) and consensus braking zones from
the Phase 3 engine output, built on the Phase 4 consensus frame.
NumPy/SciPy only — no app imports, matching the ``scripts/analysis/``
convention.

Design (owner-approved 2026-11-26, plan Section 17):

- **Sibling module**: the per-lap detector consumes ``LapGeometry``'s
  resampled ``speed`` channel and never touches the frozen engine —
  ``BrakingParams`` is deliberately separate from ``TrackDNAParams``
  (whose ``__dict__`` the golden regression pins byte-for-byte).
- **Events**: ``find_peaks`` on the wrap-median-filtered speed vs the
  1 m arclength grid — maxima (30 m apart, 0.3 m/s prominence) paired
  with the next minimum (15 m apart, 0.3 m/s prominence); relative
  reduction = (v_peak - v_trough) / v_peak. The search runs on the
  DOUBLED array so events straddling the s=0 seam are counted and
  seam-wrapping cruise plateaus keep full circular context; peaks are
  deduplicated by physical position and paired from their first-copy
  index (exactly circular, never off the array end). Known asymmetry,
  accepted: two maxima closer than the peak distance across the seam
  both survive (each in its own copy) where mid-lap one would be
  merged. Maxima on flat cruise sections localise imprecisely
  (plateau midpoints), so zones anchor on troughs.
- **Zones**: events with reduction >= 30% (the PoC recipe, Section 12
  — dimension 9 itself stays at 40% + 35/45% sensitivity, D5) have
  their troughs mapped into the consensus frame via the Phase 4
  alignment shifts and clustered with the Phase 4 recurrence-qualified
  clustering at >= 20% of laps. Zone recurrence is measured against
  laps WITH a usable speed channel — a lap that cannot observe
  braking never counts against a zone.
- **Dimension 9**: per-lap heavy events / km aggregated as a D6
  hierarchical median (lap -> session -> user -> circuit) over the
  speed-covered laps only (missing speed is coverage, never zero —
  missing != zero). Kiltorcan dry reads 0.00/km at 40% — legitimate,
  presented with the zone list and the sensitivity (D5).
- **Provenance** (D4): ``kart_category`` stays "mixed/unspecified"
  until a structured field exists.
"""

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import median_filter
from scipy.signal import find_peaks

from scripts.analysis.track_dna_reference import (
    _circular_median,
    _hierarchical,
    _recurrence_clusters,
    _user_spread,
)


@dataclass(frozen=True)
class BrakingParams:
    """v1.0 braking parameters (plan Sections 6/17.4, PoC-calibrated).

    Sibling of the engine's ``TrackDNAParams`` (frozen) and the
    consensus layer's ``ConsensusParams``; calibratable in-session per
    the Section 11 sweep (peak spacing x prominence).
    """

    heavy_threshold: float = 0.40     # dimension 9 heavy reduction (D5)
    sensitivity: tuple = (0.35, 0.45)  # reported alongside (D5)
    zone_threshold: float = 0.30      # zone eligibility (PoC recipe)
    zone_recurrence: float = 0.20     # min fraction of speed laps
    minor_zone_recurrence: float = 0.10  # Phase 8 minor-zone floor (plan
    #                                   # 20.4, owner-confirmed): clusters
    #                                   # in [10%, 20%) surface as
    #                                   # ``minor_zones`` evidence; zones
    #                                   # proper and dimension 9 are
    #                                   # untouched. Calibration: the 4th
    #                                   # Kiltorcan dry region sits at
    #                                   # 12.1%, the next-strongest chain
    #                                   # at 3.4% — nothing borderline.
    zone_cluster_m: float = 30.0      # trough cluster link tolerance
    zone_valley_min_m: float = 10.0   # valley-split floor (see 17.3)
    peak_distance_m: float = 30.0     # min spacing between maxima
    trough_distance_m: float = 15.0   # min spacing between minima
    prominence_ms: float = 0.3        # peak/trough prominence (m/s)
    speed_filter_m: float = 5.0       # wrap median filter on speed


DEFAULT_BRAKING_PARAMS = BrakingParams()


@dataclass
class BrakingEvent:
    """One peak->trough deceleration on a lap (threshold-free).

    ``s_peak``/``s_trough`` are lap-frame metre positions; ``s_peak``
    localises imprecisely on flat cruise sections (find_peaks plateau
    midpoints) — zone anchoring uses troughs.
    """

    s_peak: float
    s_trough: float
    v_peak: float
    v_trough: float
    reduction: float


@dataclass
class BrakingZone:
    """One recurring braking zone: a recurrence-qualified trough cluster.

    ``s_peak``/``s_trough`` are consensus-frame circular medians of the
    member events' mapped positions; ``recurrence`` is member laps over
    laps with a usable speed channel. ``support_by_user`` maps user id
    -> member laps / that user's speed-covered laps.
    """

    s_peak: float
    s_trough: float
    reduction_median: float
    n_laps: int
    recurrence: float
    member_events: int
    support_by_user: dict


@dataclass
class TrackBraking:
    """Full Phase 5 result for one track configuration and condition."""

    condition: str | None
    n_laps: int                        # consensus input laps
    n_laps_with_speed: int             # laps with a usable speed channel
    events_by_lap: list                # aligned; None = no speed channel
    zones: list                        # BrakingZone, sorted by s_trough
    heavy_freq_per_km: float | None    # dimension 9 at the heavy threshold
    sensitivity: dict                  # {'0.35': v, '0.45': v}
    reduction_percentiles: dict        # all events, percent
    events_per_lap_median: float | None
    per_user: dict
    kart_category: str = 'mixed/unspecified'   # D4 labels-only
    minor_zones: list = field(default_factory=list)
    #                                   # Phase 8 (plan 20.4): recurrence
    #                                   # in [minor_zone_recurrence,
    #                                   # zone_recurrence) — evidence only

    def summary(self):
        """JSON-serialisable summary (runner output, Phase 7 input)."""

        def _r(value, nd=2):
            return None if value is None else round(float(value), nd)

        def _zone_list(zone_list):
            return [{
                's_peak': _r(z.s_peak), 's_trough': _r(z.s_trough),
                'reduction_pct': _r(100.0 * z.reduction_median, 1),
                'n_laps': int(z.n_laps), 'recurrence': _r(z.recurrence, 3),
                'member_events': int(z.member_events),
                'support_by_user': {int(u): _r(v, 3)
                                    for u, v in sorted(
                                        z.support_by_user.items())},
            } for z in zone_list]

        zones = _zone_list(self.zones)
        per_user = {
            metric: {int(u): {'n_laps': stats['n_laps'],
                              'median': _r(stats['median'], 3),
                              'p10': _r(stats['p10'], 3),
                              'p90': _r(stats['p90'], 3)}
                     for u, stats in sorted(users.items())}
            for metric, users in self.per_user.items()
        }
        return {
            'condition': self.condition,
            'kart_category': self.kart_category,
            'n_laps': self.n_laps,
            'n_laps_with_speed': self.n_laps_with_speed,
            'speed_coverage': (_r(self.n_laps_with_speed / self.n_laps, 3)
                               if self.n_laps else None),
            'dimensions': {
                'heavy_braking_freq': {
                    'value': _r(self.heavy_freq_per_km, 3),
                    'unit': 'events/km',
                    'threshold': 0.40,
                    'sensitivity': {str(k): _r(v, 3)
                                    for k, v in self.sensitivity.items()},
                },
            },
            'zones': zones,
            'minor_zones': _zone_list(self.minor_zones),
            'evidence': {
                'reduction_percentiles': self.reduction_percentiles,
                'events_per_lap_median': _r(self.events_per_lap_median, 2),
            },
            'per_user': per_user,
        }


# ---- per-lap event detection ---------------------------------------------------


def detect_lap_events(geo, params=DEFAULT_BRAKING_PARAMS):
    """Braking events for one lap, or ``None`` without a usable speed
    channel (coverage — missing is never zero).

    Peak/trough search runs on the doubled speed array so events whose
    peak->trough window crosses the s=0 seam are counted and cruise
    plateaus wrapping the seam keep full circular context. The doubled
    array reports most peaks twice (at ``p`` and ``p+n``); peaks are
    deduplicated by physical position, first occurrence kept — a
    seam-wrapping cruise plateau is reported only once, at the run
    crossing index ``n``, which may map to any physical position.
    Pairing starts from the peak's first-copy index: every physical
    minimum has a twin at ``+n``, so the next-minimum search always
    resolves within the doubled array and is exactly circular.
    """
    speed = geo.speed
    if speed is None:
        return None
    v = np.asarray(speed, dtype=float)
    if v.size < 8:
        return None
    if not np.isfinite(v).all():
        ok = np.isfinite(v)
        if not ok.any():
            return None
        v = np.interp(np.arange(v.size), np.flatnonzero(ok), v[ok])

    size = int(round(params.speed_filter_m))
    if size >= 2:
        if size % 2 == 0:
            size += 1
        vf = median_filter(v, size=size, mode='wrap')
    else:
        vf = v

    n = vf.size
    v2 = np.concatenate([vf, vf])
    maxima, _ = find_peaks(v2, distance=params.peak_distance_m,
                           prominence=params.prominence_ms)
    minima, _ = find_peaks(-v2, distance=params.trough_distance_m,
                           prominence=params.prominence_ms)

    events = []
    seen = set()
    for mi in maxima:
        mi = int(mi)
        physical = mi % n
        if physical in seen:
            continue                   # twin of an already-kept peak (the
        seen.add(physical)             # doubled array reports each peak
        start = physical               # twice, except seam-wrapping cruise
        j = int(np.searchsorted(minima, start, side='right'))
        if j >= minima.size:
            continue
        ti = int(minima[j])
        v_peak = float(v2[physical])
        v_trough = float(v2[ti])
        if v_peak <= 0.0:
            continue
        reduction = (v_peak - v_trough) / v_peak
        if reduction <= 0.0:
            continue
        events.append(BrakingEvent(
            s_peak=float(geo.s[physical]), s_trough=float(geo.s[ti % n]),
            v_peak=v_peak, v_trough=v_trough, reduction=reduction))
    return events


# ---- zones and dimension 9 -----------------------------------------------------


def analyze_braking(consensus, params=DEFAULT_BRAKING_PARAMS):
    """Dimension 9 + braking zones for one condition's consensus.

    ``consensus`` is a :class:`TrackConsensus` (the reference-lap
    circuit object) — the alignment shifts map each lap's event
    positions into the circuit frame.
    Laps without a usable speed channel are coverage, never zero: the
    dimension and zone recurrence use the speed-covered laps only.
    """
    laps = consensus.laps
    n = len(laps)
    length_c = consensus.length_m

    events_by_lap = [detect_lap_events(lap.geometry, params)
                     for lap in laps]
    speed_idx = [i for i, ev in enumerate(events_by_lap) if ev is not None]
    laps_speed = [laps[i] for i in speed_idx]
    n_speed = len(speed_idx)

    # zone candidates: qualifying events mapped into the consensus frame
    mapped = []      # (lap_index, event, m_peak, m_trough)
    for i in speed_idx:
        lap = laps[i]
        length = lap.geometry.length_m
        frac = float(consensus.shifts_m[i]) / length
        for event in events_by_lap[i]:
            if event.reduction < params.zone_threshold:
                continue
            mapped.append((i, event,
                           ((event.s_peak / length) - frac) % 1.0 * length_c,
                           ((event.s_trough / length) - frac) % 1.0
                           * length_c))

    n_speed_by_user = defaultdict(int)
    for lap in laps_speed:
        n_speed_by_user[lap.user_id] += 1

    def _zone_from_cluster(cluster):
        member_laps = {mapped[j][0] for j in cluster}
        support_by_user = {}
        for uid, total in n_speed_by_user.items():
            hits = len({mapped[j][0] for j in cluster
                        if laps[mapped[j][0]].user_id == uid})
            support_by_user[uid] = hits / total
        return BrakingZone(
            s_peak=_circular_median([mapped[j][2] for j in cluster],
                                    length_c),
            s_trough=_circular_median([mapped[j][3] for j in cluster],
                                      length_c),
            reduction_median=float(np.median(
                [mapped[j][1].reduction for j in cluster])),
            n_laps=len(member_laps),
            recurrence=len(member_laps) / n_speed,
            member_events=len(cluster),
            support_by_user=support_by_user)

    def _circ_dist(a, b):
        d = abs(a - b) % length_c
        return min(d, length_c - d)

    zones = []
    if n_speed and mapped:
        min_laps = params.zone_recurrence * n_speed
        clusters = _recurrence_clusters(
            [m[3] for m in mapped], [m[0] for m in mapped],
            params.zone_cluster_m, length_c, min_laps,
            params.zone_valley_min_m)
        for cluster in clusters:
            member_laps = {mapped[j][0] for j in cluster}
            if len(member_laps) < min_laps:
                continue
            zones.append(_zone_from_cluster(cluster))
        zones.sort(key=lambda z: z.s_trough)

    # Phase 8 minor-zone tier (plan 20.4): a second, lower-gate pass
    # surfaces clusters in [minor_zone_recurrence, zone_recurrence) as
    # evidence. The zone pass above is untouched, so the delivered zone
    # set stays byte-identical; minor candidates at or above the zone
    # gate, or within a cluster tolerance of a reported zone, are
    # skipped (the two clusterings can land a few metres apart).
    minor_zones = []
    if (n_speed and mapped
            and params.minor_zone_recurrence < params.zone_recurrence):
        minor_min = params.minor_zone_recurrence * n_speed
        minor_clusters = _recurrence_clusters(
            [m[3] for m in mapped], [m[0] for m in mapped],
            params.zone_cluster_m, length_c, minor_min,
            params.zone_valley_min_m)
        for cluster in minor_clusters:
            member_laps = {mapped[j][0] for j in cluster}
            if len(member_laps) < minor_min:
                continue
            zone = _zone_from_cluster(cluster)
            if zone.recurrence >= params.zone_recurrence:
                continue
            if any(_circ_dist(zone.s_trough, z.s_trough)
                   <= params.zone_cluster_m for z in zones):
                continue
            minor_zones.append(zone)
        minor_zones.sort(key=lambda z: z.s_trough)

    # dimension 9: heavy events/km, hierarchical over speed-covered laps
    thresholds = (params.heavy_threshold,) + tuple(params.sensitivity)
    per_lap = {thr: [] for thr in thresholds}
    for i in speed_idx:
        km = laps[i].geometry.length_m / 1000.0
        counts = {thr: 0 for thr in thresholds}
        for event in events_by_lap[i]:
            for thr in thresholds:
                if event.reduction >= thr:
                    counts[thr] += 1
        for thr in thresholds:
            per_lap[thr].append(counts[thr] / km)

    heavy = per_lap[params.heavy_threshold]
    heavy_freq = _hierarchical(heavy, laps_speed)[0] if laps_speed else None
    sensitivity = {}
    for thr in params.sensitivity:
        sensitivity[thr] = (_hierarchical(per_lap[thr], laps_speed)[0]
                            if laps_speed else None)
    per_user = {
        'heavy_braking_freq': _user_spread(laps_speed, heavy)
    } if laps_speed else {}

    all_reductions = [event.reduction for events in events_by_lap
                      if events for event in events]
    if all_reductions:
        percentiles = {f'p{p}': round(100.0 * float(
            np.percentile(all_reductions, p)), 1)
            for p in (50, 75, 90, 95)}
        percentiles['max'] = round(100.0 * max(all_reductions), 1)
    else:
        percentiles = {}
    counts_speed = [len(events) for events in events_by_lap
                    if events is not None]
    events_per_lap_median = (float(np.median(counts_speed))
                             if counts_speed else None)

    return TrackBraking(
        condition=consensus.condition,
        n_laps=n,
        n_laps_with_speed=n_speed,
        events_by_lap=events_by_lap,
        zones=zones,
        heavy_freq_per_km=heavy_freq,
        sensitivity=sensitivity,
        reduction_percentiles=percentiles,
        events_per_lap_median=events_per_lap_median,
        per_user=per_user,
        minor_zones=minor_zones,
    )
