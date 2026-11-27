"""Tests for the Track DNA elevation layer (plan Phase 6, spec Section 18).

Synthetic tests for the per-lap pipeline (offset correction, device
windows, drift balance, scatter flag), dimension 10 and the median
profile on reference-lap (single-lap) circuits.
"""

import json
import math

import numpy as np
import pytest

from scripts.analysis.track_dna import DEFAULT_PARAMS, LapInput, analyze_lap
from scripts.analysis.track_dna_elevation import (
    DEFAULT_ELEVATION_PARAMS,
    analyze_elevation,
)
from scripts.analysis.track_dna_reference import ConsensusLap, \
    reference_consensus
from tests.app.test_track_dna import (
    build_path,
    fixture_oval,
    roll_lap,
)

SPACING = 0.25


# ---- synthetic helpers ---------------------------------------------------------


def alt_input(points, altitudes, dt=0.04):
    x = np.asarray([p[0] for p in points], dtype=float)
    y = np.asarray([p[1] for p in points], dtype=float)
    n = len(points)
    return LapInput(x=x, y=y, altitude=np.asarray(altitudes, dtype=float),
                    speed=np.full(n, 15.0), elapsed=np.arange(n) * dt)


def tent(n, spacing, center_m, half_width_m, height_m):
    """Triangular hill altitude array (circular distance)."""
    idx = np.arange(n)
    d = np.abs((idx * spacing - center_m
                + n * spacing / 2) % (n * spacing) - n * spacing / 2)
    return height_m * np.maximum(0.0, 1.0 - d / half_width_m)


def wave(n, spacing, amplitude_m, wavelength_m, phase=0.0):
    s = np.arange(n) * spacing
    return amplitude_m * np.sin(2 * math.pi * s / wavelength_m + phase)


def elev_lap(user_id, session_id, points, altitudes, lap_number=1,
             device='racechrono'):
    return ConsensusLap(user_id=user_id, session_id=session_id,
                        lap_number=lap_number, device=device,
                        geometry=analyze_lap(alt_input(points, altitudes)))


def no_alt_lap(user_id, session_id, points, lap_number=1):
    x = np.asarray([p[0] for p in points], dtype=float)
    y = np.asarray([p[1] for p in points], dtype=float)
    return ConsensusLap(user_id=user_id, session_id=session_id,
                        lap_number=lap_number,
                        geometry=analyze_lap(LapInput(x=x, y=y)))


def reference_circuit(record):
    """The single-lap circuit object (what build_card feeds the layer)."""
    return reference_consensus(record, DEFAULT_PARAMS)


def asymmetric_loop():
    """A stadium with unequal straights and radii — no 180° symmetry."""
    return build_path([('straight', 100), ('arc', 30, -180),
                       ('straight', 60), ('arc', 45, -180)])


# ---- per-lap pipeline -----------------------------------------------------------


def test_flat_elevation_with_gps_noise():
    """Flat track + high-frequency GPS noise: the window kills the
    noise — ascent reads ~zero (unsmoothed, this noise would read
    ~25 m of phantom climbing), not noise-inflated."""
    pts = fixture_oval()
    n = len(pts)
    alt = wave(n, SPACING, 0.1, 5.0)
    elevation = analyze_elevation(reference_circuit(elev_lap(1, 1, pts,
                                                             alt)))
    assert elevation.n_laps_with_altitude == 1
    assert elevation.ascents_by_lap[0] < 0.5
    assert elevation.elevation_gain_per_km < 1.5


def test_single_hill_known_ascent():
    """One 3 m hill over the lap: ascent ~= 3 m and the dimension is
    ascent/km (boxcar apex attenuation is small at 25 m)."""
    pts = fixture_oval()
    n = len(pts)
    alt = tent(n, SPACING, 205.0, 200.0, 3.0)
    circuit = reference_circuit(elev_lap(1, 1, pts, alt))
    elevation = analyze_elevation(circuit)
    assert elevation.ascents_by_lap[0] == pytest.approx(3.0, rel=0.10)
    assert elevation.per_lap_median_m == pytest.approx(3.0, rel=0.10)
    gain = elevation.elevation_gain_per_km
    assert gain == pytest.approx(3.0 * 1000.0 / circuit.length_m,
                                 rel=0.10)
    summary = elevation.summary()
    dims = summary['dimensions']['elevation_gain']
    assert dims['unit'] == 'm/km'
    assert dims['value'] == pytest.approx(gain, abs=0.01)
    assert dims['per_lap_median_m'] == pytest.approx(3.0, rel=0.10)
    assert dims['window_by_device'] == {'racechrono': 25.0}


def test_altitude_offset_invariant():
    """A constant offset on the reference lap changes nothing: offset
    correction runs before aggregation."""
    pts = fixture_oval()
    n = len(pts)
    hill = tent(n, SPACING, 205.0, 200.0, 3.0)
    elevation = analyze_elevation(reference_circuit(
        elev_lap(1, 1, pts, hill + 100.0)))
    assert elevation.ascents_by_lap[0] == pytest.approx(3.0, rel=0.10)


def test_monotone_drift_breaks_balance():
    """A monotone intra-lap ramp unbalances the OPEN profile (the
    balance check); the circular ascent stays scale-invariant."""
    pts = fixture_oval()
    n = len(pts)
    ramp = np.linspace(0.0, 2.0, n)
    alt = tent(n, SPACING, 205.0, 200.0, 3.0) + ramp
    elevation = analyze_elevation(reference_circuit(elev_lap(1, 1, pts,
                                                             alt)))
    assert elevation.balance is not None
    assert elevation.balance['median'] > 1.2
    summary = elevation.summary()
    assert summary['evidence']['balance']['median'] > 1.2


def test_device_windows_applied():
    """The same wandering lap reads lower through the GoPro 50 m
    window than the RaceChrono 25 m window."""
    pts = fixture_oval()
    n = len(pts)
    hill = tent(n, SPACING, 205.0, 200.0, 1.5)
    noisy = hill + wave(n, SPACING, 0.3, 60.0)
    rc = analyze_elevation(reference_circuit(
        elev_lap(1, 1, pts, noisy, device='racechrono')))
    gopro = analyze_elevation(reference_circuit(
        elev_lap(1, 2, pts, noisy, device='gopro')))
    rc_ascent = rc.per_device['racechrono']['ascent_median_m']
    gopro_ascent = gopro.per_device['gopro']['ascent_median_m']
    clean = analyze_elevation(reference_circuit(
        elev_lap(1, 3, pts, hill))).ascents_by_lap[0]
    # the GoPro 50 m window suppresses the wander the 25 m window keeps
    assert rc_ascent > gopro_ascent
    # the wander still inflates the 25 m reading above the clean hill
    assert rc_ascent > clean
    # and the hill itself survives the 50 m window (device windows are
    # not so aggressive as to flatten real elevation)
    assert gopro_ascent > 1.0
    assert rc.summary()['dimensions']['elevation_gain'][
        'window_by_device'] == {'racechrono': 25.0}
    assert gopro.summary()['dimensions']['elevation_gain'][
        'window_by_device'] == {'gopro': 50.0}


def test_missing_altitude_is_coverage_not_zero():
    """A reference lap without an altitude channel yields no dimension
    10 (missing is coverage, never zero)."""
    pts = fixture_oval()
    elevation = analyze_elevation(reference_circuit(
        no_alt_lap(1, 1, pts)))
    assert elevation.n_laps == 1
    assert elevation.n_laps_with_altitude == 0
    assert elevation.elevation_gain_per_km is None
    summary = elevation.summary()
    assert summary['altitude_coverage'] == 0.0
    assert summary['dimensions']['elevation_gain']['value'] is None


def test_dimension_units():
    pts = fixture_oval()
    n = len(pts)
    circuit = reference_circuit(elev_lap(
        1, 1, pts, tent(n, SPACING, 205.0, 200.0, 6.0)))
    elevation = analyze_elevation(circuit)
    assert elevation.elevation_gain_per_km == pytest.approx(
        6.0 * 1000.0 / circuit.length_m, rel=0.12)
    spread = elevation.per_user['elevation_gain']
    assert spread[1]['n_laps'] == 1


def test_profile_maps_hill_position():
    """The median profile is the reference lap's own smoothed profile:
    the hill lands at its own lap-frame position."""
    pts = asymmetric_loop()
    n = len(pts)
    alt = tent(n, SPACING, 250.0, 120.0, 3.0)
    elevation = analyze_elevation(reference_circuit(elev_lap(1, 1, pts,
                                                             alt)))
    assert elevation.profile_s is not None
    peak_s = float(elevation.profile_s[int(np.argmax(elevation.profile_h))])
    assert peak_s == pytest.approx(250.0, abs=15.0)
    relief = float(elevation.profile_h.max() - elevation.profile_h.min())
    assert 2.0 < relief < 3.2
    summary = elevation.summary()
    profile = summary['profile']
    assert profile['step_m'] == pytest.approx(10.0)
    assert len(profile['points']) == len(elevation.profile_s)
    assert profile['relief_m'] == pytest.approx(relief, abs=0.01)


def test_scatter_flag():
    """Wandering altitude (u16-like) is flagged; a clean hill lap is
    not — evidence only, never an exclusion."""
    pts = fixture_oval()
    n = len(pts)
    clean = tent(n, SPACING, 205.0, 200.0, 1.5)
    wandering = clean + wave(n, SPACING, 2.0, 120.0)
    elevation = analyze_elevation(reference_circuit(
        elev_lap(2, 1, pts, wandering)))
    assert elevation.scatter_by_lap[0] > 1.2
    assert elevation.scatter['flagged_laps'] == 1
    assert elevation.scatter['flagged_by_user'] == {2: 1}
    clean_elev = analyze_elevation(reference_circuit(
        elev_lap(1, 1, pts, clean)))
    assert clean_elev.scatter_by_lap[0] < 1.2
    summary = elevation.summary()
    assert summary['evidence']['scatter'] == {
        'threshold_m': 1.2, 'flagged_laps': 1, 'flagged_by_user': {2: 1}}


def test_window_sensitivity_reported():
    """The summary records the dimension at uniform 10/25/50 m
    windows; ascent falls as the window grows, and the uniform window
    matching the device window reproduces the dimension exactly."""
    pts = fixture_oval()
    n = len(pts)
    alt = tent(n, SPACING, 205.0, 200.0, 3.0) + wave(n, SPACING, 0.2, 45.0)
    elevation = analyze_elevation(reference_circuit(elev_lap(1, 1, pts,
                                                             alt)))
    sens = elevation.window_sensitivity
    assert set(sens) == {10.0, 25.0, 50.0}
    assert sens[10.0] > sens[25.0] > sens[50.0]
    assert sens[25.0] == pytest.approx(elevation.elevation_gain_per_km,
                                       rel=1e-9)
    keys = elevation.summary()['evidence'][
        'window_sensitivity_m_per_km']
    assert set(keys) == {'10.0', '25.0', '50.0'}


def test_elevation_reproducible():
    pts = fixture_oval()
    n = len(pts)
    alt = tent(n, SPACING, 205.0, 200.0, 3.0) + wave(n, SPACING, 0.3, 70.0)
    record = elev_lap(1, 1, pts, alt)
    a = analyze_elevation(reference_circuit(record))
    b = analyze_elevation(reference_circuit(record))
    assert a.summary() == b.summary()


def test_consensus_lap_device_default():
    """The device field is additive: existing constructions default to
    'unknown' (and the default window applies)."""
    pts = fixture_oval()
    n = len(pts)
    lap = elev_lap(1, 1, pts, tent(n, SPACING, 205.0, 200.0, 3.0))
    assert lap.device == 'racechrono'
    plain = ConsensusLap(user_id=1, session_id=1, geometry=lap.geometry)
    assert plain.device == 'unknown'
    elevation = analyze_elevation(reference_circuit(plain))
    assert elevation.per_device['unknown']['window_m'] == 25.0
