"""Track DNA data hygiene: deterministic session exclusion rules and inventory.

Phase 1 of the Track DNA implementation plan. Determines which sessions are
included in Track DNA computation for a track:

1. Demo-labelled sessions are excluded (decision D1).
2. Exact-duplicate sessions — same user, date, telemetry row count and best
   lap time — are excluded, keeping the lowest session id (decision D1).
3. Included sessions are split by condition: a 'Wet' label buckets the
   session as 'wet', everything else as 'dry' (Section 4 of the plan).

The ``user.demo_seeded`` flag is deliberately not used: it is unreliable as
an exclusion filter (the owner's account has it set).

This module also computes a provisional per-session lap-validity count that
approximates the plan's Section 4.1 lap filters using DB-computable
quantities only (sample counts, elapsed-time span, distance_traveled span).
It stands in for the canonical resampler-based count that lands with the
Phase 3 geometry engine; the two are reconciled in Phase 3's golden-file
regression.
"""

import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func

from app import db
from app.models import Session, Telemetry, Track

# Labels are matched case-insensitively after stripping whitespace.
DEMO_LABEL = 'demo'
WET_LABEL = 'wet'

# Provisional lap-validity parameters (Section 4.1 approximation).
MIN_SAMPLES = 100
DURATION_RANGE = (0.65, 1.5)
LENGTH_RANGE = (0.85, 1.15)


@dataclass(frozen=True)
class SessionVerdict:
    """Exclusion decision and stats for a single session."""

    session_id: int
    user_id: int
    date: date
    data_source: str | None
    telemetry_rows: int
    best_lap_time: float | None
    condition: str | None          # 'dry' | 'wet'; None when excluded
    included: bool
    exclusion_reason: str | None   # 'demo_label' | 'duplicate' | None
    duplicate_of: int | None
    provisional_laps: int


@dataclass
class TrackDataset:
    """Hygiene classification of every session assigned to a track."""

    track_id: int
    track_name: str
    verdicts: list[SessionVerdict]   # ordered by session_id

    @property
    def included(self):
        return [v for v in self.verdicts if v.included]

    @property
    def excluded(self):
        return [v for v in self.verdicts if not v.included]

    def sessions_for(self, condition):
        return [v for v in self.included if v.condition == condition]

    @property
    def user_counts(self):
        counts = Counter(v.user_id for v in self.included)
        return dict(sorted(counts.items()))

    @property
    def date_range(self):
        dates = [v.date for v in self.included]
        if not dates:
            return None
        return (min(dates), max(dates))

    @property
    def devices(self):
        return sorted({v.data_source for v in self.included if v.data_source})

    @property
    def session_fingerprint(self):
        """Sorted ids of included sessions — the dataset identity."""
        return sorted(v.session_id for v in self.included)

    def provisional_laps(self, condition=None):
        return sum(v.provisional_laps for v in self.included
                   if condition is None or v.condition == condition)

    @property
    def verdict(self):
        """(verdict, reason) for the dataset; see dataset_verdict()."""
        return dataset_verdict(len(self.user_counts), self.provisional_laps())

    def to_dict(self):
        """JSON-serialisable summary (feeds Phase 7's dataset_json)."""
        verdict, reason = self.verdict
        date_range = self.date_range
        return {
            'track_id': self.track_id,
            'track_name': self.track_name,
            'verdict': verdict,
            'verdict_reason': reason,
            'users': self.user_counts,
            'sessions': {
                'total': len(self.verdicts),
                'clean': len(self.included),
                'dry': len(self.sessions_for('dry')),
                'wet': len(self.sessions_for('wet')),
            },
            'excluded': [
                {
                    'session_id': v.session_id,
                    'reason': v.exclusion_reason,
                    'duplicate_of': v.duplicate_of,
                }
                for v in self.excluded
            ],
            'wet_session_ids': [v.session_id for v in self.sessions_for('wet')],
            'provisional_laps': {
                'total': self.provisional_laps(),
                'dry': self.provisional_laps('dry'),
                'wet': self.provisional_laps('wet'),
            },
            'devices': self.devices,
            'date_range': ([d.isoformat() for d in date_range]
                           if date_range else None),
            'session_fingerprint': self.session_fingerprint,
            'session_verdicts': [
                {
                    'session_id': v.session_id,
                    'user_id': v.user_id,
                    'date': v.date.isoformat(),
                    'condition': v.condition,
                    'included': v.included,
                    'exclusion_reason': v.exclusion_reason,
                    'duplicate_of': v.duplicate_of,
                    'data_source': v.data_source,
                    'telemetry_rows': v.telemetry_rows,
                    'provisional_laps': v.provisional_laps,
                }
                for v in self.verdicts
            ],
        }


def normalize_labels(labels):
    """Normalise a session's label list for comparison (None-safe)."""
    return [str(label).strip().lower() for label in (labels or [])]


def is_demo_session(session):
    return DEMO_LABEL in normalize_labels(session.labels)


def is_wet_session(session):
    return WET_LABEL in normalize_labels(session.labels)


def duplicate_signature(session, telemetry_rows):
    """Signature identifying exact-duplicate imports of the same session."""
    best = session.best_lap_time
    best = round(best, 3) if best is not None else None
    return (session.user_id, session.date, telemetry_rows, best)


def find_duplicates(sessions, telemetry_rows):
    """Map duplicate session ids to the canonical (lowest-id) session.

    ``sessions`` must be ordered by id. Sessions sharing a duplicate
    signature are exact-duplicate imports; all but the first are excluded
    (decision D1).
    """
    groups = {}
    for session in sessions:
        key = duplicate_signature(session, telemetry_rows.get(session.id, 0))
        groups.setdefault(key, []).append(session)

    duplicates = {}
    for group in groups.values():
        if len(group) > 1:
            canonical = group[0].id
            for session in group[1:]:
                duplicates[session.id] = canonical
    return duplicates


def provisional_valid_laps(lap_stats):
    """Count laps passing the provisional validity rule.

    ``lap_stats`` is a list of ``(samples, duration, length)`` tuples for a
    session's numbered laps (lap_number >= 1), where duration is the
    elapsed-time span and length the distance_traveled span of the lap.

    A lap is valid when it has at least MIN_SAMPLES samples, a duration
    within DURATION_RANGE of the session median, and a length within
    LENGTH_RANGE of the session median.
    """
    if not lap_stats:
        return 0
    median_duration = statistics.median(d for _, d, _ in lap_stats)
    median_length = statistics.median(l for _, _, l in lap_stats)
    lo_d, hi_d = DURATION_RANGE
    lo_l, hi_l = LENGTH_RANGE
    return sum(
        1 for samples, duration, length in lap_stats
        if samples >= MIN_SAMPLES
        and lo_d * median_duration <= duration <= hi_d * median_duration
        and lo_l * median_length <= length <= hi_l * median_length
    )


def dataset_verdict(n_users, n_laps):
    """Classify a clean dataset's support for Track DNA.

    Based on the plan's Section 11 minimum-data guidance: geometry works
    from ~10 laps (20 preferred) and cross-user confidence needs >=2 users;
    single-user circuits are flagged as estimates in Phase 8.

    Returns a ``(verdict, reason)`` tuple where verdict is one of
    'unavailable', 'weak', 'moderate' or 'strong'.
    """
    if n_users == 0:
        return ('unavailable', 'no clean sessions')
    if n_laps == 0:
        return ('unavailable', 'no valid laps')
    if n_users < 2:
        return ('weak', 'single user')
    if n_laps < 10:
        return ('weak', 'fewer than 10 laps')
    if n_laps < 20:
        return ('moderate', '10-19 laps')
    return ('strong', None)


def classify_track_sessions(track_id):
    """Classify all sessions assigned to a track for Track DNA computation.

    Returns a TrackDataset, or None when the track does not exist.
    """
    track = db.session.get(Track, track_id)
    if track is None:
        return None

    sessions = (Session.query.filter_by(track_id=track_id)
                .order_by(Session.id).all())

    telemetry_rows = {}
    lap_stats = {}
    session_ids = [s.id for s in sessions]
    if session_ids:
        telemetry_rows = dict(
            db.session.query(Telemetry.session_id, func.count(Telemetry.id))
            .filter(Telemetry.session_id.in_(session_ids))
            .group_by(Telemetry.session_id)
            .all()
        )
        rows = (
            db.session.query(
                Telemetry.session_id,
                func.count(Telemetry.id),
                func.min(Telemetry.elapsed_time),
                func.max(Telemetry.elapsed_time),
                func.min(Telemetry.distance_traveled),
                func.max(Telemetry.distance_traveled),
            )
            .filter(Telemetry.session_id.in_(session_ids),
                    Telemetry.lap_number >= 1)
            .group_by(Telemetry.session_id, Telemetry.lap_number)
            .all()
        )
        for sid, samples, t_min, t_max, d_min, d_max in rows:
            duration = (t_max - t_min
                        if t_min is not None and t_max is not None else 0.0)
            length = (d_max - d_min
                      if d_min is not None and d_max is not None else 0.0)
            lap_stats.setdefault(sid, []).append((samples, duration, length))

    duplicates = find_duplicates(
        [s for s in sessions if not is_demo_session(s)], telemetry_rows)

    verdicts = []
    for session in sessions:
        included = True
        reason = None
        duplicate_of = None
        condition = None
        if is_demo_session(session):
            included, reason = False, 'demo_label'
        elif session.id in duplicates:
            included, reason = False, 'duplicate'
            duplicate_of = duplicates[session.id]
        else:
            condition = 'wet' if is_wet_session(session) else 'dry'

        verdicts.append(SessionVerdict(
            session_id=session.id,
            user_id=session.user_id,
            date=session.date,
            data_source=session.data_source,
            telemetry_rows=telemetry_rows.get(session.id, 0),
            best_lap_time=session.best_lap_time,
            condition=condition,
            included=included,
            exclusion_reason=reason,
            duplicate_of=duplicate_of,
            provisional_laps=provisional_valid_laps(
                lap_stats.get(session.id, [])),
        ))

    return TrackDataset(
        track_id=track.id,
        track_name=track.name,
        verdicts=verdicts,
    )
