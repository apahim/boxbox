"""Tests for the circuit badge generator (Track DNA UI)."""

from app.track_dna.badges import badge_svg

from tests.app.track_dna_helpers import capsule_points, m_to_latlon


def synthetic_trajectory(straight=80.0, radius=40.0):
    """A capsule-loop trajectory block like the card builder stores."""
    pts = capsule_points(straight, radius)
    points = []
    s = 0.0
    prev = None
    for px, py in pts:
        if prev is not None:
            s += ((px - prev[0]) ** 2 + (py - prev[1]) ** 2) ** 0.5
        lat, lon = m_to_latlon(px, py)
        points.append([round(s, 1), round(lat, 6), round(lon, 6)])
        prev = (px, py)
    return {'length_m': round(s, 2), 'n_points': len(points),
            'points': points}


def path_d(svg):
    """The d attribute of the badge's single path."""
    start = svg.index('d="') + 3
    return svg[start:svg.index('"', start)]


def test_badge_shape():
    svg = badge_svg(synthetic_trajectory())
    assert svg is not None
    assert svg.startswith('<svg')
    assert svg.endswith('</svg>')
    assert 'viewBox="0 0 100 100"' in svg
    assert 'stroke="currentColor"' in svg          # CSS controls color
    assert 'fill="none"' in svg
    d = path_d(svg)
    assert d.startswith('M ')                       # a moveto
    assert d.endswith(' Z')                         # closed loop
    # all coordinates inside the viewBox
    coords = [float(v) for v in d.replace('M ', '').replace(' L ', ' ')
              .replace(' Z', '').split()]
    assert len(coords) % 2 == 0
    assert all(-1.0 <= v <= 101.0 for v in coords)
    # enough points to read as a circuit, not a blob
    assert d.count(' L ') >= 20


def test_badge_none_for_missing_or_short_trajectory():
    assert badge_svg(None) is None
    assert badge_svg({}) is None
    assert badge_svg({'points': []}) is None
    assert badge_svg({'points': [[0, 52.0, -7.0]]}) is None


def test_badge_aspect_preserved_and_centered():
    """A wide loop (long straights) fills the width, not the height,
    and stays centred in the square viewBox."""
    svg = badge_svg(synthetic_trajectory(straight=300.0, radius=30.0))
    d = path_d(svg)
    pairs = [tuple(map(float, p.split()))
             for p in d.replace('M ', '').rstrip(' Z').split(' L ')]
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    # padded to the full width, much less than full height
    assert max(xs) - min(xs) == 76.0          # 100 - 2*12 padding
    assert max(ys) - min(ys) < 40.0
    # centred
    assert (max(xs) + min(xs)) / 2 == 50.0
    assert (max(ys) + min(ys)) / 2 == 50.0
