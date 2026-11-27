"""Tests for the Track DNA braking layer (plan Phase 5, spec Section 17).

Synthetic tests for event detection (doubled-array seam handling,
thresholds, prominence), zones and dimension 9 on reference-lap
(single-lap) circuits.
"""

import json
import math

import numpy as np
import pytest

from scripts.analysis.track_dna import DEFAULT_PARAMS, LapInput, analyze_lap
from scripts.analysis.track_dna_braking import (
    DEFAULT_BRAKING_PARAMS,
    analyze_braking,
    detect_lap_events,
)
from scripts.analysis.track_dna_reference import ConsensusLap, \
    reference_consensus
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


def reference_circuit(record):
    """The single-lap circuit object (what build_card feeds the layer)."""
    return reference_consensus(record, DEFAULT_PARAMS)


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


# ---- zones and dimension 9 on the reference circuit ------------------------------


def test_reference_lap_zones():
    """On a single-lap circuit every >= 30% event is a zone with
    recurrence 1.0 (the 20% recurrence gate is trivially met)."""
    pts = fixture_oval()
    n = len(pts)
    record = braking_lap(1, 1, pts, speed_profile(
        n, [(200.0, 20.0), (330.0, 20.0)]))
    braking = analyze_braking(reference_circuit(record))
    assert len(braking.zones) == 2
    zones = sorted(braking.zones, key=lambda z: z.s_trough)
    assert zones[0].s_trough == pytest.approx(200.0, abs=5.0)
    assert zones[1].s_trough == pytest.approx(330.0, abs=5.0)
    assert zones[0].n_laps == 1
    assert zones[0].recurrence == pytest.approx(1.0)
    assert zones[0].support_by_user == {1: pytest.approx(1.0)}
    assert braking.minor_zones == []


def test_zone_reduction_threshold_30_percent():
    """Events below 30% reduction exist but never qualify for zones
    (the PoC zone recipe — Section 17.1)."""
    pts = fixture_oval()
    n = len(pts)
    record = braking_lap(1, 1, pts, speed_profile(
        n, [(200.0, 20.0)], slow=14.2))
    braking = analyze_braking(reference_circuit(record))
    assert all(len(events) == 1 for events in braking.events_by_lap)
    assert braking.zones == []
    # exactly 30% qualifies
    record = braking_lap(1, 1, pts, speed_profile(
        n, [(200.0, 20.0)], slow=14.0))
    braking = analyze_braking(reference_circuit(record))
    assert len(braking.zones) == 1
    assert braking.zones[0].reduction_median == pytest.approx(0.30,
                                                              abs=0.005)


def test_dimension_9_and_sensitivity():
    pts = fixture_oval()
    n = len(pts)
    record = braking_lap(1, 1, pts, speed_profile(n, [(200.0, 20.0)]))
    circuit = reference_circuit(record)
    braking = analyze_braking(circuit)
    per_km = 1000.0 / circuit.length_m
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
    assert summary['per_user']['heavy_braking_freq'][1]['n_laps'] == 1
    assert json.dumps(summary)


def test_missing_speed_lap_is_coverage():
    """A reference lap without a speed channel yields no dimension 9
    (missing is coverage, never zero)."""
    pts = fixture_oval()
    record = no_speed_lap(1, 1, pts)
    braking = analyze_braking(reference_circuit(record))
    assert braking.n_laps == 1
    assert braking.n_laps_with_speed == 0
    assert braking.heavy_freq_per_km is None
    summary = braking.summary()
    assert summary['speed_coverage'] == 0.0
    assert summary['dimensions']['heavy_braking_freq']['value'] is None


def test_braking_reproducible():
    pts = fixture_oval()
    n = len(pts)
    record = braking_lap(1, 1, pts, speed_profile(n, [(200.0, 20.0),
                                                      (330.0, 20.0)]))
    a = analyze_braking(reference_circuit(record))
    b = analyze_braking(reference_circuit(record))
    assert a.summary() == b.summary()
