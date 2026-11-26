"""Track DNA scorecard builder and queries (plan Phase 7, spec 19).

The write path for ``track_dna_scorecards``: compute (the Phase 4–6
pipeline via ``compute_config``) → normalise (engine-scale anchor
ladders, owner-confirmed 2026-11-26) → upsert one row per (config,
condition, methodology_version). No hooks call this (D7 revised): the
CLI is the entry point now, the admin-page trigger in Phase 9.
"""

import hashlib
import json
from dataclasses import asdict

from app import db
from app.models import Track, TrackConfig, TrackDnaScorecard
from app.track_dna.consensus import compute_config
from app.track_dna.loader import select_config_sessions
from scripts.analysis.track_dna import DEFAULT_PARAMS
from scripts.analysis.track_dna_braking import DEFAULT_BRAKING_PARAMS
from scripts.analysis.track_dna_confidence import assign_confidence
from scripts.analysis.track_dna_consensus import DEFAULT_CONSENSUS_PARAMS
from scripts.analysis.track_dna_elevation import DEFAULT_ELEVATION_PARAMS
from scripts.analysis.track_dna_score import (
    normalise_dimensions,
    overall_score,
    similarity,
)

METHODOLOGY_VERSION = '1.0'

CONDITIONS = ('dry', 'wet')


def build_scorecard(track_config_id, condition='dry',
                    params=DEFAULT_CONSENSUS_PARAMS,
                    engine_params=DEFAULT_PARAMS,
                    braking_params=DEFAULT_BRAKING_PARAMS,
                    elevation_params=DEFAULT_ELEVATION_PARAMS,
                    commit=True):
    """Compute, normalise and upsert one configuration's scorecard.

    Returns ``(card, result)`` — the stored ``TrackDnaScorecard`` row
    and the underlying compute result — or ``(None, result)`` with an
    ``error`` key when the condition has no valid laps.
    """
    result = compute_config(track_config_id, condition, params=params,
                            engine_params=engine_params,
                            braking_params=braking_params,
                            elevation_params=elevation_params)
    if 'error' in result:
        return None, result

    consensus = result['consensus']['dimensions']
    braking = result['braking']['dimensions']
    elevation = result['elevation']['dimensions']
    raw = {
        'track_length_m': consensus['track_length_m']['value'],
        'straight_pct': consensus['straight_pct']['value'],
        'longest_straight_m': consensus['longest_straight_m']['value'],
        'corner_density_per_km':
            consensus['corner_density_per_km']['value'],
        'slow_corner_prop': consensus['slow_corner_prop']['value'],
        'medium_corner_prop': consensus['medium_corner_prop']['value'],
        'fast_corner_prop': consensus['fast_corner_prop']['value'],
        'dc_per_km': consensus['dc_per_km']['value'],
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

    # Phase 8 (plan 20): per-dimension quality classes + provenance +
    # counts + warnings, and the card-level evidence block
    dim_conf, card_conf = assign_confidence(result['consensus'],
                                            result['braking'],
                                            result['elevation'],
                                            result['dataset'])
    for dim in dimensions:
        conf = dim_conf[dim['key']]
        dim['quality'] = conf['quality']
        dim['provenance'] = conf['provenance']
        dim['counts'] = conf['counts']
        dim['warnings'] = conf['warnings']

    dataset = dict(result['dataset'])
    dataset['condition'] = condition
    dataset['session_fingerprint'] = session_fingerprint(
        dataset.get('session_ids') or [])
    dataset['confidence'] = card_conf

    card = db.session.query(TrackDnaScorecard).filter_by(
        track_config_id=track_config_id, condition=condition,
        methodology_version=METHODOLOGY_VERSION).first()
    if card is None:
        card = TrackDnaScorecard(
            track_config_id=track_config_id,
            methodology_version=METHODOLOGY_VERSION,
            condition=condition)
        db.session.add(card)
    card.params_json = {
        'engine': asdict(engine_params),
        'consensus': asdict(params),
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
        # Phase 9 (plan 21.3): decimated (s, lat, lon) consensus
        # trajectory for the map; None when the track has no datum
        'trajectory': result.get('trajectory'),
    }
    card.computed_at = db.func.now()
    card.stale = False
    if commit:
        db.session.commit()
    return card, result


def session_fingerprint(session_ids):
    """Stable sha256 of the sorted session ids (staleness visibility)."""
    payload = json.dumps(sorted(int(s) for s in session_ids))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def current_fingerprint(track_config_id, condition='dry'):
    """Re-derive a configuration's current session fingerprint (plan
    21.4, admin staleness display).

    Uses the same selection the compute path makes (the loader's
    ``select_config_sessions``), so a mismatch with a stored card's
    ``dataset_json['session_fingerprint']`` means exactly "the compute
    input set changed". Read-only, display-only (D7 revised — nothing
    acts on it). Returns ``None`` for an unknown config.
    """
    config = db.session.get(TrackConfig, track_config_id)
    if config is None:
        return None
    _dataset, verdicts = select_config_sessions(
        config.track_id, condition=condition, track_config_id=config.id)
    return session_fingerprint([v.session_id for v in verdicts])


def scorecards_for_track(track_id):
    """All scorecard rows for a track's configurations."""
    return (TrackDnaScorecard.query.join(TrackConfig)
            .filter(TrackConfig.track_id == track_id)
            .order_by(TrackConfig.id, TrackDnaScorecard.condition,
                      TrackDnaScorecard.methodology_version.desc())
            .all())


def card_payload(card):
    """JSON payload for the API (Phase 9 UI input)."""
    return {
        'id': card.id,
        'track_id': card.config.track_id,
        'track_config_id': card.track_config_id,
        'config_name': card.config.name,
        'direction': card.config.direction,
        'condition': card.condition,
        'methodology_version': card.methodology_version,
        'computed_at': (card.computed_at.isoformat()
                        if card.computed_at else None),
        'stale': card.stale,
        'overall_score': card.overall_score,
        'dimensions': card.dimensions_json,
        'dataset': card.dataset_json,
        'support': card.support_json,
    }


def similar_payload(track_id, condition='dry', visible_track_ids=None):
    """On-the-fly weighted-Manhattan similarity (plan 19.3): the
    track's latest-version cards for the condition vs every other
    configuration's card of the same condition and version.

    ``visible_track_ids`` (plan 21.6, owner-confirmed): optional set of
    track ids the viewer may see — comparisons are limited to it. The
    default (``None``) keeps the CLI/test behaviour of comparing
    against every configuration.
    """
    cards = [c for c in scorecards_for_track(track_id)
             if c.condition == condition]
    if not cards:
        return None
    version = max(c.methodology_version for c in cards)
    mine = [c for c in cards if c.methodology_version == version]
    my_config_ids = {c.track_config_id for c in mine}

    others_q = (TrackDnaScorecard.query.join(TrackConfig)
                .filter(TrackDnaScorecard.condition == condition,
                        TrackDnaScorecard.methodology_version == version,
                        TrackConfig.track_id != track_id))
    if visible_track_ids is not None:
        others_q = others_q.filter(
            TrackConfig.track_id.in_(visible_track_ids))
    others = others_q.all()
    names = {t.id: t.name for t in Track.query.all()}

    configs = []
    for card in mine:
        comparisons = []
        for other in others:
            if other.track_config_id in my_config_ids:
                continue
            sim = similarity(card.dimensions_json, other.dimensions_json)
            comparisons.append({
                'track_id': other.config.track_id,
                'track_name': names.get(other.config.track_id),
                'track_config_id': other.track_config_id,
                'config_name': other.config.name,
                'condition': other.condition,
                'similarity_pct': sim['similarity_pct'],
                'coverage': sim['coverage'],
                'contributions': sim['contributions'],
            })
        comparisons.sort(key=lambda c: -(c['similarity_pct'] or 0.0))
        configs.append({
            'track_config_id': card.track_config_id,
            'config_name': card.config.name,
            'overall_score': card.overall_score,
            'comparisons': comparisons,
        })
    return {
        'track_id': track_id,
        'condition': condition,
        'methodology_version': version,
        'configs': configs,
    }
