"""Tests for the Track DNA consensus layer (plan Phase 4).

Pure synthetic tests for the consensus pipeline (reusing the Phase 3
fixture DSL from ``test_track_dna.py``) plus smoke tests for the
read-only runner, mirroring the calibration test style.
"""

import json
import math

import numpy as np
import pytest

from scripts.analysis.track_dna import DEFAULT_PARAMS
from scripts.analysis.track_dna_consensus import (
    DEFAULT_CONSENSUS_PARAMS,
    ConsensusLap,
    _align_shift,
    _circular_clusters,
    _circular_median,
    _curvature_profile,
    _map_corner,
    _sample_positions,
    build_consensus,
)
from tests.app.test_track_dna import (
    analyze_points,
    build_path,
    circle,
    fixture_chicane,
    fixture_oval,
    make_lap_input,
    reflect_close,
    roll_lap,
)

# ---- helpers -----------------------------------------------------------------


def consensus_lap(user_id, session_id, points, lap_number=1):
    return ConsensusLap(user_id=user_id, session_id=session_id,
                        lap_number=lap_number,
                        geometry=analyze_points(points))


def capsule(straight=80.0, radius=40.0):
    return build_path([('straight', straight), ('arc', radius, -180),
                       ('straight', straight), ('arc', radius, -180)])


def fixture_two_corner():
    """Capsule: two -180 deg R40 corners (the oval)."""
    return capsule(80.0, 40.0)


def fixture_four_corner():
    """Same loop with an extra -40 deg R25 bend on each straight.

    The two -140/-180 deg R40 corners sit within a few metres of
    ``fixture_two_corner``'s (same cluster); the R25 bends are ~95 m
    from anything else, so recurrence alone decides whether they count.
    """
    half = build_path([('straight', 40), ('arc', 25, -40),
                       ('straight', 40), ('arc', 40, -140)])
    return reflect_close(half)


def fixture_slow_fast():
    """Two R12 hairpins (slow) + two 70 deg R60 bends (fast) per lap."""
    half = build_path([('straight', 50), ('arc', 12, -110),
                       ('straight', 30), ('arc', 60, -70)])
    return reflect_close(half)


# ---- unit tests: alignment and circular statistics -----------------------------


def test_align_shift_recovers_known_roll():
    n = DEFAULT_CONSENSUS_PARAMS.align_grid
    t = np.arange(n)
    profile = 2 * math.pi * t / n + 0.4 * np.sin(2 * math.pi * t / n * 7)
    for k in (0, 5, 37, 400):
        frac, r = _align_shift(np.roll(profile, k), profile,
                               DEFAULT_CONSENSUS_PARAMS)
        expected = k / n
        if expected > 0.5:
            expected -= 1.0
        assert frac == pytest.approx(expected, abs=1.5 / n)
        assert r > 0.99


def test_align_shift_prefers_zero_on_symmetric_profile():
    """A symmetric heading profile ties the true peak with its alias;
    the zero-shift preference must break the tie towards zero."""
    n = DEFAULT_CONSENSUS_PARAMS.align_grid
    t = np.arange(n)
    # two identical halves -> correlation ties at shift 0 and n/2
    half = np.sin(2 * math.pi * t[:n // 2] / (n // 2) * 3)
    profile = np.concatenate([half, half]) + 0.3 * t / n
    frac, r = _align_shift(profile, profile, DEFAULT_CONSENSUS_PARAMS)
    assert frac == pytest.approx(0.0, abs=1.5 / n)
    assert r == pytest.approx(1.0, abs=1e-9)


def test_circular_clusters_wrap_and_chaining():
    circ = 1000.0
    clusters = _circular_clusters([100, 102, 103, 500, 998, 1, 2], 30.0,
                                  circ)
    assert sorted(sorted(c) for c in clusters) == [[0, 1, 2], [3], [4, 5, 6]]
    # single linkage: a point chains while it is within the tolerance of
    # the cluster's LAST member, so a cluster's diameter may exceed it
    # (200 -> 245 chains in 15/30 m steps; 245 -> 276 at 31 m breaks)
    clusters = _circular_clusters([200, 215, 245, 276], 30.0, circ)
    assert [sorted(c) for c in clusters] == [[0, 1, 2], [3]]
    assert _circular_clusters([], 30.0, circ) == []
    assert _circular_clusters([42.0], 30.0, circ) == [[0]]


def test_circular_median_wraps():
    assert _circular_median([998, 1, 2], 1000.0) == pytest.approx(1.0,
                                                                 abs=0.1)
    assert _circular_median([10, 20, 30], 1000.0) == pytest.approx(20.0)


def test_map_corner_unwraps_seam_wrapping_run():
    """A corner wrapping the s=0 seam keeps its true edge offsets."""
    geo = analyze_points(roll_lap(fixture_slow(), k=int(80 / 0.25)))
    corner = [c for c in geo.corners
              if c.s_end > geo.length_m or c.s_start > 0.8 * geo.length_m][0]
    m_apex, d_start, d_end = _map_corner(geo, corner, 0.0, geo.length_m)
    # offsets are small and ordered regardless of the seam wrap
    assert -80.0 < d_start < 0.0
    assert 0.0 < d_end < 80.0
    assert 0.0 <= m_apex < geo.length_m


def fixture_slow():
    half = build_path([('straight', 60), ('arc', 30, -90),
                       ('straight', 60), ('arc', 250, -90)])
    return reflect_close(half)


# ---- consensus: identity, seam invariance, alignment --------------------------


def test_identical_laps_consensus():
    pts = fixture_oval()
    geo = analyze_points(pts)
    laps = [consensus_lap(1, 1, pts, 1), consensus_lap(1, 1, pts, 2),
            consensus_lap(2, 2, pts, 1)]
    result = build_consensus(laps, condition='dry')

    assert result.condition == 'dry'
    assert len(result.laps) == 3
    assert result.corner_count == geo.corner_count == 2
    for a, b in zip(sorted(c.s_apex for c in geo.corners),
                    sorted(c.s_apex for c in result.corners)):
        assert a == pytest.approx(b, abs=3.0)
    for a, b in zip(sorted(c.delta_theta_deg for c in geo.corners),
                    sorted(c.delta_theta_deg for c in result.corners)):
        assert a == pytest.approx(b, abs=2.0)
    assert all(c.recurrence == 1.0 for c in result.corners)
    assert all(v == 1.0 for c in result.corners
               for v in c.support_by_user.values())

    assert result.length_m == pytest.approx(geo.length_m, abs=1.0)
    assert result.arclength_m == pytest.approx(geo.length_m, abs=3.0)
    assert result.straight_pct == pytest.approx(
        100.0 * geo.straight_fraction, abs=1.0)
    assert result.longest_straight_m == pytest.approx(
        geo.longest_straight_m, abs=3.0)
    assert result.dc_per_km == pytest.approx(geo.dc_per_km, abs=0.5)

    # identical laps align at zero shift (not at a symmetric alias)
    assert float(np.max(np.abs(result.shifts_m))) < 2.0

    # the median trajectory is the lap sampled on the consensus grid
    grid_t = np.arange(result.x.size) / result.x.size
    lx, ly = _sample_positions(geo, 0.0, grid_t)
    assert np.max(np.hypot(result.x - lx, result.y - ly)) < 1.0

    # proportions sum to 100% exactly (integer counts over the set)
    total = sum(result.corner_props.values())
    assert total == pytest.approx(100.0)

    summary = result.summary()
    assert summary['n_laps'] == 3
    assert summary['n_users'] == 2
    assert summary['n_spun_excluded'] == 0
    assert summary['dimensions']['track_length_m']['value'] == (
        pytest.approx(result.length_m, abs=0.01))
    assert json.dumps(summary)  # JSON-serialisable


def test_rolled_laps_same_consensus():
    """Seam-shifted laps must contribute the same corners at the same
    consensus positions (full-circle alignment + seam-invariant engine
    corners)."""
    pts = fixture_oval()
    base = analyze_points(pts)
    base_apexes = sorted(c.s_apex for c in base.corners)
    laps = [consensus_lap(1, 1, pts, 1),
            consensus_lap(1, 1, pts, 2),
            consensus_lap(2, 2, roll_lap(pts, k=12), 1),    # ~3 m seam shift
            consensus_lap(2, 2, roll_lap(pts, k=160), 2)]   # ~40 m seam shift
    result = build_consensus(laps)

    assert result.corner_count == 2
    for a, b in zip(base_apexes, sorted(c.s_apex for c in result.corners)):
        assert a == pytest.approx(b, abs=4.0)
    assert all(c.recurrence == 1.0 for c in result.corners)
    assert result.length_m == pytest.approx(base.length_m, abs=1.0)
    assert result.corner_count == result.cross_check['corner_count']


def test_recurrence_threshold():
    """Recurrence decides corner membership, exactly at the 50% boundary.

    Fixture geometry (measured, deterministic): the two fixtures share
    one corner position (merged cluster) and split elsewhere —
    ``two``'s corners land at ~180/330 m, ``four'''s at ~39/172/240/372 m
    in the consensus frame, so 2+2 laps give five clusters (one shared
    with 4 laps, four with 2 laps each = exactly 50%).
    """
    two = fixture_two_corner()
    four = fixture_four_corner()
    laps = [consensus_lap(1, 1, two, 1), consensus_lap(1, 1, two, 2),
            consensus_lap(1, 1, four, 3), consensus_lap(1, 1, four, 4)]
    result = build_consensus(laps)
    assert result.corner_count == 5
    assert sorted(c.n_laps for c in result.corners) == [2, 2, 2, 2, 4]
    assert all(c.recurrence >= 0.5 for c in result.corners)

    # below the threshold (1 of 3 laps = 33%) the four-corner fixture's
    # own clusters drop out; the shared cluster survives on all laps
    laps = [consensus_lap(1, 1, two, 1), consensus_lap(1, 1, two, 2),
            consensus_lap(1, 1, four, 3)]
    result = build_consensus(laps)
    assert result.corner_count == 2
    assert sorted(c.n_laps for c in result.corners) == [2, 3]
    assert all(c.recurrence >= 0.5 for c in result.corners)


def test_unequal_user_lap_counts_do_not_skew():
    """D6: a 10-lap user must not outweigh a 2-lap user — the circuit
    median is the median of the two users' medians, not the flat one."""
    short = capsule(79.0, 40.0)   # ~409.3 m
    long = capsule(81.0, 40.0)    # ~413.3 m
    laps = ([consensus_lap(1, 1, short, i) for i in range(1, 11)]
            + [consensus_lap(2, 2, long, 1),
               consensus_lap(2, 2, long, 2)])
    result = build_consensus(laps)

    assert result.length_m == pytest.approx(160.0 + 2 * math.pi * 40.0,
                                            abs=1.0)
    assert 410.0 < result.length_m < 412.5   # flat median would be ~409.3
    assert set(result.per_user['track_length_m']) == {1, 2}
    assert result.per_user['track_length_m'][1]['n_laps'] == 10
    assert result.per_user['track_length_m'][2]['n_laps'] == 2


def test_spun_laps_excluded():
    pts = fixture_oval()                      # ~411 m
    spun_pts = circle(70.0, spacing=0.4)      # ~440 m, constant curvature
    laps = [consensus_lap(1, 1, pts, 1), consensus_lap(1, 1, pts, 2),
            consensus_lap(1, 1, spun_pts, 3),
            consensus_lap(1, 1, spun_pts, 4)]
    result = build_consensus(laps)

    assert len(result.spun) == 2
    assert len(result.laps) == 2
    assert result.length_m == pytest.approx(analyze_points(pts).length_m,
                                            abs=1.0)
    assert result.corner_count == 2
    summary = result.summary()
    assert summary['n_spun_excluded'] == 2
    assert {s['lap_number']
            for s in summary['data_quality']['spun_laps']} == {3, 4}


def test_single_lap_consensus():
    pts = fixture_chicane()
    geo = analyze_points(pts)
    result = build_consensus([consensus_lap(1, 1, pts, 1)])

    assert result.corner_count == geo.corner_count
    assert all(c.recurrence == 1.0 for c in result.corners)
    assert result.length_m == pytest.approx(geo.length_m, abs=0.5)
    conv = result.convergence
    assert conv['acceptance'] is not None
    assert conv['acceptance']['n_laps'] == 1
    assert all(e['length_m']['spread'] == 0.0 for e in conv['draws'])


def test_consensus_dimensions_and_cross_check():
    """Chicane: 4 medium (R15 arcs measure ~22 m after smoothing) + 2
    fast (R60) corners, one DC per chicane pair; the frozen engine on
    the consensus line must agree."""
    pts = fixture_chicane()
    laps = ([consensus_lap(1, 1, pts, i) for i in range(1, 4)]
            + [consensus_lap(2, 2, pts, 1)])
    result = build_consensus(laps)

    assert result.corner_count == 6
    props = result.corner_props
    assert props['medium'] == pytest.approx(100.0 * 4 / 6, abs=1e-6)
    assert props['fast'] == pytest.approx(100.0 * 2 / 6, abs=1e-6)
    assert props['slow'] == 0.0
    assert sum(props.values()) == pytest.approx(100.0)

    assert result.dc_consensus_count == 2
    cross = result.cross_check
    assert cross['corner_count'] == 6
    assert cross['dc_count'] == 2
    assert cross['straight_pct'] == pytest.approx(result.straight_pct,
                                                  abs=5.0)

    summary = result.summary()
    dims = summary['dimensions']
    assert dims['corner_count']['value'] == 6
    assert dims['medium_corner_prop']['value'] == pytest.approx(
        100.0 * 4 / 6, abs=0.01)
    assert dims['dc_count']['evidence']['consensus_set_count'] == 2
    # per-corner per-user support is recorded (evidence for user weighting)
    assert all('support_by_user' in c and c['support_by_user']
               for c in summary['corners'])


def test_consensus_radius_classes():
    """Slow (R12) and fast (R60) corners classify across the provisional
    boundaries, and the proportions come from the set (sum to 100%)."""
    pts = fixture_slow_fast()
    laps = [consensus_lap(1, 1, pts, 1), consensus_lap(2, 2, pts, 1)]
    result = build_consensus(laps)

    assert result.corner_count == 4
    radii = sorted(c.radius_m for c in result.corners)
    assert radii[0] == pytest.approx(12.0, abs=3.0)
    assert radii[-1] == pytest.approx(60.0, abs=8.0)
    props = result.corner_props
    assert props['slow'] == pytest.approx(50.0, abs=1e-6)
    assert props['fast'] == pytest.approx(50.0, abs=1e-6)
    assert props['medium'] == 0.0
    assert sum(props.values()) == pytest.approx(100.0)


def test_consensus_reproducible():
    pts = fixture_oval()
    laps = [consensus_lap(1, 1, pts, 1),
            consensus_lap(2, 2, roll_lap(pts, k=160), 1)]
    a = build_consensus(laps)
    b = build_consensus(laps)
    assert a.summary() == b.summary()
    assert np.array_equal(a.x, b.x)
    assert np.array_equal(a.y, b.y)


def test_build_consensus_errors():
    with pytest.raises(ValueError):
        build_consensus([])
    with pytest.raises(ValueError):
        build_consensus([consensus_lap(1, 1, circle(30), 1)])


def test_curvature_profile_is_a_clean_roll():
    """The alignment signature must be seam-free: a rolled lap's profile
    is the base profile sampled at the shifted positions (the unwrapped
    heading fails this — its 2*pi seam step moves with the roll)."""
    pts = fixture_oval()
    base = analyze_points(pts)
    rolled = analyze_points(roll_lap(pts, k=160))   # ~40 m seam shift
    n = DEFAULT_CONSENSUS_PARAMS.align_grid
    L = base.length_m
    pr = _curvature_profile(rolled, n)
    # expected: the base's own kappa, sampled 40 m downstream (mod L)
    kappa = np.asarray(base.kappa)
    s = np.asarray(base.s)
    s_ext = np.concatenate([s, [L]])
    k_ext = np.concatenate([kappa, [kappa[0]]])
    q = (np.arange(n) / n * L + 40.0) % L
    expected = np.interp(q, s_ext, k_ext)
    assert np.max(np.abs(pr - expected)) < 0.002
    assert pr.size == n


# ---- runner smoke tests (database) ----------------------------------------------

from datetime import date  # noqa: E402

from app import db  # noqa: E402
from app.models import Session, Telemetry, TrackConfig  # noqa: E402
from app.track_dna.consensus import compute_config, run  # noqa: E402
from app.track_dna.loader import load_track_laps  # noqa: E402
from tests.app.test_track_dna_calibration import (  # noqa: E402
    capsule_points,
    make_track,
    make_user,
    m_to_latlon,
)


def make_config(track, user, name='Rental Layout'):
    config = TrackConfig(track_id=track.id, name=name, direction='cw',
                         created_by=user.id, confirmed=True)
    db.session.add(config)
    db.session.flush()
    return config


def seed_config_laps(track, config, user, labels=None, laps=2,
                     straight=80.0, radius=40.0, day=1):
    session = Session(user_id=user.id, track_id=track.id,
                      track_config_id=config.id if config else None,
                      labels=labels, data_source='racechrono',
                      date=date(2026, 1, day))
    db.session.add(session)
    db.session.flush()
    pts = capsule_points(straight, radius)
    for lap_number in range(1, laps + 1):
        for i, (px, py) in enumerate(pts):
            lat, lon = m_to_latlon(px, py)
            db.session.add(Telemetry(
                session_id=session.id,
                lap_number=lap_number,
                elapsed_time=0.05 * i,
                distance_traveled=(len(pts) * 0.5 * (lap_number - 1)
                                   + 0.5 * i),
                latitude=lat, longitude=lon, altitude=10.0, speed_gps=12.0))
    db.session.flush()
    return session


def test_compute_config_dry_wet_and_filters(app):
    owner = make_user()
    track = make_track(created_by=owner.id)
    config = make_config(track, owner)
    u1 = make_user(email='u1@test.com')
    u2 = make_user(email='u2@test.com')
    dry1 = seed_config_laps(track, config, u1, laps=2, day=1)
    dry2 = seed_config_laps(track, config, u1, laps=2, day=2)
    dry3 = seed_config_laps(track, config, u2, laps=2, day=3)
    wet = seed_config_laps(track, config, u2, labels=['Wet'], laps=2, day=4)
    seed_config_laps(track, config, u1, labels=['Demo'], laps=2, day=5)   # D1
    seed_config_laps(track, None, u2, laps=2, day=6)                      # not a member

    # loader: config membership first, hygiene on top
    _, sessions, _ = load_track_laps(track.id, track_config_id=config.id)
    assert sorted(e['session_id'] for e in sessions) == sorted(
        [s.id for s in (dry1, dry2, dry3, wet)])
    assert all(e['date'] == f'2026-01-0{e["session_id"]}' for e in sessions)

    dry = compute_config(config.id, 'dry')
    assert dry['condition'] == 'dry'
    assert dry['config_name'] == 'Rental Layout'
    assert dry['dataset']['laps']['valid'] == 6
    assert dry['dataset']['users'] == {u1.id: 2, u2.id: 1}
    assert dry['consensus']['n_laps'] == 6
    assert dry['consensus']['n_users'] == 2
    assert dry['consensus']['n_spun_excluded'] == 0

    dims = dry['consensus']['dimensions']
    assert dims['corner_count']['value'] == 2
    assert dims['track_length_m']['value'] == pytest.approx(
        2 * 80 + 2 * math.pi * 40, abs=2.0)
    assert dims['corner_density_per_km']['value'] == pytest.approx(
        2 / ((2 * 80 + 2 * math.pi * 40) / 1000.0), rel=0.01)
    props = (dims['slow_corner_prop']['value']
             + dims['medium_corner_prop']['value']
             + dims['fast_corner_prop']['value'])
    assert props == pytest.approx(100.0)
    assert dry['consensus']['convergence']['acceptance'] is not None
    assert dry['consensus']['data_quality']['spun_laps'] == []

    # wet is a separate bucket, never mixed (D1/D6)
    wet_result = compute_config(config.id, 'wet')
    assert wet_result['dataset']['laps']['valid'] == 2
    assert wet_result['consensus']['n_laps'] == 2
    assert wet_result['consensus']['n_users'] == 1


def test_compute_config_no_data(app):
    owner = make_user()
    track = make_track(created_by=owner.id)
    config = make_config(track, owner)
    result = compute_config(config.id, 'dry')
    assert result['error'] == 'no valid laps for this condition'
    assert compute_config(999)['error'].startswith('no track config')


def test_run_dispatch(app, capsys):
    owner = make_user()
    track = make_track(created_by=owner.id)
    config = make_config(track, owner)
    seed_config_laps(track, config, owner, laps=2)

    result = run(config.id, 'dry')
    assert result['track_config_id'] == config.id
    printed = capsys.readouterr().out
    assert 'dimensions' in printed
    parsed = json.loads(printed)
    assert (parsed['consensus']['dimensions']['corner_count']['value']
            == 2)
