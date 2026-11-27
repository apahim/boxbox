"""Track DNA card builder and queries (reference-lap methodology).

The write path for ``track_dna_cards``: load the admin-selected
reference lap → engine → ``reference_consensus`` → braking + elevation
→ normalise → upsert one row per (track, methodology_version).

Cards exist on official tracks only (enforced here, not just in
routes): a card is a statement about a track in the public catalog,
computed by the admin from a chosen lap. No hooks call this (the D7
pattern): the admin-page trigger and the CLI are the only callers.
"""

import math
from dataclasses import asdict

from app import db
from app.models import Track, TrackDnaCard
from app.track_dna.reference import load_reference, reference_verdict
from scripts.analysis.track_dna import DEFAULT_PARAMS, signed_area
from scripts.analysis.track_dna_braking import (
    DEFAULT_BRAKING_PARAMS,
    analyze_braking,
)
from scripts.analysis.track_dna_elevation import (
    DEFAULT_ELEVATION_PARAMS,
    analyze_elevation,
)
from scripts.analysis.track_dna_reference import ConsensusLap, \
    reference_consensus
from scripts.analysis.track_dna_score import (
    normalise_dimensions,
    overall_score,
)

# v2.1: corner speed classes recalibrated to rental-kart radii
# (slow < 15 m, medium 15-26 m, fast >= 26 m) — dimensions 5-7
# proportions shift accordingly
METHODOLOGY_VERSION = '2.1'

# Cap on the emitted trajectory's point count — enough for a smooth
# satellite-map polyline at ~3-5 m spacing on a 1 km circuit while
# keeping the stored card small.
MAX_TRAJECTORY_POINTS = 300


def _trajectory_block(consensus, track):
    """Decimated (s, lat, lon) trajectory for the map.

    The loader projects telemetry about the track datum
    (``project_to_meters`` with ``center=(track.lat, track.lon)``); this
    is its exact inverse, so the UI can place any circuit-frame
    s-position (zone troughs, corner apexes) on a map by linear
    interpolation. The grid starts at s=0 and carries no periodic
    duplicate; the loop is closed implicitly. Returns ``None`` when the
    track has no datum (no map possible) or the circuit is empty.
    """
    if track.lat is None or track.lon is None:
        return None
    n = int(consensus.grid.size)
    if n == 0:
        return None
    stride = max(1, -(-n // MAX_TRAJECTORY_POINTS))
    kx = 111320.0 * math.cos(math.radians(track.lat))
    points = []
    for i in range(0, n, stride):
        s = float(consensus.grid[i])
        x = float(consensus.x[i])
        y = float(consensus.y[i])
        points.append([round(s, 1),
                       round(track.lat + y / 110540.0, 6),
                       round(track.lon + x / kx, 6)])
    return {
        'length_m': round(float(consensus.length_m), 2),
        'n_points': len(points),
        'points': points,
    }


def build_card(track_id, engine_params=DEFAULT_PARAMS,
               braking_params=DEFAULT_BRAKING_PARAMS,
               elevation_params=DEFAULT_ELEVATION_PARAMS,
               commit=True):
    """Compute, normalise and upsert one track's DNA card.

    Returns ``(card, result)`` — the stored ``TrackDnaCard`` row and
    the underlying compute result — or ``(None, result)`` with an
    ``error`` key when the track is not official, has no reference lap
    or the reference lap is not usable.
    """
    track = db.session.get(Track, track_id)
    result = {'track_id': track_id}
    if track is None:
        result['error'] = f'no track {track_id}'
        return None, result
    result['track_name'] = track.name
    if track.created_by is not None:
        result['error'] = (f'track "{track.name}" is not official — '
                           'Track DNA is only computed for official tracks')
        return None, result

    ref = load_reference(track, engine_params)
    if not ref['ok']:
        result['error'] = ref['error']
        return None, result

    session = ref['session']
    geo = ref['lap']
    record = ConsensusLap(user_id=session.user_id,
                          session_id=session.id,
                          lap_number=geo.lap_number,
                          device=session.data_source or 'unknown',
                          geometry=geo)
    consensus = reference_consensus(record, engine_params)

    result.update({
        'consensus': consensus.summary(),
        'braking': analyze_braking(consensus,
                                   params=braking_params).summary(),
        'elevation': analyze_elevation(consensus,
                                       params=elevation_params).summary(),
        'trajectory': _trajectory_block(consensus, track),
    })

    dims_c = result['consensus']['dimensions']
    braking = result['braking']['dimensions']
    elevation = result['elevation']['dimensions']
    raw = {
        'track_length_m': dims_c['track_length_m']['value'],
        'straight_pct': dims_c['straight_pct']['value'],
        'longest_straight_m': dims_c['longest_straight_m']['value'],
        'corner_density_per_km':
            dims_c['corner_density_per_km']['value'],
        'slow_corner_prop': dims_c['slow_corner_prop']['value'],
        'medium_corner_prop': dims_c['medium_corner_prop']['value'],
        'fast_corner_prop': dims_c['fast_corner_prop']['value'],
        'dc_per_km': dims_c['dc_per_km']['value'],
        'heavy_braking_freq': braking['heavy_braking_freq']['value'],
        'elevation_gain': elevation['elevation_gain']['value'],
    }
    dimensions = normalise_dimensions(raw)
    for dim in dimensions:
        if dim['key'] == 'heavy_braking_freq':
            dim['sensitivity'] = braking['heavy_braking_freq'].get(
                'sensitivity')
        elif dim['key'] == 'elevation_gain':
            dim['evidence'] = {
                'per_lap_median_m':
                    elevation['elevation_gain'].get('per_lap_median_m'),
                'window_by_device':
                    elevation['elevation_gain'].get('window_by_device'),
            }

    area = signed_area(geo.x, geo.y)
    dataset = {
        'source': 'reference-lap',
        'session_id': session.id,
        'lap_number': geo.lap_number,
        'lap_time_s': (round(float(geo.duration_s), 3)
                       if geo.duration_s is not None else None),
        'device': session.data_source,
        'date': session.date.isoformat() if session.date else None,
        'direction': 'cw' if area < 0 else 'ccw',
    }

    card = db.session.query(TrackDnaCard).filter_by(
        track_id=track_id,
        methodology_version=METHODOLOGY_VERSION).first()
    if card is None:
        card = TrackDnaCard(track_id=track_id,
                            methodology_version=METHODOLOGY_VERSION)
        db.session.add(card)
    card.params_json = {
        'engine': asdict(engine_params),
        'braking': asdict(braking_params),
        'elevation': asdict(elevation_params),
    }
    card.dimensions_json = dimensions
    card.overall_score = overall_score(dimensions)
    card.dataset_json = dataset
    card.support_json = {
        'consensus': result['consensus'],
        'braking': result['braking'],
        'elevation': result['elevation'],
        'trajectory': result.get('trajectory'),
    }
    card.computed_at = db.func.now()
    if commit:
        db.session.commit()
    return card, result


def latest_card(track_id):
    """The track's highest-methodology-version card, or None."""
    return (TrackDnaCard.query.filter_by(track_id=track_id)
            .order_by(TrackDnaCard.methodology_version.desc())
            .first())


def summarize_card(card):
    """Plain-language interpretation of a stored card.

    Derived on the fly from ``dimensions_json`` + ``support_json`` (no
    stored summary, so existing cards get it without a recompute):
    a one-line headline verdict, a handful of fact chips and a short
    blurb that connects the dimensions into driving meaning. All
    pieces degrade gracefully when a dimension is missing.
    """
    dims = {d['key']: d for d in (card.dimensions_json or [])}
    support = card.support_json or {}
    corners = (support.get('consensus') or {}).get('corners') or []
    zones = (support.get('braking') or {}).get('zones') or []

    def val(key):
        d = dims.get(key) or {}
        return d.get('value')

    def cls(key):
        d = dims.get(key) or {}
        return d.get('class')

    # ---- headline: pace character + braking + elevation --------------------
    straight = cls('straight_pct')
    if straight in ('Straight', 'Very straight'):
        pace = 'Fast, flowing circuit'
    elif straight in ('Twisty', 'Very twisty'):
        pace = 'Tight, technical circuit'
    else:
        pace = 'Balanced circuit'

    braking = val('heavy_braking_freq')
    if braking is None:
        stop = 'no braking data'
    elif braking < 1.0:
        stop = 'light braking'
    elif braking < 2.5:
        stop = 'a few heavy stops'
    else:
        stop = 'several heavy braking zones'

    elev = cls('elevation_gain')
    ground = ('flat' if elev in (None, 'Flat') else elev.lower())

    headline = f'{pace} — {stop}, on {ground} ground.'

    # ---- chips: the standout facts -----------------------------------------
    chips = []
    if val('track_length_m') is not None:
        chips.append(f"{val('track_length_m'):.0f} m lap")
    if corners:
        mix = {'slow': 0, 'medium': 0, 'fast': 0}
        for c in corners:
            mix[c.get('class')] = mix.get(c.get('class'), 0) + 1
        chips.append('{} corners ({} slow / {} medium / {} fast)'.format(
            len(corners), mix.get('slow', 0), mix.get('medium', 0),
            mix.get('fast', 0)))
    if val('longest_straight_m') is not None:
        chips.append(f"longest straight {val('longest_straight_m'):.0f} m")
    if braking is not None:
        chips.append(f"{len(zones)} heavy braking "
                     f"zone{'s' if len(zones) != 1 else ''}")
    if val('dc_per_km') is not None:
        chips.append(f"{val('dc_per_km'):.1f} direction changes/km")
    if elev not in (None, 'Flat'):
        chips.append(f"{elev.lower()} elevation "
                     f"({val('elevation_gain'):.0f} m/km)")
    rights = sum(1 for c in corners if c.get('sign', 0) < 0)
    lefts = len(corners) - rights
    if corners and rights != lefts:
        chips.append(f"{'right' if rights > lefts else 'left'}-hand "
                     f"bias ({rights}R / {lefts}L)")

    # ---- blurb: connect the dimensions into driving meaning ----------------
    sentences = []

    # the longest straight, and whether its end is the biggest stop
    length = ((support.get('consensus') or {}).get('dimensions')
              or {}).get('track_length_m', {}).get('value')
    if corners and length and len(corners) > 1:
        ordered = sorted(corners, key=lambda c: c['s_apex'])
        gaps = []
        for i, c in enumerate(ordered):
            nxt = ordered[(i + 1) % len(ordered)]
            gap = nxt['s_start'] - c['s_end']
            if i == len(ordered) - 1:
                gap += length
            gaps.append((gap, c, nxt))
        gaps.sort(key=lambda g: -g[0])
        gap, _c, after = gaps[0]
        if gap > 30.0:
            if zones:
                strongest = max(zones, key=lambda z: z['reduction_pct'])
                in_gap = (after['s_start'] - gap) <= strongest['s_trough'] \
                    <= after['s_start']
                if in_gap:
                    sentences.append(
                        "The longest straight feeds the circuit's "
                        "biggest stop — a "
                        f"{strongest['reduction_pct']:.0f}% slowdown "
                        "into the next corner.")
                else:
                    sentences.append(
                        "The longest straight ends without a heavy "
                        "stop — carried speed counts for more than "
                        "braking there.")
            else:
                sentences.append(
                    "The longest straight runs clear of heavy "
                    "braking.")

    dc = cls('dc_per_km')
    if dc in ('High', 'Very high'):
        sentences.append('Direction changes come thick and fast — a '
                         'rhythm track where momentum matters more '
                         'than outright power.')
    elif dc in ('Low', 'Very low'):
        sentences.append('With few direction changes, the lap is built '
                         'around a handful of decisive corners.')

    slow = val('slow_corner_prop')
    fast = val('fast_corner_prop')
    if slow is not None and fast is not None:
        if slow >= 45.0:
            sentences.append('Most corners are slow and tight — '
                             'traction on corner exit defines the lap.')
        elif fast >= 45.0:
            sentences.append('Most corners are fast and sweeping — '
                             'commitment and a clean line carry the lap.')

    if elev in ('Rolling', 'Hilly', 'Very hilly'):
        sentences.append('The elevation changes add load-transfer '
                         'work on both brake and throttle.')

    if not sentences:
        sentences.append('A compact lap where positioning and '
                         'consistency beat aggression.')
    blurb = ' '.join(sentences[:4])

    return {'headline': headline, 'chips': chips, 'blurb': blurb}


def card_payload(card, track=None):
    """JSON payload for the API (UI input), with live reference state."""
    track = track or card.track
    verdict = reference_verdict(track)
    return {
        'id': card.id,
        'track_id': card.track_id,
        'track_name': track.name,
        'methodology_version': card.methodology_version,
        'computed_at': (card.computed_at.isoformat()
                        if card.computed_at else None),
        'overall_score': card.overall_score,
        'summary': summarize_card(card),
        'dimensions': card.dimensions_json,
        'dataset': card.dataset_json,
        'support': card.support_json,
        'reference_ok': verdict['ok'],
        'reference_error': verdict.get('error'),
    }
