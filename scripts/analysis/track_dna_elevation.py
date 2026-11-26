"""Track DNA elevation layer (plan Phase 6, spec Section 18).

Dimension 10 (``elevation_gain``), the consensus median altitude
profile and elevation evidence from the Phase 3 engine output, built
on the Phase 4 consensus frame. NumPy/SciPy only — no app imports,
matching the ``scripts/analysis/`` convention.

Design (owner-approved 2026-11-26, plan Section 18):

- **Sibling module**: consumes ``LapGeometry.altitude`` (the frozen
  engine already resamples it onto the 1 m arclength grid) and never
  touches the engine — ``ElevationParams`` is deliberately separate
  from ``TrackDNAParams`` (whose ``__dict__`` the golden regression
  pins byte-for-byte).
- **Device = session ``data_source``** ('racechrono' / 'gopro'), the
  only per-session device signal; ``ConsensusLap`` carries it (fields
  added in Phase 6, default 'unknown'). Device-aware boxcar windows:
  RaceBox-class 25 m, GoPro 50 m (the PoC recipe).
- **Per-lap pipeline**: offset-correct (subtract the per-lap median),
  then a wrap-mode boxcar on the 1 m grid. Boxcar over median filter:
  the prod prototype showed per-lap ascent within ~0.2 m of each other.
- **Dimension 10** = per-lap ascent — the circular sum of positive
  diffs of the smoothed profile (the total climb of the closed loop;
  offset-invariant) — divided by lap km, aggregated as a D6
  hierarchical median (lap -> session -> user -> circuit) over
  altitude-covered laps. Missing altitude is coverage, never zero
  (missing != zero, the D5/D8 pattern). Reported in m/km (the
  normalisation anchor unit) with per-lap metres in evidence.
- **Balance is OPEN-profile**: on circular diffs ascent == descent is
  a mathematical identity (verified on prod: exactly 1.000 for every
  lap), so the PoC's "ascent == descent" check is only meaningful on
  the open profile (first -> last sample), where the mismatch exposes
  endpoint drift. Evidence-level, acceptance |balance - 1| <= 0.20.
- **Known deviation, documented (18.7)**: the PoC claim "u16's GoPro
  13 m -> ~6-7 m with a 50 m window" does not reproduce (measured
  10.0 m per-lap) — u16's altitude error is low-frequency wander
  (detrended std 1.68 m vs 0.67 m clean), which no <= 50 m boxcar
  removes. The shipped windows stay at the PoC's own 25/50 m: the D6
  hierarchy absorbs the outlier user at circuit level (Kiltorcan dry
  reads 6.2 m/lap, the PoC anchor), and the wander is surfaced via
  the scatter flag (below) rather than hidden. Phase 8's confidence
  classes are the designated place to act on it.
- **Scatter flag (evidence only)**: per-lap std of the linearly
  detrended altitude — empirically separates clean devices (prod
  median 0.67 m, p90 <= 1.13 m) from wandering GoPro laps (median
  1.68 m). Real relief contributes to it on gentle circuits; the
  1.2 m threshold is calibrated on the prod distribution, not derived.
- **Consensus median profile**: each lap's smoothed offset-corrected
  profile sampled into the consensus frame via the Phase 4 alignment
  shifts (the inverse of the braking event mapping), then a
  per-grid-point median across laps — Phase 9's sparkline input.
"""

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import uniform_filter1d

from scripts.analysis.track_dna_consensus import _hierarchical, _user_spread


@dataclass(frozen=True)
class ElevationParams:
    """v1.0 elevation parameters (plan Sections 6/18.4, PoC-calibrated).

    Sibling of the engine's ``TrackDNAParams`` (frozen) and the
    consensus/braking layers' params; the windows are the Section 11
    sweep's subject.
    """

    windows_m: dict = field(default_factory=lambda: {
        'racechrono': 25.0,     # RaceBox-class GPS via RaceChrono
        'gopro': 50.0,          # GoPro-built-in GPS (video extract)
    })
    default_window_m: float = 25.0       # unknown data sources
    profile_step_m: float = 10.0         # summary profile decimation
    scatter_threshold_m: float = 1.2     # wandering-altitude flag
    sensitivity_windows_m: tuple = (10.0, 25.0, 50.0)  # evidence sweep


DEFAULT_ELEVATION_PARAMS = ElevationParams()


@dataclass
class TrackElevation:
    """Full Phase 6 result for one track configuration and condition."""

    condition: str | None
    n_laps: int                        # consensus input laps
    n_laps_with_altitude: int          # laps with a usable altitude channel
    ascents_by_lap: list               # aligned; None = no altitude (m)
    balances_by_lap: list              # aligned; open ascent/descent or None
    scatter_by_lap: list               # aligned; detrended std (m) or None
    profiles_by_lap: list              # aligned; smoothed profiles or None
    elevation_gain_per_km: float | None    # dimension 10 (device windows)
    per_lap_median_m: float | None
    balance: dict | None               # {'median','p10','p90'} of the ratio
    per_device: dict                   # device -> n_laps + ascent median (m)
    cross_device_gap: float | None     # (max-min)/min across device medians
    window_sensitivity: dict           # uniform-window dimension (m/km)
    scatter: dict                      # flagged laps + per-user breakdown
    profile_s: np.ndarray | None       # consensus median profile grid (m)
    profile_h: np.ndarray | None       # consensus median profile heights (m)
    per_user: dict

    def summary(self):
        """JSON-serialisable summary (runner output, Phase 7 input)."""

        def _r(value, nd=2):
            return None if value is None else round(float(value), nd)

        ascents = [a for a in self.ascents_by_lap if a is not None]
        profile = None
        if (self.profile_s is not None and self.profile_h is not None
                and self.profile_s.size >= 2):
            profile = {
                'step_m': _r(float(np.mean(np.diff(self.profile_s))), 1),
                'relief_m': _r(float(self.profile_h.max()
                                     - self.profile_h.min())),
                'points': [[_r(s, 1), _r(h)]
                           for s, h in zip(self.profile_s, self.profile_h)],
            }
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
            'n_laps': self.n_laps,
            'n_laps_with_altitude': self.n_laps_with_altitude,
            'altitude_coverage': (_r(self.n_laps_with_altitude / self.n_laps,
                                     3) if self.n_laps else None),
            'dimensions': {
                'elevation_gain': {
                    'value': _r(self.elevation_gain_per_km, 3),
                    'unit': 'm/km',
                    'per_lap_median_m': _r(self.per_lap_median_m),
                    'window_by_device': {
                        dev: _r(stats['window_m'])
                        for dev, stats in sorted(self.per_device.items())},
                },
            },
            'evidence': {
                'ascent_m': {
                    'per_lap_median': _r(float(np.median(ascents)))
                    if ascents else None,
                    'p10': _r(float(np.percentile(ascents, 10)))
                    if ascents else None,
                    'p90': _r(float(np.percentile(ascents, 90)))
                    if ascents else None,
                },
                'balance': self.balance,
                'per_device': {
                    dev: {'n_laps': int(stats['n_laps']),
                          'ascent_median_m': _r(stats['ascent_median_m'])}
                    for dev, stats in sorted(self.per_device.items())},
                'cross_device_gap': _r(self.cross_device_gap, 3),
                'window_sensitivity_m_per_km': {
                    str(w): _r(v, 3)
                    for w, v in self.window_sensitivity.items()},
                'scatter': {
                    'threshold_m': _r(self.scatter['threshold_m']),
                    'flagged_laps': int(self.scatter['flagged_laps']),
                    'flagged_by_user': {int(u): int(c) for u, c
                                        in sorted(
                                            self.scatter['flagged_by_user']
                                            .items())},
                },
            },
            'profile': profile,
            'per_user': per_user,
        }


# ---- per-lap pipeline -----------------------------------------------------------


def _window_for(device, params):
    return float(params.windows_m.get(device, params.default_window_m))


def _lap_profile(geo, window_m):
    """Offset-corrected, boxcar-smoothed altitude on the 1 m grid — or
    ``None`` without a usable altitude channel (coverage — missing is
    never zero)."""

    if geo.altitude is None:
        return None
    v = np.asarray(geo.altitude, dtype=float)
    if v.size < 8:
        return None
    if not np.isfinite(v).all():
        ok = np.isfinite(v)
        if not ok.any():
            return None
        v = np.interp(np.arange(v.size), np.flatnonzero(ok), v[ok])
    v = v - float(np.median(v))
    size = int(round(window_m))
    if size >= 2:
        if size % 2 == 0:
            size += 1
        return uniform_filter1d(v, size=size, mode='wrap')
    return v


def _ascent_circular(profile):
    """Total climb of the closed loop (m): positive circular diffs."""
    d = np.diff(np.append(profile, profile[0]))
    return float(d[d > 0].sum())


def _asc_desc_open(profile, margin=0):
    """Open-profile ascent/descent (m) — their mismatch is endpoint
    drift (the balance check; circular diffs are an identity).

    ``margin`` grid points are cut from each end: the wrap-mode boxcar
    smears any seam discontinuity (raw end-start drift) into the first
    and last half-window, which would convert drift into artificial
    descent and re-balance the profile. The interior diffs keep the
    honest within-lap climb/descent split — their net still carries
    ~((n - w)/n) of the drift."""
    d = np.diff(profile)
    if margin > 0:
        d = d[margin:profile.size - 1 - margin]
    return float(d[d > 0].sum()), float(-d[d < 0].sum())


def _scatter(altitude):
    """Std of the linearly detrended raw altitude (m) — the wander/noise
    scale. Real relief contributes on gentle circuits; the flag
    threshold is calibrated on the prod distribution (18.3)."""
    if altitude is None:
        return None
    v = np.asarray(altitude, dtype=float)
    if v.size < 8 or not np.isfinite(v).all():
        return None
    t = np.arange(v.size, dtype=float)
    trend = np.polyval(np.polyfit(t, v, 1), t)
    return float(np.std(v - trend))


def _sample_circular(profile, positions):
    """Interpolate a lap-grid profile at metre ``positions`` in
    ``[0, lap length)`` with circular wrap (doubled array)."""
    n = profile.size
    xs = np.arange(2 * n, dtype=float)
    vals = np.concatenate([profile, profile])
    return np.interp(np.asarray(positions, dtype=float), xs, vals)


# ---- dimension 10, evidence and profile -----------------------------------------


def analyze_elevation(consensus, params=DEFAULT_ELEVATION_PARAMS):
    """Dimension 10 + elevation evidence and the consensus median
    profile for one condition's consensus.

    ``consensus`` is a Phase 4 :class:`TrackConsensus`; the alignment
    shifts map consensus-frame positions into each lap's frame (the
    inverse of the braking event mapping). Laps without a usable
    altitude channel are coverage, never zero: the dimension, evidence
    and profile use the altitude-covered laps only.
    """
    laps = consensus.laps
    n = len(laps)
    length_c = consensus.length_m

    profiles = [_lap_profile(lap.geometry, _window_for(lap.device, params))
                for lap in laps]
    alt_idx = [i for i, p in enumerate(profiles) if p is not None]
    laps_alt = [laps[i] for i in alt_idx]
    n_alt = len(alt_idx)

    ascents = [None] * n
    balances = [None] * n
    scatters = [_scatter(lap.geometry.altitude) for lap in laps]
    for i in alt_idx:
        profile = profiles[i]
        ascents[i] = _ascent_circular(profile)
        window = _window_for(laps[i].device, params)
        up, down = _asc_desc_open(profile,
                                  margin=int(round(window)) // 2)
        balances[i] = (up / down) if down > 0 else None

    # dimension 10: per-lap ascent / km, D6 hierarchical
    gains = [ascents[i] * 1000.0 / laps[i].geometry.length_m
             for i in alt_idx]
    gain = _hierarchical(gains, laps_alt)[0] if laps_alt else None
    per_user = ({'elevation_gain': _user_spread(laps_alt, gains)}
                if laps_alt else {})

    ratios = [b for b in balances if b is not None and np.isfinite(b)]
    balance = ({'median': float(np.median(ratios)),
                'p10': float(np.percentile(ratios, 10)),
                'p90': float(np.percentile(ratios, 90))}
               if ratios else None)

    by_device = defaultdict(list)
    window_by_device = {}
    for i in alt_idx:
        device = laps[i].device
        by_device[device].append(ascents[i])
        window_by_device[device] = _window_for(device, params)
    per_device = {device: {'n_laps': len(values),
                           'ascent_median_m': float(np.median(values)),
                           'window_m': window_by_device[device]}
                  for device, values in sorted(by_device.items())}
    major = [stats for stats in per_device.values()
             if stats['n_laps'] >= 5]
    cross_device_gap = None
    if len(major) >= 2:
        medians = [s['ascent_median_m'] for s in major]
        if min(medians) > 0:
            cross_device_gap = (max(medians) - min(medians)) / min(medians)

    window_sensitivity = {}
    for w in params.sensitivity_windows_m:
        values = []
        for i in alt_idx:
            profile = _lap_profile(laps[i].geometry, float(w))
            values.append(_ascent_circular(profile) * 1000.0
                          / laps[i].geometry.length_m)
        window_sensitivity[float(w)] = (_hierarchical(values, laps_alt)[0]
                                        if laps_alt else None)

    flagged_by_user = defaultdict(int)
    flagged = 0
    for i in alt_idx:
        if scatters[i] is not None and scatters[i] > params.scatter_threshold_m:
            flagged += 1
            flagged_by_user[laps[i].user_id] += 1

    profile_s = profile_h = None
    if n_alt:
        grid = np.arange(0.0, length_c, params.profile_step_m)
        samples = []
        for i in alt_idx:
            lap = laps[i]
            length = lap.geometry.length_m
            frac = float(consensus.shifts_m[i]) / length
            positions = ((grid / length_c) + frac) % 1.0 * length
            samples.append(_sample_circular(profiles[i], positions))
        profile_s = grid
        profile_h = np.median(np.vstack(samples), axis=0)

    return TrackElevation(
        condition=consensus.condition,
        n_laps=n,
        n_laps_with_altitude=n_alt,
        ascents_by_lap=ascents,
        balances_by_lap=balances,
        scatter_by_lap=scatters,
        profiles_by_lap=profiles,
        elevation_gain_per_km=gain,
        per_lap_median_m=(float(np.median([ascents[i] for i in alt_idx]))
                          if alt_idx else None),
        balance=balance,
        per_device=per_device,
        cross_device_gap=cross_device_gap,
        window_sensitivity=window_sensitivity,
        scatter={'threshold_m': params.scatter_threshold_m,
                 'flagged_laps': flagged,
                 'flagged_by_user': dict(flagged_by_user)},
        profile_s=profile_s,
        profile_h=profile_h,
        per_user=per_user,
    )
