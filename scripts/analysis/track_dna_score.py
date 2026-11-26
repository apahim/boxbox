"""Track DNA scorecard normalisation and similarity (plan Phase 7,
spec Section 19).

Pure module (NumPy only — no app imports): the engine-scale anchor
ladders that turn the ten raw dimension values into 0-10 scores and
five-level labels, the agreed weight split (geometry 75 / braking 15 /
elevation 10), the overall weighted score, and the weighted-Manhattan
similarity with coverage.

Owner-confirmed 2026-11-26 (plan 19.1/19.4, resolving the 16.4g gate):
the original requirements doc's bands were never committed, so this
table is re-anchored to engine scale per 15.2e, calibrated on the
2026-11-26 prod cross-track measurement (Kiltorcan dry/wet,
Whiteriver, Muret, Watergrasshill, Athboy). The PoC's Section 12
anchors are superseded — engine v1.0 measures straight% ~18 (not 7.9),
longest straight ~70 m (not 32), DC ~4.1/km (not 3.02), 9 corners
(not 7).

Missing dimensions (e.g. no speed channel -> dimension 9) carry no
score and no label, are excluded from the overall score, and shrink
similarity coverage — missing is never zero (D5/D8).
"""

import numpy as np


# key -> (anchors, scores, unit, display, labels, weight)
# anchors/scores: piecewise-linear ladder, clamped at both ends.
DIMENSIONS = {
    'track_length_m': {
        'anchors': (500.0, 800.0, 1100.0, 1500.0, 2000.0),
        'unit': 'm',
        'display': 'Track length',
        'labels': ('Very short', 'Short', 'Medium', 'Long', 'Very long'),
        'weight': 10,
    },
    'straight_pct': {
        'anchors': (5.0, 10.0, 20.0, 35.0, 50.0),
        'unit': '%',
        'display': 'Straight proportion',
        'labels': ('Very twisty', 'Twisty', 'Balanced', 'Straight',
                   'Very straight'),
        'weight': 10,
    },
    'longest_straight_m': {
        'anchors': (30.0, 60.0, 100.0, 150.0, 250.0),
        'unit': 'm',
        'display': 'Longest straight',
        'labels': ('Very short', 'Short', 'Medium', 'Long', 'Very long'),
        'weight': 8,
    },
    'corner_density_per_km': {
        'anchors': (4.0, 7.0, 10.0, 14.0, 20.0),
        'unit': '/km',
        'display': 'Corner density',
        'labels': ('Very low', 'Low', 'Moderate', 'High', 'Very high'),
        'weight': 12,
    },
    'slow_corner_prop': {
        'anchors': (0.0, 20.0, 40.0, 60.0, 80.0),
        'unit': '%',
        'display': 'Slow corners',
        'labels': ('Very low', 'Low', 'Moderate', 'High', 'Very high'),
        'weight': 8,
    },
    'medium_corner_prop': {
        'anchors': (0.0, 20.0, 40.0, 60.0, 80.0),
        'unit': '%',
        'display': 'Medium corners',
        'labels': ('Very low', 'Low', 'Moderate', 'High', 'Very high'),
        'weight': 8,
    },
    'fast_corner_prop': {
        'anchors': (0.0, 20.0, 40.0, 60.0, 80.0),
        'unit': '%',
        'display': 'Fast corners',
        'labels': ('Very low', 'Low', 'Moderate', 'High', 'Very high'),
        'weight': 8,
    },
    'dc_per_km': {
        'anchors': (1.0, 3.0, 5.0, 8.0, 12.0),
        'unit': '/km',
        'display': 'Direction changes',
        'labels': ('Very low', 'Low', 'Moderate', 'High', 'Very high'),
        'weight': 11,
    },
    'heavy_braking_freq': {
        'anchors': (0.0, 1.0, 2.0, 3.5, 5.0),
        'unit': 'events/km',
        'display': 'Heavy braking',
        'labels': ('Very low', 'Low', 'Moderate', 'High', 'Very high'),
        'weight': 15,
    },
    'elevation_gain': {
        'anchors': (3.0, 6.0, 12.0, 20.0, 35.0),
        'unit': 'm/km',
        'display': 'Elevation gain',
        'labels': ('Flat', 'Gentle', 'Rolling', 'Hilly', 'Very hilly'),
        'weight': 10,
    },
}

SCORES = (0.0, 2.5, 5.0, 7.5, 10.0)

# label bands on the 0-10 score: [0, 1.25) [1.25, 3.75) [3.75, 6.25)
# [6.25, 8.75) [8.75, 10]
LABEL_EDGES = (1.25, 3.75, 6.25, 8.75)

TOTAL_WEIGHT = sum(spec['weight'] for spec in DIMENSIONS.values())
assert TOTAL_WEIGHT == 100, TOTAL_WEIGHT


def score_for(key, value):
    """Piecewise-linear anchor score in [0, 10], clamped at both ends."""
    anchors = DIMENSIONS[key]['anchors']
    return float(np.interp(float(value), anchors, SCORES))


def label_for(key, score):
    """Five-level label from the score band."""
    labels = DIMENSIONS[key]['labels']
    for i, edge in enumerate(LABEL_EDGES):
        if score < edge:
            return labels[i]
    return labels[-1]


def normalise_dimensions(raw):
    """Raw values (key -> value or None) -> the scorecard's dimension
    list. Missing values keep the slot with score/label None (missing
    is never zero) and are excluded from the overall score."""
    dimensions = []
    for key, spec in DIMENSIONS.items():
        value = raw.get(key)
        score = label = None
        if value is not None:
            score = round(score_for(key, value), 2)
            label = label_for(key, score)
        dimensions.append({
            'key': key,
            'display': spec['display'],
            'value': None if value is None else round(float(value), 2),
            'unit': spec['unit'],
            'class': label,
            'score': score,
            'weight': spec['weight'],
        })
    return dimensions


def overall_score(dimensions):
    """Weighted mean of the present dimension scores (0-10), or None
    when nothing is present."""
    total = 0.0
    weight = 0
    for dim in dimensions:
        if dim['score'] is not None:
            total += dim['score'] * dim['weight']
            weight += dim['weight']
    return round(total / weight, 2) if weight else None


def similarity(dimensions_a, dimensions_b):
    """Weighted-Manhattan similarity with coverage (plan Section 19.3).

    Over dimensions present on BOTH cards:
    ``sim = 100 * (1 - sum(w_i * |s_a - s_b|) / (10 * sum(w_i)))`` —
    symmetric by construction, 100 for identical cards, in [0, 100].
    ``coverage`` is the shared weight over the total (100); each
    contribution is the percentage points a dimension adds to the
    distance. Missing dimensions never count as zero.
    """
    a = {d['key']: d for d in dimensions_a}
    b = {d['key']: d for d in dimensions_b}
    shared_weight = 0.0
    distance = 0.0
    contributions = {}
    for key, spec in DIMENSIONS.items():
        da, db = a.get(key), b.get(key)
        if da is None or db is None:
            continue
        if da['score'] is None or db['score'] is None:
            continue
        shared_weight += spec['weight']
        delta = abs(da['score'] - db['score'])
        distance += spec['weight'] * delta
        contributions[key] = spec['weight'] * delta
    if shared_weight <= 0:
        return {'similarity_pct': None, 'coverage': 0.0,
                'contributions': {}}
    scaled = {key: round(100.0 * v / (10.0 * shared_weight), 2)
              for key, v in contributions.items()}
    return {
        'similarity_pct': round(100.0 * (1.0 - distance
                                         / (10.0 * shared_weight)), 2),
        'coverage': round(shared_weight / TOTAL_WEIGHT, 3),
        'contributions': scaled,
    }
