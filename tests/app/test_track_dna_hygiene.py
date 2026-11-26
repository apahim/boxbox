"""Tests for Track DNA data-hygiene rules and inventory (plan Phase 1)."""

import json
from datetime import date

from app import db
from app.models import Session, Telemetry, Track, User
from app.track_dna.hygiene import (
    DEMO_LABEL,
    DURATION_RANGE,
    LENGTH_RANGE,
    MIN_SAMPLES,
    classify_track_sessions,
    dataset_verdict,
    duplicate_signature,
    find_duplicates,
    is_demo_session,
    is_wet_session,
    normalize_labels,
    provisional_valid_laps,
)


def make_user(email='driver@test.com'):
    user = User(email=email, display_name=email.split('@')[0])
    db.session.add(user)
    db.session.flush()
    return user


def make_track(name='Test Circuit'):
    track = Track(slug=name.lower().replace(' ', '_'), name=name,
                  lat=52.0, lon=-7.0)
    db.session.add(track)
    db.session.flush()
    return track


def make_session(track, user, date_=date(2026, 1, 1), labels=None,
                 best_lap_time=None, data_source='racechrono'):
    session = Session(
        user_id=user.id,
        track_id=track.id,
        date=date_,
        labels=labels,
        best_lap_time=best_lap_time,
        data_source=data_source,
    )
    db.session.add(session)
    db.session.flush()
    return session


def add_lap(session, lap_number, samples, duration, length):
    """Seed one lap's telemetry with the given sample count/duration/length."""
    for i in range(samples):
        frac = i / max(samples - 1, 1)
        db.session.add(Telemetry(
            session_id=session.id,
            lap_number=lap_number,
            elapsed_time=duration * frac,
            distance_traveled=length * frac,
        ))
    db.session.flush()


def add_valid_lap(session, lap_number):
    """Seed one lap that passes the provisional validity rule."""
    add_lap(session, lap_number, 150, 60.0, 1000.0)


class TestLabelRules:
    def test_normalize_labels_handles_none_case_and_whitespace(self):
        assert normalize_labels(None) == []
        assert normalize_labels([]) == []
        assert normalize_labels([' Demo ', 'WET']) == ['demo', 'wet']

    def test_demo_detection(self):
        assert is_demo_session(Session(labels=['Demo']))
        assert is_demo_session(Session(labels=['demo']))
        assert is_demo_session(Session(labels=[' DEMO ']))
        assert not is_demo_session(Session(labels=['Demolition']))
        assert not is_demo_session(Session(labels=['Demo data']))
        assert not is_demo_session(Session(labels=None))

    def test_wet_detection(self):
        assert is_wet_session(Session(labels=['Wet']))
        assert is_wet_session(Session(labels=['wet', 'Adult']))
        assert not is_wet_session(Session(labels=['Dry']))
        assert not is_wet_session(Session(labels=['wet-weather']))
        assert not is_wet_session(Session(labels=None))


class TestDuplicateDetection:
    def test_signature_components(self):
        session = Session(user_id=1, date=date(2026, 1, 2),
                          best_lap_time=61.23456)
        assert duplicate_signature(session, 1234) == \
            (1, date(2026, 1, 2), 1234, 61.235)

    def test_signature_with_no_best_lap(self):
        session = Session(user_id=1, date=date(2026, 1, 2), best_lap_time=None)
        assert duplicate_signature(session, 0) == (1, date(2026, 1, 2), 0, None)

    def test_identical_signature_excludes_later_session(self, db_session):
        track = make_track()
        user = make_user()
        s1 = make_session(track, user, best_lap_time=61.234)
        s2 = make_session(track, user, best_lap_time=61.234)
        add_lap(s1, 1, 150, 60.0, 1000.0)
        add_lap(s2, 1, 150, 60.0, 1000.0)
        db.session.commit()

        ds = classify_track_sessions(track.id)
        assert [v.session_id for v in ds.included] == [s1.id]
        assert len(ds.excluded) == 1
        excluded = ds.excluded[0]
        assert excluded.session_id == s2.id
        assert excluded.exclusion_reason == 'duplicate'
        assert excluded.duplicate_of == s1.id

    def test_best_lap_rounded_to_milliseconds_in_signature(self, db_session):
        track = make_track()
        user = make_user()
        s1 = make_session(track, user, best_lap_time=61.2341)
        s2 = make_session(track, user, best_lap_time=61.2344)
        add_lap(s1, 1, 150, 60.0, 1000.0)
        add_lap(s2, 1, 150, 60.0, 1000.0)
        db.session.commit()

        # Sub-millisecond differences round away: same signature.
        ds = classify_track_sessions(track.id)
        assert [v.session_id for v in ds.included] == [s1.id]
        assert ds.excluded[0].session_id == s2.id
        assert ds.excluded[0].exclusion_reason == 'duplicate'
        assert ds.excluded[0].duplicate_of == s1.id

    def test_different_row_count_not_duplicate(self, db_session):
        track = make_track()
        user = make_user()
        s1 = make_session(track, user, best_lap_time=61.2)
        s2 = make_session(track, user, best_lap_time=61.2)
        add_lap(s1, 1, 150, 60.0, 1000.0)
        add_lap(s2, 1, 160, 60.0, 1000.0)
        db.session.commit()

        ds = classify_track_sessions(track.id)
        assert [v.session_id for v in ds.included] == [s1.id, s2.id]

    def test_different_best_lap_not_duplicate(self, db_session):
        track = make_track()
        user = make_user()
        s1 = make_session(track, user, best_lap_time=61.2)
        s2 = make_session(track, user, best_lap_time=61.9)
        add_lap(s1, 1, 150, 60.0, 1000.0)
        add_lap(s2, 1, 150, 60.0, 1000.0)
        db.session.commit()

        ds = classify_track_sessions(track.id)
        assert [v.session_id for v in ds.included] == [s1.id, s2.id]

    def test_different_date_not_duplicate(self, db_session):
        track = make_track()
        user = make_user()
        s1 = make_session(track, user, date_=date(2026, 1, 1),
                          best_lap_time=61.2)
        s2 = make_session(track, user, date_=date(2026, 1, 2),
                          best_lap_time=61.2)
        add_lap(s1, 1, 150, 60.0, 1000.0)
        add_lap(s2, 1, 150, 60.0, 1000.0)
        db.session.commit()

        ds = classify_track_sessions(track.id)
        assert [v.session_id for v in ds.included] == [s1.id, s2.id]

    def test_different_user_not_duplicate(self, db_session):
        track = make_track()
        u1 = make_user('a@test.com')
        u2 = make_user('b@test.com')
        s1 = make_session(track, u1, best_lap_time=61.2)
        s2 = make_session(track, u2, best_lap_time=61.2)
        add_lap(s1, 1, 150, 60.0, 1000.0)
        add_lap(s2, 1, 150, 60.0, 1000.0)
        db.session.commit()

        ds = classify_track_sessions(track.id)
        assert [v.session_id for v in ds.included] == [s1.id, s2.id]

    def test_three_way_group_keeps_lowest_id(self, db_session):
        track = make_track()
        user = make_user()
        s1 = make_session(track, user, best_lap_time=61.2)
        s2 = make_session(track, user, best_lap_time=61.2)
        s3 = make_session(track, user, best_lap_time=61.2)
        for s in (s1, s2, s3):
            add_lap(s, 1, 150, 60.0, 1000.0)
        db.session.commit()

        ds = classify_track_sessions(track.id)
        assert [v.session_id for v in ds.included] == [s1.id]
        for v in ds.excluded:
            assert v.exclusion_reason == 'duplicate'
            assert v.duplicate_of == s1.id

    def test_find_duplicates_ignores_demo_sessions(self, db_session):
        track = make_track()
        user = make_user()
        s1 = make_session(track, user, best_lap_time=61.2)
        s2 = make_session(track, user, best_lap_time=61.2)
        db.session.flush()

        # Demo sessions are filtered out before duplicate grouping.
        demo = make_session(track, user, labels=['Demo'])
        dupes = find_duplicates([s1, s2, demo], {s1.id: 10, s2.id: 10,
                                                 demo.id: 10})
        assert dupes == {s2.id: s1.id}


class TestPrecedenceAndConditions:
    def test_demo_beats_duplicate_and_wet(self, db_session):
        track = make_track()
        user = make_user()
        s1 = make_session(track, user, labels=['Wet'], best_lap_time=61.2)
        # Duplicate of s1, but also demo-labelled and wet-labelled.
        s2 = make_session(track, user, labels=['Demo', 'Wet'],
                          best_lap_time=61.2)
        add_valid_lap(s1, 1)
        add_valid_lap(s2, 1)
        db.session.commit()

        ds = classify_track_sessions(track.id)
        assert [v.session_id for v in ds.included] == [s1.id]
        assert [v.session_id for v in ds.sessions_for('wet')] == [s1.id]

        excluded = ds.excluded[0]
        assert excluded.session_id == s2.id
        assert excluded.exclusion_reason == 'demo_label'
        assert excluded.duplicate_of is None
        assert excluded.condition is None

    def test_condition_split(self, db_session):
        track = make_track()
        user = make_user()
        s1 = make_session(track, user, date_=date(2026, 1, 1), labels=['Wet'])
        s2 = make_session(track, user, date_=date(2026, 1, 2), labels=None)
        s3 = make_session(track, user, date_=date(2026, 1, 3),
                          labels=['Adult'])
        add_valid_lap(s1, 1)
        add_valid_lap(s2, 1)
        add_valid_lap(s3, 1)
        db.session.commit()

        ds = classify_track_sessions(track.id)
        conditions = {v.session_id: v.condition for v in ds.included}
        assert conditions == {s1.id: 'wet', s2.id: 'dry', s3.id: 'dry'}
        assert [v.session_id for v in ds.sessions_for('wet')] == [s1.id]
        assert [v.session_id for v in ds.sessions_for('dry')] == [s2.id, s3.id]


class TestProvisionalLaps:
    def test_all_valid_laps_counted(self):
        stats = [(150, 60.0, 1000.0)] * 3
        assert provisional_valid_laps(stats) == 3

    def test_empty_stats(self):
        assert provisional_valid_laps([]) == 0

    def test_invalid_laps_filtered(self):
        # Median duration = 60, median length = 1000 (robust to the rejects).
        stats = [
            (150, 60.0, 1000.0),    # valid
            (50, 60.0, 1000.0),     # too few samples
            (150, 20.0, 1000.0),    # duration below 0.65x median
            (150, 120.0, 1000.0),   # duration above 1.5x median
            (150, 60.0, 200.0),     # length below 0.85x median
            (150, 60.0, 2500.0),    # length above 1.15x median
            (2, 0.0, 1.0),          # boundary-row artifact
        ]
        assert provisional_valid_laps(stats) == 1

    def test_bounds_are_inclusive(self):
        median_duration, median_length = 60.0, 1000.0
        stats = [
            (MIN_SAMPLES,
             DURATION_RANGE[0] * median_duration,
             LENGTH_RANGE[0] * median_length),
            (MIN_SAMPLES,
             DURATION_RANGE[1] * median_duration,
             LENGTH_RANGE[1] * median_length),
            (MIN_SAMPLES, median_duration, median_length),
        ]
        assert provisional_valid_laps(stats) == 3

    def test_classify_counts_provisional_laps(self, db_session):
        track = make_track()
        user = make_user()
        s1 = make_session(track, user)
        add_lap(s1, 0, 5, 0.0, 3.0)         # lap 0 boundary row: ignored
        add_valid_lap(s1, 1)                 # valid
        add_lap(s1, 2, 150, 61.0, 990.0)    # valid
        add_lap(s1, 3, 40, 60.0, 1000.0)    # too few samples
        add_lap(s1, 4, 150, 200.0, 1000.0)  # duration above 1.5x median
        add_lap(s1, 5, 2, 0.0, 1.0)         # artifact
        db.session.commit()

        ds = classify_track_sessions(track.id)
        assert len(ds.verdicts) == 1
        assert ds.verdicts[0].provisional_laps == 2
        assert ds.provisional_laps() == 2
        assert ds.provisional_laps('dry') == 2
        assert ds.provisional_laps('wet') == 0

    def test_session_without_telemetry_has_no_valid_laps(self, db_session):
        track = make_track()
        user = make_user()
        make_session(track, user)
        db.session.commit()

        ds = classify_track_sessions(track.id)
        assert len(ds.included) == 1
        assert ds.provisional_laps() == 0


class TestDatasetVerdict:
    def test_strong(self):
        assert dataset_verdict(3, 373) == ('strong', None)
        assert dataset_verdict(2, 20) == ('strong', None)

    def test_moderate(self):
        assert dataset_verdict(2, 15) == ('moderate', '10-19 laps')

    def test_weak_single_user(self):
        assert dataset_verdict(1, 36) == ('weak', 'single user')

    def test_weak_few_laps(self):
        assert dataset_verdict(2, 5) == ('weak', 'fewer than 10 laps')

    def test_unavailable(self):
        assert dataset_verdict(0, 0) == ('unavailable', 'no clean sessions')
        assert dataset_verdict(1, 0) == ('unavailable', 'no valid laps')


class TestTrackDataset:
    def test_unknown_track(self, db_session):
        assert classify_track_sessions(99999) is None

    def test_track_without_sessions(self, db_session):
        track = make_track('Empty Circuit')
        db.session.commit()

        ds = classify_track_sessions(track.id)
        assert ds.verdicts == []
        assert ds.verdict == ('unavailable', 'no clean sessions')
        assert ds.provisional_laps() == 0
        assert ds.user_counts == {}
        assert ds.date_range is None
        assert ds.devices == []
        assert ds.session_fingerprint == []

    def test_aggregations(self, db_session):
        track = make_track()
        u1 = make_user('a@test.com')
        u2 = make_user('b@test.com')
        s1 = make_session(track, u1, date(2026, 1, 5), data_source='gopro',
                          best_lap_time=60.0)
        s2 = make_session(track, u1, date(2026, 2, 10),
                          data_source='racechrono', best_lap_time=61.0)
        s3 = make_session(track, u2, date(2026, 3, 15), labels=['Wet'],
                          data_source='racechrono', best_lap_time=62.0)
        s4 = make_session(track, u1, labels=['Demo'], best_lap_time=60.0)
        add_valid_lap(s1, 1)
        add_valid_lap(s1, 2)
        add_valid_lap(s2, 1)
        add_valid_lap(s3, 1)
        db.session.commit()

        ds = classify_track_sessions(track.id)
        assert ds.user_counts == {u1.id: 2, u2.id: 1}
        assert ds.date_range == (date(2026, 1, 5), date(2026, 3, 15))
        assert ds.devices == ['gopro', 'racechrono']
        assert ds.session_fingerprint == sorted([s1.id, s2.id, s3.id])
        assert ds.provisional_laps() == 4
        assert ds.provisional_laps('dry') == 3
        assert ds.provisional_laps('wet') == 1
        # 2 users, 4 laps -> weak (fewer than 10 laps)
        assert ds.verdict == ('weak', 'fewer than 10 laps')

    def test_deterministic(self, db_session):
        track = make_track()
        user = make_user()
        s1 = make_session(track, user, labels=['Wet'], best_lap_time=61.2)
        s2 = make_session(track, user, best_lap_time=61.2)  # duplicate of s1
        s3 = make_session(track, user, labels=['Demo'])
        add_valid_lap(s1, 1)
        add_valid_lap(s2, 1)
        db.session.commit()

        ds1 = classify_track_sessions(track.id)
        ds2 = classify_track_sessions(track.id)
        assert ds1.verdicts == ds2.verdicts
        assert ds1.to_dict() == ds2.to_dict()

    def test_to_dict_shape(self, db_session):
        track = make_track()
        user = make_user()
        s1 = make_session(track, user, labels=['Wet'], data_source='gopro')
        s2 = make_session(track, user, labels=['Demo'])
        add_valid_lap(s1, 1)
        db.session.commit()

        data = classify_track_sessions(track.id).to_dict()
        assert data['track_id'] == track.id
        assert data['track_name'] == 'Test Circuit'
        assert data['sessions'] == {'total': 2, 'clean': 1, 'dry': 0, 'wet': 1}
        assert data['excluded'] == [
            {'session_id': s2.id, 'reason': 'demo_label', 'duplicate_of': None}
        ]
        assert data['wet_session_ids'] == [s1.id]
        assert data['provisional_laps'] == {'total': 1, 'dry': 0, 'wet': 1}
        assert data['devices'] == ['gopro']
        assert data['date_range'] == ['2026-01-01', '2026-01-01']
        assert data['session_fingerprint'] == [s1.id]
        assert len(data['session_verdicts']) == 2
        assert data['verdict'] == 'weak'


class TestDnaInventoryCli:
    def _seed(self):
        track = make_track()
        user = make_user()
        s1 = make_session(track, user, best_lap_time=61.2)
        s2 = make_session(track, user, labels=['Demo'])
        s3 = make_session(track, user, best_lap_time=61.2)  # duplicate of s1
        add_valid_lap(s1, 1)
        add_valid_lap(s2, 1)
        add_valid_lap(s3, 1)
        db.session.commit()
        return track, s1, s2, s3

    def test_human_output(self, app):
        track, s1, s2, s3 = self._seed()
        runner = app.test_cli_runner()
        result = runner.invoke(args=['dna-inventory'])

        assert result.exit_code == 0
        assert 'Test Circuit' in result.output
        assert '1 clean (1 dry, 0 wet)' in result.output
        assert 'demo (1)' in result.output and str(s2.id) in result.output
        assert f'duplicate (1): {s3.id} (of {s1.id})' in result.output
        assert 'provisional laps: 1' in result.output

    def test_json_output(self, app):
        self._seed()
        runner = app.test_cli_runner()
        result = runner.invoke(args=['dna-inventory', '--json'])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]['track_name'] == 'Test Circuit'
        assert data[0]['sessions']['clean'] == 1
        assert data[0]['provisional_laps']['total'] == 1

    def test_single_track_argument(self, app):
        track, _, _, _ = self._seed()
        make_track('Other Circuit')
        db.session.commit()

        runner = app.test_cli_runner()
        result = runner.invoke(args=['dna-inventory', str(track.id)])

        assert result.exit_code == 0
        assert 'Test Circuit' in result.output
        assert 'Other Circuit' not in result.output

    def test_unknown_track_argument(self, app):
        runner = app.test_cli_runner()
        result = runner.invoke(args=['dna-inventory', '99999'])

        assert result.exit_code == 1
        assert 'not found' in result.output
