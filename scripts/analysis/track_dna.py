"""Track DNA geometry primitives.

Phase 2 of the Track DNA implementation plan: the pure-functions core that
the configuration-identification clustering builds on. Phase 3 extends this
module with the full geometry engine (resampling, smoothing, curvature,
corner/straight segmentation).

NumPy only — no app imports, matching the ``scripts/analysis/`` convention.
"""

import numpy as np


def signed_area(x, y):
    """Shoelace signed area of an ordered polyline (m^2).

    Positive for counter-clockwise traversal, negative for clockwise.
    The path does not need to be closed: the closing segment back to the
    first point is implicit, as required for lap loops.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size < 3:
        return 0.0
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def robust_bbox(x, y, percentiles=(2.5, 97.5)):
    """Percentile bounding box of a point cloud, glitch-robust.

    Returns ``(x0, y0, x1, y1)`` with the low/high percentiles taken
    independently per axis. Raw min/max bboxes get corrupted by GPS
    glitches (a production session showed a 2.7 x 8.5 km bbox on a
    ~230 m circuit); the percentile trim removes them while leaving
    genuine circuit extent intact.

    Returns ``(0.0, 0.0, 0.0, 0.0)`` for empty input.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size == 0:
        return (0.0, 0.0, 0.0, 0.0)
    lo, hi = percentiles
    x0, x1 = np.percentile(x, [lo, hi])
    y0, y1 = np.percentile(y, [lo, hi])
    return (float(x0), float(y0), float(x1), float(y1))


def bbox_iou(a, b):
    """Intersection-over-union of two ``(x0, y0, x1, y1)`` boxes.

    Returns 0.0 for disjoint or degenerate boxes.
    """
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b

    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)

    iw = max(ix1 - ix0, 0.0)
    ih = max(iy1 - iy0, 0.0)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0

    area_a = max(ax1 - ax0, 0.0) * max(ay1 - ay0, 0.0)
    area_b = max(bx1 - bx0, 0.0) * max(by1 - by0, 0.0)
    union = area_a + area_b - inter
    if union <= 0.0:
        return 0.0
    return inter / union
