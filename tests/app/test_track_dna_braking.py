"""Tests for the Track DNA braking layer (plan Phase 5, spec Section 17).

Synthetic tests for event detection (doubled-array seam handling,
thresholds, prominence), zones and dimension 9, plus smoke tests for
the read-only runner's braking section.
"""

import json
import math

import numpy as np
import pytest

from scripts.analysis.track_dna import LapInput, analyze_lap
from scripts.analysis.track_dna_braking import (
    DEFAULT_BRAKING_PARAMS,
    analyze_braking,
    detect_lap_events,
)
from scripts.analysis.track_dna_consensus import ConsensusLap, build_consensus
from tests.app.test_track_dna import (
    fixture_oval,
    make_lap_input,
    roll_lap,
)

SPACING = 0.25


# ---- synthetic helpers ---------------------------------------------------------


def speed_input(points, speeds, dt=0.04):
    x = np.asarray([p[0] for p in points], dtype=float)
    y = np.asarray([p[1] for p in points], dtype=float)
    n = len(points)
    return LapInput(x=x, y=y, altitude=None,
                    speed=np.asarray(speeds, dtype=float),
                    elapsed=np.arange(n) * dt)


def speed_profile(n_points, windows, cruise=20.0, slow=12.0,
                  ramp_m=25.0, spacing=SPACING):
    """Cruise speed with circular trapezoid decel windows.

    ``windows``: ``(center_m, hold_m)`` pairs — path-arclength window
    centre and full-depth hold width, with ``ramp_m`` ramps on each
    side. Index space is circular, so a window may straddle index 0
    (the s=0 seam). Plateaus stay exactly ``cruise``/``slow`` so
    reduction values are exact for boundary tests.
    """
    v = np.full(n_points, cruise)
    idx = np.arange(n_points)
    r = max(3, int(round(ramp_m / spacing)))
    for center_m, hold_m in windows:
        c = int(round(center_m / spacing)) % n_points
        h = max(1, int(round(hold_m / spacing / 2)))
        d = np.abs(((idx - c + n_points // 2) % n_points) - n_points // 2)
        w = h + r
        depth = np.where(d <= h, 1.0, np.clip((w - d) / r, 0.0, 1.0))
        v = np.minimum(v, cruise - (cruise - slow) * depth)
    return v


def braking_lap(user_id, session_id, points, speeds, lap_number=1):
    return ConsensusLap(user_id=user_id, session_id=session_id,
                        lap_number=lap_number,
                        geometry=analyze_lap(speed_input(points, speeds)))


def no_speed_lap(user_id, session_id, points, lap_number=1):
    x = np.asarray([p[0] for p in points], dtype=float)
    y = np.asarray([p[1] for p in points], dtype=float)
    return ConsensusLap(user_id=user_id, session_id=session_id,
                        lap_number=lap_number,
                        geometry=analyze_lap(LapInput(x=x, y=y)))


# ---- event detection -----------------------------------------------------------


def test_detect_single_decel_not_split():
    """One decel window yields exactly one event with the exact
    reduction (peak spacing must not split it)."""
    pts = fixture_oval()
    v = speed_profile(len(pts), [(200.0, 20.0)])
    geo = analyze_lap(speed_input(pts, v))
    events = detect_lap_events(geo)
    assert events is not None
    assert len(events) == 1
    event = events[0]
    assert event.reduction == pytest.approx(0.40, abs=0.005)
    assert event.v_peak == pytest.approx(20.0, abs=0.1)
    assert event.v_trough == pytest.approx(12.0, abs=0.1)
    assert event.s_trough == pytest.approx(200.0, abs=4.0)
    assert 0.0 <= event.s_peak < geo.length_m


def test_detect_two_decels_both_counted():
    pts = fixture_oval()
    v = speed_profile(len(pts), [(120.0, 20.0), (330.0, 20.0)])
    geo = analyze_lap(speed_input(pts, v))
    events = detect_lap_events(geo)
    assert len(events) == 2
    troughs = sorted(e.s_trough for e in events)
    assert troughs[0] == pytest.approx(120.0, abs=4.0)
    assert troughs[1] == pytest.approx(330.0, abs=4.0)
    assert all(e.reduction == pytest.approx(0.40, abs=0.005)
               for e in events)


def test_reduction_boundary_at_heavy_threshold():
    """The heavy flag flips exactly at 40% reduction (D5)."""
    pts = fixture_oval()
    for slow, expect_heavy in ((12.02, False), (12.0, True),
                               (11.98, True)):
        v = speed_profile(len(pts), [(200.0, 20.0)], slow=slow)
        events = detect_lap_events(analyze_lap(speed_input(pts, v)))
        assert len(events) == 1
        assert (events[0].reduction >= 0.40) is expect_heavy


def test_small_wobble_not_an_event():
    """Sub-prominence speed wobble creates no events."""
    pts = fixture_oval()
    n = len(pts)
    v = (np.full(n, 20.0)
         + 0.05 * np.sin(np.arange(n) * 2 * math.pi * 37 / n))
    events = detect_lap_events(analyze_lap(speed_input(pts, v)))
    assert events == []


def test_constant_speed_no_events():
    pts = fixture_oval()
    events = detect_lap_events(analyze_lap(make_lap_input(pts)))
    assert events == []


def test_missing_speed_is_coverage_not_zero():
    pts = fixture_oval()
    events = detect_lap_events(no_speed_lap(1, 1, pts).geometry)
    assert events is None


def test_event_straddling_seam_counted():
    """Roadmap acceptance: an event whose decel ramp starts before s=0
    and bottoms out after it is counted — the trough is found in the
    second copy of the doubled array and mapped back by modulo."""
    pts = fixture_oval()
    v = speed_profile(len(pts), [(10.0, 20.0)])   # window spans -25..45 m
    geo = analyze_lap(speed_input(pts, v))
    events = detect_lap_events(geo)
    assert len(events) == 1
    assert events[0].reduction == pytest.approx(0.40, abs=0.005)
    assert events[0].s_trough == pytest.approx(10.0, abs=4.0)


def test_rolled_lap_same_events():
    """Rolling the lap (moving the s=0 seam) must not change the
    physical event set."""
    pts = fixture_oval()
    v = speed_profile(len(pts), [(200.0, 20.0)])
    base = analyze_lap(speed_input(pts, v))
    k = int(150 / SPACING)
    rolled = analyze_lap(speed_input(roll_lap(pts, k), np.roll(v, -k)))
    eb = detect_lap_events(base)
    er = detect_lap_events(rolled)
    assert len(eb) == len(er) == 1
    assert er[0].reduction == pytest.approx(eb[0].reduction, abs=0.01)
    assert eb[0].s_trough == pytest.approx(200.0, abs=4.0)
    assert er[0].s_trough == pytest.approx(50.0, abs=4.0)


def test_peak_at_seam_kept():
    """A cruise peak at physical s=0 is detectable only at index n of
    the doubled array and must be kept (its event braked into the
    s=100 window)."""
    pts = fixture_oval()
    geo_ref = analyze_lap(speed_input(pts, np.full(len(pts), 20.0)))
    length = geo_ref.length_m
    v = speed_profile(len(pts), [(100.0, 20.0), (length - 100.0, 20.0)])
    events = detect_lap_events(analyze_lap(speed_input(pts, v)))
    assert len(events) == 2
    troughs = sorted(e.s_trough for e in events)
    assert troughs[0] == pytest.approx(100.0, abs=4.0)
    assert troughs[1] == pytest.approx(length - 100.0, abs=4.0)


# ---- zones and dimension 9 -----------------------------------------------------


def test_zone_recurrence_threshold():
    """Zones need >= 20% of laps: 10/10 and 2/10 (exactly 20%) qualify,
    1/10 does not."""
    pts = fixture_oval()
    n = len(pts)
    laps = []
    for i in range(1, 11):
        windows = [(200.0, 20.0)]
        if i <= 2:
            windows.append((330.0, 20.0))
        if i == 3:
            windows.append((80.0, 20.0))
        laps.append(braking_lap(1, 1, pts, speed_profile(n, windows), i))
    braking = analyze_braking(build_consensus(laps))
    assert len(braking.zones) == 2
    zones = sorted(braking.zones, key=lambda z: z.s_trough)
    assert zones[0].s_trough == pytest.approx(200.0, abs=5.0)
    assert zones[1].s_trough == pytest.approx(330.0, abs=5.0)
    assert zones[0].n_laps == 10
    assert zones[0].recurrence == pytest.approx(1.0)
    assert zones[1].n_laps == 2
    assert zones[1].recurrence == pytest.approx(0.2)
    assert zones[1].support_by_user == {1: pytest.approx(0.2)}


def test_zone_reduction_threshold_30_percent():
    """Events below 30% reduction exist but never qualify for zones
    (the PoC zone recipe — Section 17.1)."""
    pts = fixture_oval()
    n = len(pts)
    laps = [braking_lap(1, 1, pts, speed_profile(n, [(200.0, 20.0)],
                                                 slow=14.2), i)
            for i in (1, 2)]
    braking = analyze_braking(build_consensus(laps))
    assert all(len(events) == 1 for events in braking.events_by_lap)
    assert braking.zones == []
    # exactly 30% qualifies
    laps = [braking_lap(1, 1, pts, speed_profile(n, [(200.0, 20.0)],
                                                 slow=14.0), i)
            for i in (1, 2)]
    braking = analyze_braking(build_consensus(laps))
    assert len(braking.zones) == 1
    assert braking.zones[0].reduction_median == pytest.approx(0.30,
                                                              abs=0.005)


def test_dimension_9_and_sensitivity():
    pts = fixture_oval()
    n = len(pts)
    laps = [braking_lap(1, 1, pts, speed_profile(n, [(200.0, 20.0)]), i)
            for i in range(1, 5)]
    consensus = build_consensus(laps)
    braking = analyze_braking(consensus)
    per_km = 1000.0 / consensus.length_m
    assert braking.heavy_freq_per_km == pytest.approx(per_km, rel=0.01)
    assert braking.sensitivity[0.35] == pytest.approx(per_km, rel=0.01)
    assert braking.sensitivity[0.45] == 0.0

    summary = braking.summary()
    dims = summary['dimensions']['heavy_braking_freq']
    assert dims['value'] == pytest.approx(per_km, rel=0.01)
    assert dims['unit'] == 'events/km'
    assert dims['sensitivity']['0.35'] == pytest.approx(per_km, rel=0.01)
    assert dims['sensitivity']['0.45'] == 0.0
    assert summary['speed_coverage'] == 1.0
    assert summary['kart_category'] == 'mixed/unspecified'
    assert len(summary['zones']) == 1
    assert summary['zones'][0]['reduction_pct'] == pytest.approx(40.0,
                                                                 abs=1.0)
    assert summary['per_user']['heavy_braking_freq'][1]['n_laps'] == 4
    assert json.dumps(summary)


def test_missing_speed_laps_are_coverage():
    """Laps without a speed channel never dilute dimension 9 (missing
    is coverage, not zero)."""
    pts = fixture_oval()
    n = len(pts)
    with_speed = [braking_lap(1, 1, pts, speed_profile(n, [(200.0, 20.0)]),
                              i) for i in (1, 2)]
    without = [no_speed_lap(1, 1, pts, i) for i in (3, 4)]
    consensus = build_consensus(with_speed + without)
    braking = analyze_braking(consensus)
    assert braking.n_laps == 4
    assert braking.n_laps_with_speed == 2
    assert braking.heavy_freq_per_km == pytest.approx(
        1000.0 / consensus.length_m, rel=0.01)
    summary = braking.summary()
    assert summary['speed_coverage'] == 0.5
    # the flat-with-zeros median would read half of this
    assert summary['dimensions']['heavy_braking_freq']['value'] == (
        pytest.approx(1000.0 / consensus.length_m, rel=0.01))


def test_braking_reproducible():
    pts = fixture_oval()
    n = len(pts)
    laps = [braking_lap(1, 1, pts, speed_profile(n, [(200.0, 20.0),
                                                     (330.0, 20.0)]), i)
            for i in (1, 2)]
    a = analyze_braking(build_consensus(laps))
    b = analyze_braking(build_consensus(laps))
    assert a.summary() == b.summary()


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


def seed_braking_laps(track, config, user, laps=2, labels=None, day=1,
                      windows=((100.0, 20.0),), cruise=20.0, slow=12.0):
    session = Session(user_id=user.id, track_id=track.id,
                      track_config_id=config.id if config else None,
                      labels=labels, data_source='racechrono',
                      date=date(2026, 1, day))
    db.session.add(session)
    db.session.flush()
    pts = capsule_points(80.0, 40.0)          # 0.5 m spacing
    speeds = speed_profile(len(pts), list(windows), cruise=cruise,
                           slow=slow, spacing=0.5)
    for lap_number in range(1, laps + 1):
        for i, (px, py) in enumerate(pts):
            lat, lon = m_to_latlon(px, py)
            db.session.add(Telemetry(
                session_id=session.id,
                lap_number=lap_number,
                elapsed_time=0.05 * i,
                distance_traveled=(len(pts) * 0.5 * (lap_number - 1)
                                   + 0.5 * i),
                latitude=lat, longitude=lon, altitude=10.0,
                speed_gps=float(speeds[i])))
    db.session.flush()
    return session


def test_compute_config_braking_section(app):
    owner = make_user()
    track = make_track(created_by=owner.id)
    config = make_config(track, owner)
    u1 = make_user(email='brake1@test.com')
    seed_braking_laps(track, config, u1, laps=2, day=1)
    seed_braking_laps(track, config, u1, laps=2, day=2)

    result = compute_config(config.id, 'dry')
    braking = result['braking']
    assert braking['n_laps'] == 4
    assert braking['n_laps_with_speed'] == 4
    length_m = result['consensus']['dimensions']['track_length_m']['value']
    dims = braking['dimensions']['heavy_braking_freq']
    assert dims['value'] == pytest.approx(1000.0 / length_m, rel=0.02)
    assert dims['sensitivity']['0.35'] == pytest.approx(1000.0 / length_m,
                                                        rel=0.02)
    assert dims['sensitivity']['0.45'] == 0.0
    assert len(braking['zones']) == 1
    zone = braking['zones'][0]
    assert zone['recurrence'] == 1.0
    assert zone['reduction_pct'] == pytest.approx(40.0, abs=1.0)
    assert zone['support_by_user'] == {u1.id: 1.0}
    assert braking['evidence']['events_per_lap_median'] == 1.0

    # wet is a separate bucket with its own braking section (D1/D6)
    seed_braking_laps(track, config, u1, laps=2, labels=['Wet'], day=3,
                      windows=((100.0, 20.0), (300.0, 20.0)))
    wet = compute_config(config.id, 'wet')
    assert wet['braking']['n_laps'] == 2
    assert len(wet['braking']['zones']) == 2
    assert wet['braking']['dimensions']['heavy_braking_freq'][
        'value'] == pytest.approx(2 * 1000.0 / length_m, rel=0.02)


def test_run_prints_braking_section(app, capsys):
    owner = make_user()
    track = make_track(created_by=owner.id)
    config = make_config(track, owner)
    seed_braking_laps(track, config, owner, laps=2)

    result = run(config.id, 'dry')
    assert 'braking' in result
    printed = capsys.readouterr().out
    assert 'heavy_braking_freq' in printed
    parsed = json.loads(printed)
    assert len(parsed['braking']['zones']) == 1
