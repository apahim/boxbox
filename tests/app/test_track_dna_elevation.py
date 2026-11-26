"""Tests for the Track DNA elevation layer (plan Phase 6, spec Section 18).

Synthetic tests for the per-lap pipeline (offset correction, device
windows, drift balance, scatter flag), dimension 10, the consensus
median profile mapping, plus smoke tests for the read-only runner's
elevation section.
"""

import json
import math

import numpy as np
import pytest

from scripts.analysis.track_dna import LapInput, analyze_lap
from scripts.analysis.track_dna_consensus import ConsensusLap, build_consensus
from scripts.analysis.track_dna_elevation import (
    DEFAULT_ELEVATION_PARAMS,
    analyze_elevation,
)
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


def asymmetric_loop():
    """A stadium with unequal straights and radii — no 180° symmetry,
    so the FFT alignment has a unique best shift (the oval's symmetry
    alias would exercise the zero-shift preference instead)."""
    return build_path([('straight', 100), ('arc', 30, -180),
                       ('straight', 60), ('arc', 45, -180)])


def oval_laps(altitudes_by_lap, user_id=1, session_id=1, device='racechrono'):
    pts = fixture_oval()
    return [elev_lap(user_id, session_id, pts, alt, lap_number=i + 1,
                     device=device)
            for i, alt in enumerate(altitudes_by_lap)]


# ---- per-lap pipeline -----------------------------------------------------------


def test_flat_elevation_with_gps_noise():
    """Flat track + high-frequency GPS noise: the window kills the
    noise — ascent reads ~zero (unsmoothed, this noise would read
    ~25 m of phantom climbing), not noise-inflated."""
    pts = fixture_oval()
    n = len(pts)
    alt = wave(n, SPACING, 0.1, 5.0)
    elevation = analyze_elevation(build_consensus(oval_laps([alt])))
    assert elevation.n_laps_with_altitude == 1
    assert elevation.ascents_by_lap[0] < 0.5
    assert elevation.elevation_gain_per_km < 1.5


def test_single_hill_known_ascent():
    """One 3 m hill over the lap: ascent ~= 3 m and the dimension is
    ascent/km (boxcar apex attenuation is small at 25 m)."""
    pts = fixture_oval()
    n = len(pts)
    alt = tent(n, SPACING, 205.0, 200.0, 3.0)
    elevation = analyze_elevation(build_consensus(oval_laps([alt])))
    assert elevation.ascents_by_lap[0] == pytest.approx(3.0, rel=0.10)
    assert elevation.per_lap_median_m == pytest.approx(3.0, rel=0.10)
    consensus = build_consensus(oval_laps([alt]))
    gain = elevation.elevation_gain_per_km
    assert gain == pytest.approx(3.0 * 1000.0 / consensus.length_m,
                                 rel=0.10)
    summary = elevation.summary()
    dims = summary['dimensions']['elevation_gain']
    assert dims['unit'] == 'm/km'
    assert dims['value'] == pytest.approx(gain, abs=0.01)
    assert dims['per_lap_median_m'] == pytest.approx(3.0, rel=0.10)
    assert dims['window_by_device'] == {'racechrono': 25.0}


def test_altitude_offset_invariant():
    """A constant per-lap offset changes nothing: offset correction
    aligns laps before aggregation."""
    pts = fixture_oval()
    n = len(pts)
    hill = tent(n, SPACING, 205.0, 200.0, 3.0)
    laps = oval_laps([hill, hill, hill + 100.0, hill - 40.0])
    elevation = analyze_elevation(build_consensus(laps))
    ascents = [a for a in elevation.ascents_by_lap if a is not None]
    assert max(ascents) - min(ascents) < 1e-6
    assert elevation.ascents_by_lap[0] == pytest.approx(3.0, rel=0.10)


def test_monotone_drift_breaks_balance():
    """A monotone intra-lap ramp unbalances the OPEN profile (the
    balance check); the circular ascent stays scale-invariant."""
    pts = fixture_oval()
    n = len(pts)
    ramp = np.linspace(0.0, 2.0, n)
    alt = tent(n, SPACING, 205.0, 200.0, 3.0) + ramp
    elevation = analyze_elevation(build_consensus(oval_laps([alt])))
    assert elevation.balance is not None
    assert elevation.balance['median'] > 1.2
    summary = elevation.summary()
    assert summary['evidence']['balance']['median'] > 1.2


def test_device_windows_applied():
    """The same wandering lap reads lower through the GoPro 50 m
    window than the RaceChrono 25 m window; wavelengths between the
    windows survive both."""
    pts = fixture_oval()
    n = len(pts)
    hill = tent(n, SPACING, 205.0, 200.0, 1.5)
    noisy = hill + wave(n, SPACING, 0.3, 60.0)
    laps = ([elev_lap(1, 1, pts, noisy, i + 1, device='racechrono')
             for i in range(5)]
            + [elev_lap(1, 2, pts, noisy, i + 1, device='gopro')
               for i in range(5)])
    elevation = analyze_elevation(build_consensus(laps))
    rc = elevation.per_device['racechrono']['ascent_median_m']
    gopro = elevation.per_device['gopro']['ascent_median_m']
    clean = analyze_elevation(
        build_consensus(oval_laps([hill]))).ascents_by_lap[0]
    # the GoPro 50 m window suppresses the wander the 25 m window keeps
    assert rc > gopro
    # the wander still inflates the 25 m reading above the clean hill
    assert rc > clean
    # and the hill itself survives the 50 m window (device windows are
    # not so aggressive as to flatten real elevation)
    assert gopro > 1.0
    # the gap needs >= 5 laps per device (spec 18.3)
    assert elevation.cross_device_gap == pytest.approx(
        (rc - gopro) / gopro, rel=0.01)
    summary = elevation.summary()
    assert summary['dimensions']['elevation_gain'][
        'window_by_device'] == {'gopro': 50.0, 'racechrono': 25.0}
    assert summary['evidence']['per_device']['gopro']['n_laps'] == 5


def test_missing_altitude_is_coverage_not_zero():
    """Laps without an altitude channel never dilute dimension 10
    (missing is coverage, not zero)."""
    pts = fixture_oval()
    n = len(pts)
    hill = tent(n, SPACING, 205.0, 200.0, 3.0)
    with_alt = oval_laps([hill, hill], user_id=1, session_id=1)
    without = [no_alt_lap(1, 2, pts, i + 1) for i in range(2)]
    elevation = analyze_elevation(
        build_consensus(with_alt + without))
    only = analyze_elevation(build_consensus(with_alt))
    assert elevation.n_laps == 4
    assert elevation.n_laps_with_altitude == 2
    assert elevation.elevation_gain_per_km == pytest.approx(
        only.elevation_gain_per_km, rel=1e-9)
    summary = elevation.summary()
    assert summary['altitude_coverage'] == 0.5
    assert summary['n_laps_with_altitude'] == 2


def test_dimension_hierarchy_and_units():
    """D6 hierarchy: session medians -> user medians -> circuit median
    (u1: sessions at 6 m and 2 m -> 4; u2: 8 m; circuit 6 m/km-scale)."""
    pts = fixture_oval()
    n = len(pts)
    laps = (oval_laps([tent(n, SPACING, 205.0, 200.0, 6.0)],
                      user_id=1, session_id=1)
            + oval_laps([tent(n, SPACING, 205.0, 200.0, 2.0)],
                        user_id=1, session_id=2)
            + oval_laps([tent(n, SPACING, 205.0, 200.0, 8.0)],
                        user_id=2, session_id=3))
    consensus = build_consensus(laps)
    elevation = analyze_elevation(consensus)
    assert elevation.elevation_gain_per_km == pytest.approx(
        6.0 * 1000.0 / consensus.length_m, rel=0.12)
    spread = elevation.per_user['elevation_gain']
    assert spread[1]['n_laps'] == 2
    assert spread[2]['n_laps'] == 1
    # u1's flat median sits between its two sessions; u2 reads highest
    assert spread[1]['median'] < spread[2]['median']


def test_median_profile_maps_hill_to_consensus_frame():
    """A rolled lap's hill lands at the consensus-frame position of
    the unrolled lap's hill (alignment-shift mapping, the inverse of
    the braking event mapping)."""
    pts = asymmetric_loop()
    n = len(pts)
    alt = tent(n, SPACING, 250.0, 120.0, 3.0)
    k = int(150 / SPACING)
    rolled_alt = np.roll(alt, -k)
    laps = [elev_lap(1, 1, pts, alt, 1),
            elev_lap(1, 2, roll_lap(pts, k), rolled_alt, 1)]
    elevation = analyze_elevation(build_consensus(laps))
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
    # the rolled lap's own frame puts the hill 150 m earlier
    solo = analyze_elevation(build_consensus(
        [elev_lap(1, 2, roll_lap(pts, k), rolled_alt, 1)]))
    solo_peak = float(solo.profile_s[int(np.argmax(solo.profile_h))])
    assert solo_peak == pytest.approx(100.0, abs=15.0)


def test_scatter_flag():
    """Wandering altitude (u16-like) is flagged; a clean hill lap is
    not — evidence only, never an exclusion."""
    pts = fixture_oval()
    n = len(pts)
    clean = tent(n, SPACING, 205.0, 200.0, 1.5)
    wandering = clean + wave(n, SPACING, 2.0, 120.0)
    laps = [elev_lap(1, 1, pts, clean, 1),
            elev_lap(2, 1, pts, wandering, 1)]
    elevation = analyze_elevation(build_consensus(laps))
    assert elevation.scatter_by_lap[0] < 1.2
    assert elevation.scatter_by_lap[1] > 1.2
    assert elevation.scatter['flagged_laps'] == 1
    assert elevation.scatter['flagged_by_user'] == {2: 1}
    summary = elevation.summary()
    assert summary['evidence']['scatter'] == {
        'threshold_m': 1.2, 'flagged_laps': 1, 'flagged_by_user': {2: 1}}


def test_cross_device_agreement_clean_profile():
    """The same clean hill through both device windows agrees within
    the acceptance tolerance (cross-device +-15%)."""
    pts = fixture_oval()
    n = len(pts)
    hill = tent(n, SPACING, 205.0, 200.0, 3.0)
    laps = ([elev_lap(1, 1, pts, hill, i + 1, device='racechrono')
             for i in range(5)]
            + [elev_lap(1, 2, pts, hill, i + 1, device='gopro')
               for i in range(5)])
    elevation = analyze_elevation(build_consensus(laps))
    assert elevation.cross_device_gap is not None
    assert elevation.cross_device_gap < 0.15


def test_window_sensitivity_reported():
    """The summary records the dimension at uniform 10/25/50 m
    windows; ascent falls as the window grows, and the uniform window
    matching the device window reproduces the dimension exactly."""
    pts = fixture_oval()
    n = len(pts)
    alt = tent(n, SPACING, 205.0, 200.0, 3.0) + wave(n, SPACING, 0.2, 45.0)
    elevation = analyze_elevation(build_consensus(oval_laps([alt])))
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
    laps = oval_laps([alt, np.roll(alt, 300)])
    a = analyze_elevation(build_consensus(laps))
    b = analyze_elevation(build_consensus(laps))
    assert a.summary() == b.summary()


def test_consensus_lap_device_default():
    """The Phase 6 device field is additive: existing constructions
    default to 'unknown' (and the default window applies)."""
    pts = fixture_oval()
    n = len(pts)
    lap = elev_lap(1, 1, pts, tent(n, SPACING, 205.0, 200.0, 3.0))
    assert lap.device == 'racechrono'
    plain = ConsensusLap(user_id=1, session_id=1, geometry=lap.geometry)
    assert plain.device == 'unknown'
    elevation = analyze_elevation(build_consensus([plain]))
    assert elevation.per_device['unknown']['window_m'] == 25.0


# ---- runner smoke tests (database) ----------------------------------------------

from datetime import date  # noqa: E402

from app import db  # noqa: E402
from app.models import Session, Telemetry  # noqa: E402
from app.track_dna.consensus import compute_config, run  # noqa: E402
from tests.app.test_track_dna_calibration import (  # noqa: E402
    capsule_points,
    make_track,
    make_user,
    m_to_latlon,
)
from tests.app.test_track_dna_consensus import make_config  # noqa: E402


def seed_elev_laps(track, config, user, laps=5, labels=None, day=1,
                   height_m=3.0, data_source='racechrono'):
    session = Session(user_id=user.id, track_id=track.id,
                      track_config_id=config.id if config else None,
                      labels=labels, data_source=data_source,
                      date=date(2026, 1, day))
    db.session.add(session)
    db.session.flush()
    pts = capsule_points(80.0, 40.0)          # 0.5 m spacing
    alt = tent(len(pts), 0.5, 205.0, 200.0, height_m)
    for lap_number in range(1, laps + 1):
        for i, (px, py) in enumerate(pts):
            lat, lon = m_to_latlon(px, py)
            db.session.add(Telemetry(
                session_id=session.id,
                lap_number=lap_number,
                elapsed_time=0.05 * i,
                distance_traveled=(len(pts) * 0.5 * (lap_number - 1)
                                   + 0.5 * i),
                latitude=lat, longitude=lon, altitude=float(alt[i]),
                speed_gps=15.0))
    db.session.flush()
    return session


def test_compute_config_elevation_section(app):
    owner = make_user()
    track = make_track(created_by=owner.id)
    config = make_config(track, owner)
    u1 = make_user(email='elev1@test.com')
    seed_elev_laps(track, config, u1, laps=5, day=1,
                   data_source='racechrono')
    seed_elev_laps(track, config, u1, laps=5, day=2, data_source='gopro')

    result = compute_config(config.id, 'dry')
    elevation = result['elevation']
    assert elevation['n_laps'] == 10
    assert elevation['n_laps_with_altitude'] == 10
    assert elevation['altitude_coverage'] == 1.0
    length_m = result['consensus']['dimensions']['track_length_m']['value']
    dims = elevation['dimensions']['elevation_gain']
    assert dims['unit'] == 'm/km'
    assert dims['value'] == pytest.approx(3.0 * 1000.0 / length_m, rel=0.15)
    assert dims['per_lap_median_m'] == pytest.approx(3.0, rel=0.15)
    assert dims['window_by_device'] == {'gopro': 50.0, 'racechrono': 25.0}
    per_device = elevation['evidence']['per_device']
    assert per_device['racechrono']['n_laps'] == 5
    assert per_device['gopro']['n_laps'] == 5
    assert elevation['evidence']['cross_device_gap'] < 0.15
    assert elevation['evidence']['balance']['median'] == pytest.approx(
        1.0, abs=0.05)
    assert elevation['evidence']['scatter']['flagged_laps'] == 0
    profile = elevation['profile']
    assert profile['step_m'] == pytest.approx(10.0)
    assert len(profile['points']) >= 30
    assert 2.0 < profile['relief_m'] < 3.3
    peak_s = max(profile['points'], key=lambda p: p[1])[0]
    assert peak_s == pytest.approx(205.0, abs=20.0)
    assert elevation['per_user']['elevation_gain'][u1.id]['n_laps'] == 10
    assert json.dumps(elevation)

    # wet is a separate bucket with its own elevation section (D1/D6)
    seed_elev_laps(track, config, u1, laps=2, labels=['Wet'], day=3,
                   height_m=2.0)
    wet = compute_config(config.id, 'wet')
    assert wet['elevation']['n_laps'] == 2
    assert wet['elevation']['dimensions']['elevation_gain'][
        'value'] == pytest.approx(2.0 * 1000.0 / length_m, rel=0.15)


def test_run_prints_elevation_section(app, capsys):
    owner = make_user()
    track = make_track(created_by=owner.id)
    config = make_config(track, owner)
    seed_elev_laps(track, config, owner, laps=2)

    result = run(config.id, 'dry')
    assert 'elevation' in result
    printed = capsys.readouterr().out
    assert 'elevation_gain' in printed
    parsed = json.loads(printed)
    assert parsed['elevation']['n_laps_with_altitude'] == 2
