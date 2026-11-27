"""Circuit badge generation for Track DNA.

Turns a stored card trajectory into a single-stroke closed-loop SVG —
a stylised circuit outline usable as a track emblem (page header now,
track-list thumbnails later). Pure function, no state: the caller
passes the ``support_json['trajectory']`` block and gets an SVG
string (or ``None`` when there is nothing to draw).

The SVG strokes with ``currentColor`` so the page's CSS controls the
colour; geometry is centred and aspect-preserved inside a square
viewBox (north up).
"""

import math


_BADGE_SIZE = 100.0
_BADGE_PAD = 12.0


def badge_svg(trajectory, size=_BADGE_SIZE, pad=_BADGE_PAD):
    """A closed-loop circuit outline SVG for one stored trajectory.

    ``trajectory`` is the card's ``support_json['trajectory']`` dict
    (``points``: ``[[s, lat, lon], ...]``, ``length_m``). Returns an
    SVG string, or ``None`` when the trajectory is missing or too
    short to read as a loop.
    """
    points = (trajectory or {}).get('points')
    if not points or len(points) < 4:
        return None

    lats = [p[1] for p in points]
    lons = [p[2] for p in points]
    lat0 = (min(lats) + max(lats)) / 2.0
    lon0 = (min(lons) + max(lons)) / 2.0

    # equirectangular projection about the loop centroid (metres) —
    # the same projection the loader uses, inverted
    kx = 111320.0 * math.cos(math.radians(lat0))
    xs = [(lon - lon0) * kx for lon in lons]
    ys = [(lat - lat0) * 110540.0 for lat in lats]

    # fit, aspect-preserved, into the square viewBox (north up)
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-6)
    scale = (size - 2.0 * pad) / span
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    coords = [(size / 2.0 + (x - cx) * scale,
               size / 2.0 - (y - cy) * scale)      # y flipped: north up
              for x, y in zip(xs, ys)]

    # the loop closes implicitly: last point back to the first
    d = ('M ' + ' L '.join(f'{x:.1f} {y:.1f}' for x, y in coords)
         + ' Z')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {size:g} {size:g}" class="track-badge-svg" '
            f'fill="none" stroke="currentColor" stroke-width="5" '
            f'stroke-linejoin="round" stroke-linecap="round" '
            f'role="img" aria-label="Circuit outline">'
            f'<path d="{d}"/></svg>')
