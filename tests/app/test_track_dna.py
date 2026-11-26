"""Synthetic tests for the Track DNA geometry engine (plan Phase 3, Section 9).

Pure tests — no app/database fixtures. All paths are built in metre space
with a small segment DSL (straights + circular arcs) and closed either as a
capsule or with a 180° point reflection (``reflect_close``), which doubles
the half's turning and cancels its displacement, so every fixture is an
exact smooth closed loop with total heading ±360°.

Boundary fixtures use values calibrated to the engine's measurement
semantics rather than the plan's nominal ones where those are not
resolvable at 1 m grid quantisation (documented per test).
"""

import json
import math
import os

import numpy as np
import pytest

from scripts.analysis.track_dna import (
    DEFAULT_PARAMS,
    MIN_SAMPLES,
    LapInput,
    analyze_lap,
    analyze_session,
    circular_smooth,
    dedupe_static,
    resample_lap,
    _circular_runs,
)

# ---- path DSL ---------------------------------------------------------------


def build_path(segments, spacing=0.25):
    """Walk segments from the origin heading east.

    Segments: ``('straight', length_m)`` or ``('arc', radius_m, dtheta_deg)``
    with positive dtheta = left (counter-clockwise). Returns dense
    ``(x, y)`` points.
    """
    x, y, heading = 0.0, 0.0, 0.0
    pts = [(0.0, 0.0)]
    for seg in segments:
        if seg[0] == 'straight':
            length = seg[1]
            n = max(2, int(round(length / spacing)))
            for i in range(1, n + 1):
                d = length * i / n
                pts.append((x + d * math.cos(heading), y + d * math.sin(heading)))
            x += length * math.cos(heading)
            y += length * math.sin(heading)
        else:
            _, radius, dth = seg
            rad = math.radians(dth)
            s = 1.0 if dth >= 0 else -1.0
            cx = x - s * radius * math.sin(heading)
            cy = y + s * radius * math.cos(heading)
            arc_len = abs(rad) * radius
            n = max(2, int(round(arc_len / spacing)))
            bx, by = x - cx, y - cy
            for i in range(1, n + 1):
                a = rad * i / n
                ca, sa = math.cos(a), math.sin(a)
                pts.append((cx + bx * ca - by * sa, cy + bx * sa + by * ca))
            ca, sa = math.cos(rad), math.sin(rad)
            x = cx + bx * ca - by * sa
            y = cy + bx * sa + by * ca
            heading += rad
    return pts


def reflect_close(half_pts):
    """Close a half-loop with its 180° point reflection.

    The half must turn ±180° and start/end with straights, which makes both
    joints smooth. Turning doubles to ±360°; displacement cancels exactly.
    """
    (x0, y0), (x1, y1) = half_pts[0], half_pts[-1]
    refl = [(x0 + x1 - px, y0 + y1 - py) for (px, py) in half_pts]
    return half_pts + refl[1:]


def circle(R, spacing=0.25):
    n = max(200, int(round(2 * math.pi * R / spacing)))
    return [(R * math.cos(2 * math.pi * i / n),
             R * math.sin(2 * math.pi * i / n)) for i in range(n)]


def make_lap_input(points, dt=0.04):
    x = np.array([p[0] for p in points])
    y = np.array([p[1] for p in points])
    n = len(points)
    return LapInput(x=x, y=y, altitude=np.zeros(n), speed=np.full(n, 15.0),
                    elapsed=np.arange(n) * dt)


def roll_lap(points, k):
    """Rotate the lap's starting point to index k (moves the s=0 seam)."""
    return points[k:] + points[:k]


def analyze_points(points, **kwargs):
    return analyze_lap(make_lap_input(points), **kwargs)


def s_span_contains(straights, lap_length, s):
    """True when some straight's certified span covers metre position s."""
    for st in straights:
        start = st.s_start % lap_length
        end = start + st.length_m
        if start <= s <= end or start <= s + lap_length <= end:
            return True
    return False


# ---- fixture builders ---------------------------------------------------------


def fixture_oval(straight=80.0, radius=40.0):
    return build_path([('straight', straight), ('arc', radius, -180),
                       ('straight', straight), ('arc', radius, -180)])


def fixture_slow_corner():
    """Loop with two 90° R=30 corners (and gentle R=250 return arcs)."""
    half = build_path([('straight', 60), ('arc', 30, -90),
                       ('straight', 60), ('arc', 250, -90)])
    return reflect_close(half)


def fixture_hairpin():
    half = build_path([('straight', 60), ('arc', 12, -180), ('straight', 60)])
    return reflect_close(half)


def fixture_chicane(gap=25.0):
    half = build_path([('straight', 50), ('arc', 15, 45),
                       ('straight', gap), ('arc', 15, -45),
                       ('straight', 50), ('arc', 60, -180)])
    return reflect_close(half)


def fixture_compound():
    """Two same-sign 60° R=20 bends 15 m apart: must merge into one corner."""
    half = build_path([('straight', 50), ('arc', 20, -60),
                       ('straight', 15), ('arc', 20, -60),
                       ('straight', 50), ('arc', 250, -60)])
    return reflect_close(half)


def fixture_s_bend():
    """Opposite 40° R=15 bends 5 m apart: the PoC straight-classifier
    failure case — must NOT count as straight."""
    half = build_path([('straight', 50), ('arc', 15, 40),
                       ('straight', 5), ('arc', 15, -40),
                       ('straight', 50), ('arc', 60, -180)])
    return reflect_close(half)


def fixture_corner(theta_deg):
    """Loop with two corners of ``theta_deg`` at R=50 (gentle returns)."""
    half = build_path([('straight', 60), ('arc', 50, -theta_deg),
                       ('straight', 60), ('arc', 250, -(180 - theta_deg))])
    return reflect_close(half)


def fixture_capsule(straight, radius=60.0):
    return build_path([('straight', straight), ('arc', radius, -180),
                       ('straight', straight), ('arc', radius, -180)])


def _walk_end(segments):
    """Final (x, y, heading) after walking segments from origin, east."""
    x, y, heading = 0.0, 0.0, 0.0
    for seg in segments:
        if seg[0] == 'straight':
            x += seg[1] * math.cos(heading)
            y += seg[1] * math.sin(heading)
        else:
            _, radius, dth = seg
            rad = math.radians(dth)
            s = 1.0 if dth >= 0 else -1.0
            cx = x - s * radius * math.sin(heading)
            cy = y + s * radius * math.cos(heading)
            bx, by = x - cx, y - cy
            ca, sa = math.cos(rad), math.sin(rad)
            x = cx + bx * ca - by * sa
            y = cy + bx * sa + by * ca
            heading += rad
    return x, y, heading


def fixture_carousel():
    """A >300 deg carousel (two hard R=12 bends linked by an above-
    threshold R=140 section), closed by a straight + gentle arc whose
    parameters are solved in closed form so the loop returns exactly to
    its start with heading continuity. The lap starts mid-carousel, so
    the corner run wraps the s=0 seam.

    The carousel measures ~-345 deg: over the spin cap, but with a deep
    internal curvature relaxation — it must split into two corners, not
    flag a spin (Kiltorcan's real carousel behaves exactly like this).
    """
    carousel = [('arc', 12.0, -165), ('arc', 140.0, -8), ('arc', 12.0, -172)]
    px, py, _heading = _walk_end(carousel)
    a = math.radians(15.0)
    # closing arc(r, -15) ends at the origin heading east (right turn):
    # centre (0, -r), start angle 90+15 deg -> S(r); the straight from
    # (px, py) to S(r) runs along heading +15 deg.
    r = (px * math.sin(a) - py * math.cos(a)) / (math.cos(a) - 1.0)
    sx, sy = -r * math.sin(a), -r + r * math.cos(a)
    straight = (sx - px) * math.cos(a) + (sy - py) * math.sin(a)
    return build_path(carousel + [('straight', straight), ('arc', r, -15)])


# ---- unit tests: helpers -------------------------------------------------------


def test_dedupe_static_collapses_stationary_chain():
    x = np.array([0.0, 0.01, 0.02, 0.03, 1.0, 2.0, 2.02, 3.0])
    y = np.zeros(8)
    keep = dedupe_static(x, y, min_step_m=0.05)
    # first point always kept; jitter run collapses; real steps kept
    assert keep.tolist() == [True, False, False, False, True, True, False, True]


def test_circular_runs_merges_gaps_and_wraps():
    n = 20
    mask = np.zeros(n, dtype=bool)
    mask[5:7] = True        # run A
    mask[10:12] = True      # run B, 3-sample gap from A -> merges at max_gap 3
    mask[18:] = True        # run C wrapping the seam...
    mask[:1] = True         # ...through index 0
    runs = _circular_runs(mask, 3)
    # A+B merged into one run; C is the seam-crossing run starting at 18
    # (the partial head representative at 0 is dropped as contained)
    assert runs == [(5, 7), (18, 3)]


def test_circular_runs_full_lap():
    runs = _circular_runs(np.ones(10, dtype=bool), 0)
    assert runs == [(0, 10)]


def test_circular_smooth_is_periodic():
    # constant signal preserved
    const = circular_smooth(np.full(50, 3.0), 10.0, 1.0)
    assert np.allclose(const, 3.0)
    # periodicity = circular shift invariance
    t = np.arange(200)
    signal = np.sin(2 * np.pi * t / 50.0) + 0.3 * np.cos(2 * np.pi * t / 23.0)
    base = circular_smooth(signal, 10.0, 1.0)
    for k in (1, 7, 100, 199):
        rolled = circular_smooth(np.roll(signal, k), 10.0, 1.0)
        assert np.allclose(rolled, np.roll(base, k))


def test_resample_carries_channels_and_grid():
    pts = fixture_oval()
    lap = make_lap_input(pts, dt=0.05)
    grid, columns, length = resample_lap(lap)
    assert length == pytest.approx(80 + math.pi * 40 + 80 + math.pi * 40, abs=0.5)
    assert columns['x'].size == grid.size
    # channels present and elapsed strictly increasing
    assert columns['altitude'].size == grid.size
    assert np.all(np.diff(columns['elapsed']) > 0)
    # grid spacing is res metres
    assert np.allclose(np.diff(grid), DEFAULT_PARAMS.res_m)


# ---- synthetic fixtures ---------------------------------------------------------


def test_circle_r250_is_one_straight_no_corners():
    geo = analyze_points(circle(250))
    assert geo.corner_count == 0
    assert not geo.spun
    assert len(geo.straights) == 1
    assert geo.straights[0].length_m == pytest.approx(2 * math.pi * 250, rel=0.01)
    assert geo.straight_fraction == pytest.approx(1.0, abs=0.01)
    assert geo.heading_total_deg == pytest.approx(360, abs=1)


def test_circle_r30_full_rotation_flags_spin():
    """A full-rotation stretch exceeds the 300 deg per-corner cap with NO
    internal curvature relaxation (constant curvature): the true spin
    signature — segment dropped, lap flagged `spun` (diagnostic), lap
    kept. Contrast with test_carousel_over_cap_splits."""
    geo = analyze_points(circle(30))
    assert geo.spun
    assert geo.corner_count == 0
    assert geo.length_m == pytest.approx(2 * math.pi * 30, rel=0.01)


def test_carousel_over_cap_splits():
    """A >300 deg carousel with an internal curvature relaxation must
    split into two corners at the heading midpoint — not flag a spin and
    not drop the section (Kiltorcan's carousel measures 345-359 deg on
    every lap; dropping it broke the heading budget on 85% of real laps).
    The split must be seam-invariant: rolling the lap's start must give
    the same corner set."""
    pts = fixture_carousel()
    geo = analyze_points(pts)
    assert not geo.spun
    assert geo.corner_count == 2
    dths = sorted(c.delta_theta_deg for c in geo.corners)
    assert dths[0] == pytest.approx(-180.0, abs=6.0)
    assert dths[1] == pytest.approx(-178.0, abs=6.0)
    for c in geo.corners:
        assert c.sign == -1
        assert c.radius_m == pytest.approx(12.0, abs=2.0)
    # heading budget holds: the carousel's 345 deg is in the corner set
    budget = geo.heading_budget
    assert abs(budget['residue_deg']) <= 5.0, budget
    assert abs(budget['corners_deg'] + budget['straights_deg']
               + budget['subthreshold_deg'] + budget['spin_dropped_deg']
               + budget['residue_deg'] - geo.heading_total_deg) < 1e-6

    rolled = analyze_points(roll_lap(pts, k=300))
    assert rolled.corner_count == 2
    assert not rolled.spun
    rolled_dths = sorted(c.delta_theta_deg for c in rolled.corners)
    for a, b in zip(dths, rolled_dths):
        assert a == pytest.approx(b, abs=6.0)


def test_slow_corner_pair():
    geo = analyze_points(fixture_slow_corner())
    assert geo.corner_count == 2
    for c in geo.corners:
        assert c.delta_theta_deg == pytest.approx(-90.0, abs=1.0)
        assert c.radius_m == pytest.approx(30.0, abs=2.0)
        assert c.sign == -1
    assert geo.dc_count == 0
    assert not geo.spun


def test_oval_two_corners_two_straights():
    geo = analyze_points(fixture_oval())
    assert geo.corner_count == 2
    for c in geo.corners:
        assert c.delta_theta_deg == pytest.approx(-180.0, abs=0.5)
        assert c.radius_m == pytest.approx(40.0, abs=1.0)
    assert geo.dc_count == 0
    assert len(geo.straights) == 2
    # certified spans cover the 80 m straights (windows reach into the arcs)
    for st in geo.straights:
        assert 75.0 <= st.length_m <= 95.0
    assert geo.straight_total_m <= geo.length_m
    assert geo.longest_straight_m <= _diagonal(geo.bbox) + 1e-9


def _diagonal(bbox):
    x0, y0, x1, y1 = bbox
    return math.hypot(x1 - x0, y1 - y0)


def test_hairpin_paperclip():
    geo = analyze_points(fixture_hairpin())
    assert geo.corner_count == 2
    for c in geo.corners:
        assert c.delta_theta_deg == pytest.approx(-180.0, abs=1.0)
        assert c.radius_m == pytest.approx(12.0, abs=1.5)
    assert geo.dc_count == 0


def test_chicane_two_corners_one_dc():
    geo = analyze_points(fixture_chicane(gap=25.0))
    assert geo.corner_count == 6   # 2x (chicane pair + closing 180 R=60)
    chicane = [c for c in geo.corners if abs(c.delta_theta_deg) < 90]
    assert len(chicane) == 4       # two chicane pairs (reflection)
    signs = sorted({c.sign for c in chicane})
    assert signs == [-1, 1]
    assert geo.dc_count == 2       # one per chicane
    for dc in geo.direction_changes:
        assert dc.sign_before == -dc.sign_after


def test_dc_gap_boundary():
    """The engine's direction-change gap (index-space, end-to-start) hits
    29/30/31 m at geometric chicane gaps 44/45/46 (corner runs extend ~7 m
    into the straights on each side at R=15). The s-extent difference
    (s_start_next - s_end_prev) is one grid step larger than the index gap."""
    results = {}
    for gap in (44.0, 45.0, 46.0):
        geo = analyze_points(fixture_chicane(gap=gap))
        pair = [c for c in geo.corners if abs(c.delta_theta_deg) < 90]
        pair.sort(key=lambda c: c.s_start)
        measured = [pair[i + 1].s_start - pair[i].s_end
                    for i in range(0, len(pair), 2)]
        results[gap] = (measured, geo.dc_count)
    assert all(m == pytest.approx(30, abs=0.6) for m in results[44.0][0])
    assert results[44.0][1] == 2          # engine gap 29 <= 30
    assert all(m == pytest.approx(31, abs=0.6) for m in results[45.0][0])
    assert results[45.0][1] == 2          # engine gap 30 <= 30 (inclusive)
    assert all(m == pytest.approx(32, abs=0.6) for m in results[46.0][0])
    assert results[46.0][1] == 0          # engine gap 31 > 30


def test_compound_bend_merges_same_sign():
    geo = analyze_points(fixture_compound())
    assert geo.corner_count == 2
    for c in geo.corners:
        assert c.delta_theta_deg == pytest.approx(-120.0, abs=3.0)
        # radius is inflated ~7% by 10 m smoothing on 21 m arcs
        assert c.radius_m == pytest.approx(20.0, rel=0.15)
    assert geo.dc_count == 0


def test_s_bend_is_not_straight():
    """The PoC failure case: an S-bend must not be classified as straight.
    The D3 window test uses total heading variation (not net), so the
    cancellation that fooled the original classifier cannot happen."""
    geo = analyze_points(fixture_s_bend())
    # two opposite 40-degree bends per half -> 4 S corners + 2 closing corners
    assert geo.corner_count == 6
    s_corners = [c for c in geo.corners if abs(c.delta_theta_deg) < 90]
    assert len(s_corners) == 4
    assert geo.dc_count == 2
    # no straight's certified span covers the S-bend arc midpoints
    # (arcs sit at s ~ 55 and ~ 71 in the first half; mirrored in the second)
    lap = geo.length_m
    for s in (55.0, 71.0, 55.0 + lap / 2, 71.0 + lap / 2):
        assert not s_span_contains(geo.straights, lap, s), f'straight covers s={s}'


def test_corner_crosses_start_line():
    base = analyze_points(fixture_slow_corner())
    pts = fixture_slow_corner()
    # roll so s=0 sits mid-corner (corner run is roughly s=55..112)
    rolled = roll_lap(pts, k=int(80 / 0.25))
    geo = analyze_points(rolled)
    assert geo.corner_count == base.corner_count
    for a, b in zip(sorted(c.delta_theta_deg for c in base.corners),
                    sorted(c.delta_theta_deg for c in geo.corners)):
        assert a == pytest.approx(b, abs=0.5)
    for a, b in zip(sorted(c.radius_m for c in base.corners),
                    sorted(c.radius_m for c in geo.corners)):
        assert a == pytest.approx(b, rel=0.05)
    # the corner wraps the seam: s_end beyond the lap length or s_start large
    wrapping = [c for c in geo.corners if c.s_end > geo.length_m or c.s_start > geo.length_m * 0.8]
    assert wrapping, 'expected the seam-crossing corner to wrap'
    assert geo.heading_total_deg == pytest.approx(-360, abs=1)


def test_straight_crosses_start_line():
    base = analyze_points(fixture_oval())
    pts = fixture_oval()
    rolled = roll_lap(pts, k=int(40 / 0.25))   # s=0 mid-straight
    geo = analyze_points(rolled)
    assert len(geo.straights) == len(base.straights)
    for a, b in zip(sorted(st.length_m for st in base.straights),
                    sorted(st.length_m for st in geo.straights)):
        assert a == pytest.approx(b, abs=2.0)
    assert geo.corner_count == 2


def test_corner_delta_threshold():
    """Corner inclusion boundary at 30 degrees. The engine measures
    nominal - ~0.05 deg on these fixtures, so the include/exclude assertion
    uses 29.5/30.5 for cross-platform safety; measurement accuracy is
    asserted separately."""
    below = analyze_points(fixture_corner(29.5))
    assert below.corner_count == 0
    above = analyze_points(fixture_corner(30.5))
    assert above.corner_count == 2
    for c in above.corners:
        assert c.delta_theta_deg == pytest.approx(-30.5, abs=0.3)
    # accuracy: a 40-degree corner measures within 0.3 degrees
    geo = analyze_points(fixture_corner(40.0))
    assert geo.corner_count == 2
    for c in geo.corners:
        assert c.delta_theta_deg == pytest.approx(-40.0, abs=0.3)


def test_straight_minimum_boundary():
    """Certified straight length must reach straight_min_m (20). With R=60
    flanks the capsule's certified span is ~L + 7 m, so L=16 certifies ~22 m
    (kept) and L=13 cannot fit a qualifying window (dropped). The plan's
    literal 19.9/20 m pair is not resolvable at 1 m grid quantisation —
    the min-length filter itself is exercised via straight_min_m=25."""
    kept = analyze_points(fixture_capsule(straight=16.0))
    assert len(kept.straights) == 2
    for st in kept.straights:
        assert st.length_m >= DEFAULT_PARAMS.straight_min_m
        assert st.length_m == pytest.approx(22.0, abs=3.0)
    dropped = analyze_points(fixture_capsule(straight=13.0))
    assert len(dropped.straights) == 0
    raised = analyze_points(
        fixture_capsule(straight=16.0),
        params=_with(straight_min_m=25.0))
    assert len(raised.straights) == 0


def _with(**overrides):
    from dataclasses import replace
    return replace(DEFAULT_PARAMS, **overrides)


def test_multi_rate_invariance():
    """10 Hz vs 25 Hz-class sample spacing must give the same geometry
    (the 1 m resampler normalises input rate)."""
    results = []
    for spacing in (0.25, 0.6, 1.5):
        pts = build_path(
            [('straight', 80), ('arc', 40, -180),
             ('straight', 80), ('arc', 40, -180)], spacing=spacing)
        results.append(analyze_points(pts))
    for geo in results:
        assert geo.corner_count == 2
        for c in geo.corners:
            assert c.delta_theta_deg == pytest.approx(-180.0, abs=0.5)
            assert c.radius_m == pytest.approx(40.0, rel=0.05)
    lengths = [g.length_m for g in results]
    assert max(lengths) - min(lengths) < 2.0


def test_gps_noise_robustness():
    """Corner segmentation survives GPS-scale position noise (i.i.d. noise
    is harsher than the correlated noise of real receivers)."""
    pts = np.array(build_path(
        [('straight', 80), ('arc', 40, -180),
         ('straight', 80), ('arc', 40, -180)], spacing=0.4))
    rng = np.random.default_rng(42)
    noisy = pts + rng.normal(0.0, 0.1, pts.shape)
    geo = analyze_points(list(map(tuple, noisy)))
    assert geo.corner_count == 2
    assert not geo.spun
    for c in geo.corners:
        assert c.delta_theta_deg == pytest.approx(-180.0, abs=5.0)
        assert c.radius_m == pytest.approx(40.0, rel=0.15)


def test_reproducibility():
    pts = fixture_chicane()
    a = analyze_points(pts)
    b = analyze_points(pts)
    assert a.length_m == b.length_m
    assert a.summary() == b.summary()
    assert np.array_equal(a.x, b.x)
    assert np.array_equal(a.kappa, b.kappa)
    assert np.array_equal(a.theta, b.theta)


# ---- invariants (plan Section 9) -------------------------------------------------


@pytest.mark.parametrize('name', [
    'oval', 'slow_corner', 'hairpin', 'chicane', 'compound', 's_bend',
])
def test_invariants(name):
    geo = analyze_points(FIXTURES[name]())
    assert geo.length_m > 0
    assert 0.0 <= geo.straight_fraction <= 1.0
    assert geo.longest_straight_m <= geo.straight_total_m + 1e-9
    assert geo.straight_total_m <= geo.length_m + 1e-9
    assert geo.dc_count <= max(geo.corner_count - 1, 0)
    assert abs(geo.heading_total_deg) == pytest.approx(360, abs=2.0)
    # heading budget: corners + straights + dropped terms + residue = total,
    # tight on synthetics
    budget = geo.heading_budget
    assert abs(budget['residue_deg']) <= 2.0, budget
    assert abs(budget['corners_deg'] + budget['straights_deg']
               + budget['subthreshold_deg'] + budget['spin_dropped_deg']
               + budget['residue_deg'] - geo.heading_total_deg) < 1e-6
    # every straight's endpoints must lie inside the driven bbox
    for st in geo.straights:
        i0 = int(round((st.s_start / geo.length_m) * geo.x.size)) % geo.x.size
        i1 = int(round(((st.s_start + st.length_m) / geo.length_m)
                       * geo.x.size)) % geo.x.size
        for i in (i0, i1):
            assert geo.bbox[0] - 1 <= geo.x[i] <= geo.bbox[2] + 1
            assert geo.bbox[1] - 1 <= geo.y[i] <= geo.bbox[3] + 1


@pytest.mark.parametrize('name', ['oval', 'hairpin', 'chicane', 's_bend'])
def test_bbox_feasibility_true_straights(name):
    """Longest straight <= driven-bbox diagonal — the spec §19 invariant.
    Only checked on fixtures whose straights are geometrically straight:
    D3 deliberately classifies gentle (R >= R_min) arcs as straights, and a
    long gentle arc legitimately exceeds the bbox diagonal. On real laps
    (Kiltorcan) straights are true straights and the invariant holds."""
    geo = analyze_points(FIXTURES[name]())
    assert geo.longest_straight_m <= _diagonal(geo.bbox) + 1.0


FIXTURES = {
    'oval': fixture_oval,
    'slow_corner': fixture_slow_corner,
    'hairpin': fixture_hairpin,
    'chicane': fixture_chicane,
    'compound': fixture_compound,
    's_bend': fixture_s_bend,
}


# ---- golden fixture (Kiltorcan real telemetry) ------------------------------

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')
GOLDEN_NPZ = os.path.join(FIXTURE_DIR, 'track_dna_kiltorcan.npz')
GOLDEN_JSON = os.path.join(FIXTURE_DIR, 'track_dna_kiltorcan_expected.json')


@pytest.mark.skipif(not os.path.exists(GOLDEN_NPZ), reason='golden fixture missing')
def test_golden_kiltorcan():
    """Golden-file regression on real Kiltorcan telemetry (plan Section 9:
    the PoC track as golden regression per methodology version).

    Three laps exported from production (anonymised: metre-space,
    track-centred arrays only — no lat/lon or user metadata): the PoC
    reference lap (session 24 lap 1, RaceChrono), a GoPro lap (session 52)
    and a second RaceChrono lap (session 53). The engine must reproduce
    the stored summaries exactly and stay inside the Kiltorcan acceptance
    envelope (9 corners = the PoC's 7 + the carousel split; radii ~9-32 m;
    no spin; heading budget closed)."""
    data = np.load(GOLDEN_NPZ)
    expected = json.load(open(GOLDEN_JSON))
    assert expected['params'] == DEFAULT_PARAMS.__dict__
    assert len(expected['laps']) == 3

    for i, lap_spec in enumerate(expected['laps']):
        lap = LapInput(
            x=data[f'lap{i}_x'], y=data[f'lap{i}_y'],
            altitude=data[f'lap{i}_alt'], speed=data[f'lap{i}_speed'],
            elapsed=data[f'lap{i}_elapsed'],
            n_samples=int(data[f'lap{i}_x'].size))
        geo = analyze_lap(lap, lap_number=lap_spec['lap_number'])
        want = lap_spec['summary']
        got = geo.summary()

        assert geo.length_m == pytest.approx(want['length_m'], abs=0.05)
        assert geo.spun == want['spun']
        assert geo.corner_count == len(want['corners']) == 9
        assert geo.dc_count == len(want['direction_changes'])
        assert len(geo.straights) == len(want['straights'])
        for c, w in zip(geo.corners, want['corners']):
            assert c.s_start == pytest.approx(w['s_start'], abs=0.6)
            assert c.s_apex == pytest.approx(w['s_apex'], abs=0.6)
            assert c.delta_theta_deg == pytest.approx(w['delta_theta_deg'],
                                                     abs=0.1)
            assert c.radius_m == pytest.approx(w['radius_m'], abs=0.2)
        for st, w in zip(geo.straights, want['straights']):
            assert st.length_m == pytest.approx(w['length_m'], abs=0.6)
        budget_w = want['heading_budget']
        for key in ('corners_deg', 'straights_deg', 'subthreshold_deg',
                    'spin_dropped_deg', 'residue_deg'):
            assert got['heading_budget'][key] == pytest.approx(
                budget_w[key], abs=0.1)

        # Kiltorcan acceptance envelope (plan Sections 9/11)
        assert 985.0 <= geo.length_m <= 1010.0
        assert all(100.0 <= abs(c.delta_theta_deg) <= 280.0
                   for c in geo.corners)
        assert all(8.0 <= c.radius_m <= 40.0 for c in geo.corners)
        assert abs(geo.heading_budget['residue_deg']) <= 5.0
        assert geo.longest_straight_m <= _diagonal(geo.bbox)


# ---- session validity (plan Section 4.1 / D8) -------------------------------------


def test_session_validity_filters():
    oval_pts = build_path([('straight', 80), ('arc', 40, -180),
                           ('straight', 80), ('arc', 40, -180)])
    long_pts = build_path([('straight', 104), ('arc', 52, -180),
                           ('straight', 104), ('arc', 52, -180)])  # +30% length
    laps = {
        1: make_lap_input(oval_pts, dt=0.04),             # valid
        2: make_lap_input(oval_pts[:50], dt=0.04),        # insufficient samples
        3: make_lap_input(oval_pts, dt=0.12),             # 3x duration
        4: make_lap_input(long_pts, dt=0.04),             # length out of range
        5: make_lap_input(circle(65, spacing=0.4), dt=0.05),  # spun, still valid
    }
    result = analyze_session(laps)
    # spun laps are NOT rejected: lap 5 stays valid with spun=True and its
    # >300 deg section excluded from the corner set
    assert result.n_valid == 2
    spun = [lap for lap in result.laps if lap.lap_number == 5][0]
    assert spun.spun
    assert spun.corner_count == 0
    reasons = {r.lap_number: r.reason for r in result.rejected}
    assert reasons == {
        2: 'insufficient_samples',
        3: 'duration_out_of_range',
        4: 'length_out_of_range',
    }


def test_session_min_samples_boundary():
    pts = build_path([('straight', 40), ('arc', 20, -180),
                      ('straight', 40), ('arc', 20, -180)], spacing=0.5)
    assert len(pts) >= MIN_SAMPLES
    just_enough = make_lap_input(pts[:MIN_SAMPLES])
    too_few = make_lap_input(pts[:MIN_SAMPLES - 1])
    result = analyze_session({1: just_enough, 2: too_few})
    assert result.n_valid == 1
    assert [r.reason for r in result.rejected] == ['insufficient_samples']


def test_session_reproducibility():
    laps = {i: make_lap_input(fixture_oval()) for i in range(1, 6)}
    a = analyze_session(laps)
    b = analyze_session(laps)
    assert a.n_valid == b.n_valid == 5
    assert [lap.summary() for lap in a.laps] == [lap.summary() for lap in b.laps]
    assert [r.reason for r in a.rejected] == [r.reason for r in b.rejected]


def test_session_empty():
    result = analyze_session({})
    assert result.n_valid == 0
    assert result.median_duration_s is None
