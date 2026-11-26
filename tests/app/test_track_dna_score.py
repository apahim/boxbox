"""Tests for Track DNA normalisation and similarity (plan Phase 7,
spec Section 19). Pure module — no database."""

import pytest

from scripts.analysis.track_dna_score import (
    DIMENSIONS,
    LABEL_EDGES,
    TOTAL_WEIGHT,
    label_for,
    normalise_dimensions,
    overall_score,
    score_for,
    similarity,
)


def test_weights_sum_to_100():
    assert TOTAL_WEIGHT == 100
    assert sum(spec['weight'] for spec in DIMENSIONS.values()) == 100
    blocks = {
        'geometry': sum(DIMENSIONS[k]['weight'] for k in (
            'track_length_m', 'straight_pct', 'longest_straight_m',
            'corner_density_per_km', 'slow_corner_prop',
            'medium_corner_prop', 'fast_corner_prop', 'dc_per_km')),
        'braking': DIMENSIONS['heavy_braking_freq']['weight'],
        'elevation': DIMENSIONS['elevation_gain']['weight'],
    }
    assert blocks == {'geometry': 75, 'braking': 15, 'elevation': 10}


@pytest.mark.parametrize('key', sorted(DIMENSIONS))
def test_anchor_scores_and_labels_exact(key):
    """Value at every anchor maps to the exact ladder score and the
    anchor's own label band (anchor/threshold unit tests)."""
    spec = DIMENSIONS[key]
    for anchor, score in zip(spec['anchors'], (0.0, 2.5, 5.0, 7.5, 10.0)):
        assert score_for(key, anchor) == pytest.approx(score)
        assert label_for(key, score) == spec['labels'][
            min(4, sum(score >= edge for edge in LABEL_EDGES))]


def test_piecewise_linear_between_anchors():
    assert score_for('track_length_m', 950.0) == pytest.approx(
        2.5 + 150.0 / 300.0 * 2.5)          # 800 -> 1100 segment
    assert score_for('dc_per_km', 4.0) == pytest.approx(
        2.5 + 1.0 / 2.0 * 2.5)              # 3 -> 5 segment
    assert score_for('elevation_gain', 6.25) == pytest.approx(
        2.5 + 0.25 / 6.0 * 2.5)             # 6 -> 12 segment


def test_scores_clamped_outside_anchors():
    assert score_for('track_length_m', 100.0) == 0.0
    assert score_for('track_length_m', 5000.0) == 10.0
    assert score_for('straight_pct', 0.0) == 0.0
    assert score_for('straight_pct', 99.0) == 10.0


def test_label_boundaries():
    labels = DIMENSIONS['track_length_m']['labels']
    assert label_for('track_length_m', 0.0) == labels[0]
    assert label_for('track_length_m', 1.24) == labels[0]
    assert label_for('track_length_m', 1.25) == labels[1]
    assert label_for('track_length_m', 3.75) == labels[2]
    assert label_for('track_length_m', 6.25) == labels[3]
    assert label_for('track_length_m', 8.75) == labels[4]
    assert label_for('track_length_m', 10.0) == labels[4]


def test_kiltorcan_dry_calibration():
    """The 2026-11-26 prod cross-track measurement pins the ladder
    arithmetic (plan 19.4 example column, engine v1.0 values)."""
    raw = {
        'track_length_m': 992.0, 'straight_pct': 18.3,
        'longest_straight_m': 70.0, 'corner_density_per_km': 9.07,
        'slow_corner_prop': 66.7, 'medium_corner_prop': 33.3,
        'fast_corner_prop': 0.0, 'dc_per_km': 4.06,
        'heavy_braking_freq': 0.0, 'elevation_gain': 6.25,
    }
    dims = normalise_dimensions(raw)
    scores = {d['key']: d['score'] for d in dims}
    assert scores['track_length_m'] == pytest.approx(4.1, abs=0.05)
    assert scores['straight_pct'] == pytest.approx(4.58, abs=0.05)
    assert scores['longest_straight_m'] == pytest.approx(3.13, abs=0.05)
    assert scores['corner_density_per_km'] == pytest.approx(4.23, abs=0.05)
    assert scores['slow_corner_prop'] == pytest.approx(8.34, abs=0.05)
    assert scores['medium_corner_prop'] == pytest.approx(4.16, abs=0.05)
    assert scores['fast_corner_prop'] == 0.0
    assert scores['dc_per_km'] == pytest.approx(3.83, abs=0.05)
    assert scores['heavy_braking_freq'] == 0.0
    assert scores['elevation_gain'] == pytest.approx(2.6, abs=0.05)
    labels = {d['key']: d['class'] for d in dims}
    assert labels['track_length_m'] == 'Medium'
    assert labels['straight_pct'] == 'Balanced'
    assert labels['slow_corner_prop'] == 'High'
    assert labels['elevation_gain'] == 'Gentle'
    assert overall_score(dims) == pytest.approx(3.31, abs=0.03)


def test_normalise_missing_dimension():
    dims = normalise_dimensions({'track_length_m': 992.0})
    by_key = {d['key']: d for d in dims}
    assert len(dims) == 10
    assert by_key['track_length_m']['score'] == pytest.approx(4.1, abs=0.05)
    assert by_key['heavy_braking_freq']['score'] is None
    assert by_key['heavy_braking_freq']['class'] is None
    assert by_key['heavy_braking_freq']['value'] is None
    # missing never counts as zero: overall excludes it
    assert overall_score(dims) == pytest.approx(4.1)
    assert overall_score(normalise_dimensions({})) is None


def test_similarity_identical_cards_100():
    dims = normalise_dimensions({
        'track_length_m': 992.0, 'straight_pct': 18.3,
        'longest_straight_m': 70.0, 'corner_density_per_km': 9.07,
        'slow_corner_prop': 66.7, 'medium_corner_prop': 33.3,
        'fast_corner_prop': 0.0, 'dc_per_km': 4.06,
        'heavy_braking_freq': 0.0, 'elevation_gain': 6.25})
    sim = similarity(dims, dims)
    assert sim['similarity_pct'] == 100.0
    assert sim['coverage'] == 1.0
    assert all(v == 0.0 for v in sim['contributions'].values())


def test_similarity_symmetric_and_bounded():
    a = normalise_dimensions({'track_length_m': 992.0, 'dc_per_km': 4.06})
    b = normalise_dimensions({'track_length_m': 1500.0, 'dc_per_km': 12.0})
    ab = similarity(a, b)
    ba = similarity(b, a)
    assert ab['similarity_pct'] == ba['similarity_pct']
    assert ab['coverage'] == ba['coverage']
    assert 0.0 <= ab['similarity_pct'] <= 100.0
    # contributions sum to the distance (coverage-weighted)
    distance = 100.0 - ab['similarity_pct']
    assert sum(ab['contributions'].values()) == pytest.approx(
        distance, abs=0.05)


def test_similarity_opposite_ends_zero():
    low = normalise_dimensions({'track_length_m': 400.0})
    high = normalise_dimensions({'track_length_m': 3000.0})
    assert similarity(low, high)['similarity_pct'] == 0.0


def test_similarity_coverage_missing_dimension():
    full = normalise_dimensions({'track_length_m': 992.0,
                                 'heavy_braking_freq': 0.0})
    partial = normalise_dimensions({'track_length_m': 992.0})
    sim = similarity(full, partial)
    # only length is shared: coverage 10/100
    assert sim['coverage'] == pytest.approx(0.1)
    assert set(sim['contributions']) == {'track_length_m'}
    assert sim['similarity_pct'] == 100.0   # on the shared space
    # a dimension missing on one side never contributes distance
    assert 'heavy_braking_freq' not in sim['contributions']
