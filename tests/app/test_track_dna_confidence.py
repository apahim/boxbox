"""Tests for Track DNA confidence and quality classes (plan Phase 8,
spec Section 20).

Pure rule tests over synthetic layer summaries (no database), plus
builder/CLI integration tests. The rules reuse plan anchors only —
no invented coefficients (roadmap acceptance).
"""

import pytest

from scripts.analysis.track_dna_confidence import (
    ELEVATION_GAP_MAX,
    MIN_LAPS,
    MIN_USERS,
    PROVENANCE,
    assign_confidence,
)
from scripts.analysis.track_dna_score import DIMENSIONS as SCORE_DIMS

QUALITIES = ('Measured', 'Estimated', 'Unavailable')


# ---- synthetic summary builders -------------------------------------------------


def demonstrated(n=50, length_ok=True, corners_ok=True, straight_ok=True):
    return {'demonstrated_n': n,
            'length_spread_m': 5.0, 'length_ok': length_ok,
            'corner_spread': 0.0, 'corners_ok': corners_ok,
            'straight_pct_spread': 1.0, 'straight_ok': straight_ok,
            'hierarchical_evidence': {}}


def consensus_summary(n_users=3, n_laps=323, acceptance=None,
                      per_user=None):
    return {'n_users': n_users, 'n_sessions': 17, 'n_laps': n_laps,
            'convergence': {'draws': [], 'acceptance': acceptance},
            'per_user': per_user or {}}


def braking_summary(value=0.5, n_speed=323, coverage=1.0, per_user=None):
    return {'n_laps_with_speed': n_speed, 'speed_coverage': coverage,
            'dimensions': {'heavy_braking_freq': {'value': value}},
            'per_user': {'heavy_braking_freq': per_user}
            if per_user else {}}


def elevation_summary(value=6.2, n_alt=323, per_user=None, flagged=0):
    return {'n_laps_with_altitude': n_alt,
            'dimensions': {'elevation_gain': {'value': value}},
            'evidence': {'scatter': {'flagged_laps': flagged}},
            'per_user': {'elevation_gain': per_user} if per_user else {}}


def users(*medians):
    """Per-user spread section: {user_id: {n_laps, median, p10, p90}}."""
    return {i + 1: {'n_laps': 10, 'median': m, 'p10': m, 'p90': m}
            for i, m in enumerate(medians)}


def run(consensus=None, braking=None, elevation=None, dataset=None):
    return assign_confidence(consensus or consensus_summary(
        acceptance=demonstrated()),
        braking or braking_summary(per_user=users(0.0, 1.0)),
        elevation or elevation_summary(per_user=users(6.0, 7.0)),
        dataset or {'devices': ['gopro', 'racechrono']})


# ---- pure rule tests ------------------------------------------------------------


def test_measured_happy_path():
    dims, card = run()
    assert set(dims) == set(SCORE_DIMS)
    assert all(d['quality'] == 'Measured' for d in dims.values())
    assert all(d['warnings'] == [] for d in dims.values())
    for key, conf in dims.items():
        assert conf['provenance'] == PROVENANCE[key]
        assert conf['counts']['n_users'] >= MIN_USERS
        assert conf['counts']['n_laps'] >= MIN_LAPS
        assert conf['quality'] in QUALITIES
    assert card['convergence']['demonstrated'] is True
    assert card['convergence']['demonstrated_n'] == 50


def test_single_user_circuit_all_estimated():
    """Roadmap acceptance: single-user circuits are flagged Estimated —
    every present dimension lacks cross-user corroboration."""
    dims, _ = run(consensus_summary(n_users=1, n_laps=50,
                                    acceptance=demonstrated()),
                  braking_summary(per_user=users(0.5)),
                  elevation_summary(per_user=users(6.0)))
    assert all(d['quality'] == 'Estimated' for d in dims.values())
    for conf in dims.values():
        assert any(w.startswith('single_user') for w in conf['warnings'])


def test_thin_data():
    dims, _ = run(consensus_summary(n_users=2, n_laps=12,
                                    acceptance=demonstrated()),
                  braking_summary(n_speed=12, per_user=users(0.0, 1.0)))
    geo = dims['track_length_m']
    assert geo['quality'] == 'Estimated'
    assert 'thin_data: 12 laps (<20)' in geo['warnings']
    assert dims['heavy_braking_freq']['quality'] == 'Estimated'
    assert 'thin_data: 12 laps (<20)' in dims['heavy_braking_freq'][
        'warnings']
    # elevation's rule is users + cross-user gap (no lap minimum)
    assert dims['elevation_gain']['quality'] == 'Measured'


def test_convergence_not_demonstrated():
    dims, card = run(consensus_summary(acceptance=demonstrated(n=20)))
    assert card['convergence']['demonstrated'] is False
    assert card['convergence']['demonstrated_n'] == 20
    conf = dims['dc_per_km']
    assert conf['quality'] == 'Estimated'
    assert 'convergence_not_demonstrated: demonstrated at 20, not 50' \
        in conf['warnings']


def test_no_convergence_evidence():
    """The Phase 8 honesty fix: a 1-lap dataset has no subsampling
    draws at all — acceptance is None, never a vacuous pass."""
    dims, card = run(consensus_summary(acceptance=None))
    assert card['convergence']['demonstrated'] is False
    assert card['convergence']['demonstrated_n'] is None
    assert 'convergence_not_demonstrated: no subsampling evidence' \
        in dims['track_length_m']['warnings']


def test_convergence_anchors_failed():
    dims, _ = run(consensus_summary(
        acceptance=demonstrated(corners_ok=False)))
    assert 'convergence_anchors_failed: spreads exceed the 15.6 ' \
        'anchors at k=50' in dims['track_length_m']['warnings']


def test_braking_unavailable():
    """Missing speed is Unavailable, never zero (D5/D8)."""
    dims, _ = run(braking=braking_summary(value=None, n_speed=0,
                                          coverage=None))
    conf = dims['heavy_braking_freq']
    assert conf['quality'] == 'Unavailable'
    assert conf['warnings'] == ['no_speed_channel']
    assert conf['counts'] == {'n_users': 0, 'n_laps': 0}


def test_braking_low_coverage_is_warning_only():
    """Partial speed coverage is evidence, not a class trigger."""
    dims, _ = run(braking=braking_summary(n_speed=25, coverage=0.8,
                                          per_user=users(0.0, 1.0)))
    conf = dims['heavy_braking_freq']
    assert conf['quality'] == 'Measured'
    assert 'low_speed_coverage: 0.8' in conf['warnings']


def test_elevation_cross_user_gap_estimated():
    """The u16 case finally acted on (plan 18.8/20.1): Kiltorcan dry
    user medians disagree by 80% -> Estimated."""
    dims, card = run(elevation=elevation_summary(
        per_user=users(5.776, 10.4, 6.163)))
    conf = dims['elevation_gain']
    assert conf['quality'] == 'Estimated'
    assert 'cross_user_gap: 0.80 > 0.20' in conf['warnings']
    assert card['cross_user_gaps']['elevation_gain'] == pytest.approx(
        0.80, abs=0.005)


def test_elevation_measured_with_high_scatter():
    """The Whiteriver pin (plan 20.1): 50/50 scatter-flagged laps but
    users agree within 16% — real relief inflates the detrended std,
    so the scatter fraction is evidence, never a class trigger."""
    dims, card = run(elevation=elevation_summary(
        n_alt=50, flagged=50, per_user=users(19.281, 22.364)))
    conf = dims['elevation_gain']
    assert conf['quality'] == 'Measured'
    assert conf['warnings'] == []
    assert card['elevation_scatter_flagged_fraction'] == 1.0
    assert card['cross_user_gaps']['elevation_gain'] == pytest.approx(
        0.16, abs=0.005)


def test_elevation_unavailable():
    dims, _ = run(elevation=elevation_summary(value=None, n_alt=0))
    conf = dims['elevation_gain']
    assert conf['quality'] == 'Unavailable'
    assert conf['warnings'] == ['no_altitude_channel']


def test_elevation_zero_median_user():
    dims, _ = run(elevation=elevation_summary(per_user=users(0.0, 5.0)))
    conf = dims['elevation_gain']
    assert conf['quality'] == 'Estimated'
    assert 'cross_user_gap: undefined (zero-median user)' \
        in conf['warnings']


def test_geometry_user_spread_reported_never_gated():
    """Driving-line variance is evidence, not a class trigger: 22%
    straight% disagreement between users does not demote geometry."""
    per_user = {'straight_pct': users(18.16, 18.2, 14.9)}
    dims, card = run(consensus_summary(acceptance=demonstrated(),
                                       per_user=per_user))
    assert dims['straight_pct']['quality'] == 'Measured'
    assert card['per_user_medians']['straight_pct'] == \
        {1: 18.16, 2: 18.2, 3: 14.9}
    assert card['cross_user_gaps']['straight_pct'] == pytest.approx(
        0.221, abs=0.005)


def test_card_block_fields():
    _, card = run(dataset={'devices': ['gopro']})
    assert card['single_device'] is True
    assert card['n_users'] == 3
    assert card['n_sessions'] == 17
    assert card['n_laps'] == 323
    assert card['convergence']['demonstrated'] is True
    assert set(card['per_user_medians']) >= {
        'heavy_braking_freq', 'elevation_gain'}


def test_provenance_covers_every_dimension():
    assert set(PROVENANCE) == set(SCORE_DIMS)
    assert 'Assumed' not in QUALITIES    # reserved, never emitted


# ---- builder and CLI integration (database) -------------------------------------


def test_build_scorecarard_confidence_fields(app):
    with app.app_context():
        from app.track_dna.scorecards import build_scorecard
        from tests.app.test_track_dna_calibration import (
            make_track, make_user,
        )
        from tests.app.test_track_dna_consensus import make_config
        from tests.app.test_track_dna_scorecards import seed_dna_laps

        owner = make_user()
        track = make_track(created_by=owner.id)
        config = make_config(track, owner)
        seed_dna_laps(track, config, owner, laps=2, day=1)
        card, result = build_scorecard(config.id, 'dry')
        assert card is not None

        # single-user, 2-lap seed: every present dimension Estimated
        by_key = {d['key']: d for d in card.dimensions_json}
        assert len(by_key) == 10
        for key, dim in by_key.items():
            assert dim['quality'] == 'Estimated', key
            assert dim['provenance'] == PROVENANCE[key]
            assert dim['counts'] == {'n_users': 1, 'n_laps': 2}
            assert any(w.startswith('single_user')
                       for w in dim['warnings'])
        assert any('convergence_not_demonstrated' in w
                   for w in by_key['track_length_m']['warnings'])
        conf = card.dataset_json['confidence']
        assert conf['n_users'] == 1
        assert conf['single_device'] is True     # racechrono only
        assert conf['convergence']['demonstrated'] is False
        assert conf['convergence']['demonstrated_n'] is not None
        assert 'elevation_gain' in conf['per_user_medians']

        # reproducibility: confidence is deterministic
        first = card.dimensions_json
        card2, _ = build_scorecard(config.id, 'dry')
        assert card2.dimensions_json == first
        assert card2.dataset_json['confidence'] == conf


def test_missing_speed_unavailable_on_card(app):
    with app.app_context():
        from app.track_dna.scorecards import build_scorecard
        from tests.app.test_track_dna_calibration import (
            make_track, make_user,
        )
        from tests.app.test_track_dna_consensus import make_config
        from tests.app.test_track_dna_scorecards import seed_dna_laps

        owner = make_user()
        track = make_track(created_by=owner.id)
        config = make_config(track, owner)
        seed_dna_laps(track, config, owner, laps=2, day=1,
                      with_speed=False)
        card, _ = build_scorecard(config.id, 'dry')
        by_key = {d['key']: d for d in card.dimensions_json}
        dim = by_key['heavy_braking_freq']
        assert dim['value'] is None            # missing is never zero
        assert dim['score'] is None
        assert dim['quality'] == 'Unavailable'
        assert dim['warnings'] == ['no_speed_channel']


def test_cli_prints_quality_column(app):
    with app.app_context():
        from app.track_dna.scorecards import build_scorecard
        from tests.app.test_track_dna_calibration import (
            make_track, make_user,
        )
        from tests.app.test_track_dna_consensus import make_config
        from tests.app.test_track_dna_scorecards import seed_dna_laps

        owner = make_user()
        track = make_track(created_by=owner.id)
        config = make_config(track, owner)
        seed_dna_laps(track, config, owner, laps=2, day=1)
        card, _ = build_scorecard(config.id, 'dry')
        assert card is not None
        track_id = track.id

    runner = app.test_cli_runner()
    result = runner.invoke(args=['compute-track-dna', str(track_id)])
    assert result.exit_code == 0
    assert 'Estimated' in result.output
    lines = [ln for ln in result.output.splitlines()
             if 'Track length' in ln]
    assert lines and lines[0].rstrip().endswith('Estimated')
