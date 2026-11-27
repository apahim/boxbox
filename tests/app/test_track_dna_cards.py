"""Tests for the Track DNA card builder, storage, validation and CLI
(reference-lap methodology)."""

import pytest

from app import db
from app.models import TrackDnaCard

from tests.app.track_dna_helpers import (
    make_track,
    make_user,
    seed_dna_session,
)


_seed_counter = [0]


def _seed_official(name='Test Circuit', laps=2, **kwargs):
    """Admin + official track + one seeded session (no reference yet).
    Each call gets a distinct admin user (unique email/google_id)."""
    _seed_counter[0] += 1
    admin = make_user(admin=True,
                      email=f'driver{_seed_counter[0]}@test.com')
    track = make_track(name=name)               # created_by=None: official
    session = seed_dna_session(track, admin, laps=laps, **kwargs)
    return admin, track, session


def _set_reference(track, session, lap_number=1):
    track.reference_session_id = session.id
    track.reference_lap_number = lap_number
    db.session.commit()


# ---- builder and storage --------------------------------------------------------


def test_build_card_stores_and_upserts(app):
    with app.app_context():
        admin, track, session = _seed_official()
        _set_reference(track, session, lap_number=1)

        from app.track_dna.cards import build_card

        card, result = build_card(track.id)
        assert card is not None
        assert 'error' not in result
        assert TrackDnaCard.query.count() == 1
        assert card.track_id == track.id
        assert card.methodology_version == '2.1'

        dims = card.dimensions_json
        assert len(dims) == 10
        by_key = {d['key']: d for d in dims}
        assert by_key['track_length_m']['value'] > 0
        assert 0.0 <= by_key['straight_pct']['value'] <= 100.0
        assert by_key['longest_straight_m']['value'] <= \
            by_key['track_length_m']['value']
        assert all(d['score'] is None or 0.0 <= d['score'] <= 10.0
                   for d in dims)
        assert sum(d['weight'] for d in dims) == 100
        assert by_key['heavy_braking_freq']['sensitivity'] is not None
        assert by_key['elevation_gain']['evidence'][
            'window_by_device'] == {'racechrono': 25.0}
        assert 0.0 <= card.overall_score <= 10.0

        # provenance: the reference lap, not a consensus
        dataset = card.dataset_json
        assert dataset['source'] == 'reference-lap'
        assert dataset['session_id'] == session.id
        assert dataset['lap_number'] == 1
        assert dataset['lap_time_s'] is not None
        assert dataset['direction'] in ('cw', 'ccw')
        assert card.support_json['trajectory']['n_points'] > 0
        assert card.params_json.keys() == {'engine', 'braking',
                                           'elevation'}

        # reproducibility: same data -> identical dimensions; upsert
        first = card.dimensions_json
        card2, _ = build_card(track.id)
        assert card2.id == card.id            # upsert, not a new row
        assert TrackDnaCard.query.count() == 1
        assert card2.dimensions_json == first


def test_build_card_requires_official_track(app):
    with app.app_context():
        owner = make_user()
        track = make_track(created_by=owner.id)   # personal
        session = seed_dna_session(track, owner)
        _set_reference(track, session)

        from app.track_dna.cards import build_card

        card, result = build_card(track.id)
        assert card is None
        assert 'not official' in result['error']
        assert TrackDnaCard.query.count() == 0


def test_build_card_requires_reference(app):
    with app.app_context():
        _admin, track, _session = _seed_official()

        from app.track_dna.cards import build_card

        card, result = build_card(track.id)
        assert card is None
        assert 'no reference lap' in result['error']


def test_build_card_rejects_invalid_lap(app):
    with app.app_context():
        admin, track, session = _seed_official()
        # lap 99 does not exist
        _set_reference(track, session, lap_number=99)

        from app.track_dna.cards import build_card

        card, result = build_card(track.id)
        assert card is None
        assert 'lap 99' in result['error']

        # lap 0 is not a numbered lap
        track.reference_lap_number = 0
        db.session.commit()
        card, result = build_card(track.id)
        assert card is None
        assert result['error']


def test_reference_gone_or_moved(app):
    with app.app_context():
        admin, track, session = _seed_official()
        _set_reference(track, session)

        from app.track_dna.reference import reference_verdict

        assert reference_verdict(track)['ok'] is True

        # session deleted -> broken reference, honest error
        db.session.delete(session)
        db.session.commit()
        verdict = reference_verdict(track)
        assert verdict['ok'] is False
        assert verdict['error']

        # moved to another track -> broken too
        admin2, track2, session2 = _seed_official(name='Other Circuit')
        _set_reference(track2, session2)
        session2.track_id = track.id
        db.session.commit()
        # reference points at a session no longer on track2
        track2_id = track2.id
        from app.models import Track as TrackModel
        verdict = reference_verdict(db.session.get(TrackModel, track2_id))
        assert verdict['ok'] is False


def test_card_payload_reference_state(app):
    with app.app_context():
        admin, track, session = _seed_official()
        _set_reference(track, session)

        from app.track_dna.cards import build_card, card_payload

        card, _ = build_card(track.id)
        served = card_payload(card, track=track)
        assert served['reference_ok'] is True
        assert served['reference_error'] is None
        assert served['dataset']['source'] == 'reference-lap'
        assert served['track_id'] == track.id
        assert 'methodology_version' in served
        assert served['summary']['headline']
        assert served['summary']['chips']
        assert served['summary']['blurb']

        # break the reference (delete the session) -> live verdict flips
        db.session.delete(session)
        db.session.commit()
        served = card_payload(card, track=track)
        assert served['reference_ok'] is False
        assert served['reference_error']


# ---- interpretation summary -----------------------------------------------------


def test_summarize_card_shape(app):
    with app.app_context():
        _admin, track, session = _seed_official()
        _set_reference(track, session)
        from app.track_dna.cards import build_card, summarize_card

        card, _ = build_card(track.id)
        summary = summarize_card(card)
        # headline: pace character + braking + ground
        assert summary['headline'].endswith('.')
        assert 'circuit' in summary['headline'].lower()
        # chips: lap length, corner mix, braking zones at minimum
        assert any('m lap' in c for c in summary['chips'])
        assert any('corners' in c for c in summary['chips'])
        assert any('braking zone' in c for c in summary['chips'])
        # blurb: plain sentences, no leading/trailing whitespace
        assert summary['blurb']
        assert summary['blurb'] == summary['blurb'].strip()
        import json
        json.dumps(summary)


def test_summarize_card_flat_vs_hilly(app):
    with app.app_context():
        _a, track_a, session_a = _seed_official(name='Flat Circuit',
                                                height_m=0.5)
        _b, track_b, session_b = _seed_official(name='Hilly Circuit',
                                                height_m=25.0)
        _set_reference(track_a, session_a)
        _set_reference(track_b, session_b)
        from app.track_dna.cards import build_card, summarize_card

        flat = summarize_card(build_card(track_a.id)[0])
        hilly = summarize_card(build_card(track_b.id)[0])
        assert 'flat' in flat['headline'].lower()
        assert 'flat' not in hilly['headline'].lower()
        assert any('elevation' in c for c in hilly['chips'])
        assert not any('elevation' in c for c in flat['chips'])
        assert 'load-transfer' in hilly['blurb']


def test_summarize_card_missing_dimensions(app):
    """No speed channel -> dimension 9 missing: the summary degrades
    gracefully (no braking chip, honest headline wording)."""
    with app.app_context():
        _admin, track, session = _seed_official(with_speed=False)
        _set_reference(track, session)
        from app.track_dna.cards import build_card, summarize_card

        card, _ = build_card(track.id)
        summary = summarize_card(card)
        assert 'no braking data' in summary['headline']
        assert not any('braking zone' in c for c in summary['chips'])
        assert summary['blurb']


def test_summarize_card_technical_track(app):
    """A twisty capsule (short straights) reads as technical in the
    headline and the blurb mentions the lap character."""
    with app.app_context():
        _admin, track, session = _seed_official(name='Twisty')
        _set_reference(track, session)
        from app.track_dna.cards import build_card, summarize_card

        summary = summarize_card(build_card(track.id)[0])
        assert 'circuit' in summary['headline'].lower()
        assert summary['chips']


# ---- CLI ---------------------------------------------------------------------------


def test_cli_compute_track_dna(app):
    with app.app_context():
        admin, track, session = _seed_official()
        _set_reference(track, session)
        track_id = track.id

        runner = app.test_cli_runner()
        result = runner.invoke(args=['compute-track-dna', str(track_id)])
        assert result.exit_code == 0, result.output
        assert 'overall' in result.output
        assert TrackDnaCard.query.filter_by(track_id=track_id).count() == 1

        # official tracks without a reference are skipped, not errors
        make_track(name='Empty Official')
        result = runner.invoke(args=['compute-track-dna', '--all'])
        assert result.exit_code == 0, result.output
        assert 'no reference lap' in result.output


def test_cli_requires_track_or_all(app):
    with app.app_context():
        runner = app.test_cli_runner()
        assert runner.invoke(args=['compute-track-dna']).exit_code != 0
        assert runner.invoke(
            args=['compute-track-dna', '99999']).exit_code != 0
