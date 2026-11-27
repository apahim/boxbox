"""Synthetic tests for the Track DNA reference-lap circuit builder.

The single-lap successor of the consensus layer: one valid lap's
engine output becomes the circuit geometry object the braking and
elevation layers consume.
"""

import numpy as np
import pytest

from scripts.analysis.track_dna import DEFAULT_PARAMS, analyze_lap
from scripts.analysis.track_dna_reference import (
    ConsensusLap,
    reference_consensus,
)
from tests.app.test_track_dna import fixture_oval, make_lap_input


def reference_from(points, **kwargs):
    return reference_consensus(
        ConsensusLap(user_id=7, session_id=42, lap_number=3,
                     geometry=analyze_lap(make_lap_input(points)),
                     **kwargs),
        DEFAULT_PARAMS)


def test_circuit_identity_is_the_lap():
    """The circuit IS the reference lap: dimensions 1-8 read the lap's
    own LapGeometry; the trajectory is its resampled positions."""
    pts = fixture_oval()
    geo = analyze_lap(make_lap_input(pts))
    circuit = reference_from(pts)

    assert circuit.laps[0].geometry.length_m == geo.length_m
    assert circuit.length_m == pytest.approx(geo.length_m)
    assert circuit.straight_pct == pytest.approx(
        100.0 * geo.straight_fraction)
    assert circuit.longest_straight_m == pytest.approx(
        geo.longest_straight_m)
    assert circuit.corner_count == len(geo.corners)
    assert circuit.corner_density_per_km == pytest.approx(
        geo.corner_density_per_km)
    assert circuit.dc_per_km == pytest.approx(geo.dc_per_km)
    assert circuit.condition is None
    assert np.array_equal(circuit.shifts_m, [0.0])
    assert np.array_equal(circuit.align_r, [1.0])
    assert circuit.seed == {'session_id': 42, 'lap_number': 3}
    assert np.allclose(circuit.x, geo.x)
    assert np.allclose(circuit.y, geo.y)
    assert np.allclose(circuit.grid, geo.s)
    assert circuit.arclength_m == pytest.approx(geo.length_m, rel=0.01)


def test_circuit_corner_set_is_the_lap_corners():
    pts = fixture_oval()
    geo = analyze_lap(make_lap_input(pts))
    circuit = reference_from(pts)

    assert len(circuit.corners) == len(geo.corners)
    by_apex = sorted(geo.corners, key=lambda c: c.s_apex)
    for cc, lc in zip(circuit.corners, by_apex):
        assert cc.s_apex == pytest.approx(lc.s_apex)
        assert cc.s_start == pytest.approx(lc.s_start)
        assert cc.s_end == pytest.approx(lc.s_end)
        assert cc.delta_theta_deg == pytest.approx(lc.delta_theta_deg)
        assert cc.sign == lc.sign
        assert cc.radius_m == pytest.approx(lc.radius_m, rel=0.01)
        assert cc.n_laps == 1
        assert cc.recurrence == 1.0
        assert cc.member_corners == 1
        assert cc.support_by_user == {7: 1.0}
        assert cc.radius_class in ('slow', 'medium', 'fast')
    # corner proportions sum to 100% exactly
    total = sum(circuit.corner_props.values())
    assert total == pytest.approx(100.0 if circuit.corner_count else 0.0)


def test_radius_classes_match_thresholds():
    from scripts.analysis.track_dna_reference import (
        MEDIUM_CORNER_MAX_M,
        SLOW_CORNER_MAX_M,
        _radius_class,
    )
    assert _radius_class(10.0) == 'slow'
    assert _radius_class(SLOW_CORNER_MAX_M) == 'medium'
    assert _radius_class(MEDIUM_CORNER_MAX_M) == 'fast'
    assert _radius_class(999.0) == 'fast'


def test_summary_shape():
    """summary() feeds the card builder: dims 1-8, corners list and
    trajectory evidence, all JSON-serialisable."""
    import json

    pts = fixture_oval()
    circuit = reference_from(pts)
    summary = circuit.summary()

    assert summary['condition'] is None
    assert summary['n_users'] == 1
    assert summary['n_sessions'] == 1
    assert summary['n_laps'] == 1
    assert summary['n_spun_excluded'] == 0
    dims = summary['dimensions']
    assert set(dims) == {'track_length_m', 'straight_pct',
                         'longest_straight_m', 'corner_count',
                         'corner_density_per_km', 'slow_corner_prop',
                         'medium_corner_prop', 'fast_corner_prop',
                         'dc_per_km', 'dc_count'}
    assert dims['track_length_m']['value'] == pytest.approx(
        circuit.length_m, abs=0.01)
    assert len(summary['corners']) == circuit.corner_count
    assert summary['consensus_trajectory']['length_m'] == pytest.approx(
        circuit.length_m, abs=0.01)
    json.dumps(summary)


def test_spun_lap_rejected():
    """A spun reference lap has no circuit geometry — the builder
    raises, the caller turns it into a validation error."""
    pts = fixture_oval()
    geo = analyze_lap(make_lap_input(pts))
    geo.spun = True
    record = ConsensusLap(user_id=1, session_id=1, geometry=geo)
    with pytest.raises(ValueError):
        reference_consensus(record, DEFAULT_PARAMS)
