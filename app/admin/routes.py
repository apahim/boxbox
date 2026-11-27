import time

from flask import render_template, abort, current_app, flash, redirect, \
    request, url_for
from flask_login import login_required, current_user
from sqlalchemy import func

from app import db, _mapkit_token_exp
from app.admin import bp
from app.models import User, Session, Lap, Track, SessionUpload, \
    TrackDnaCard


def _require_admin():
    if not current_user.is_admin:
        abort(403)


def _dna_health():
    """Track DNA rows for the admin dashboard: one row per official
    track — the selected reference lap, the latest card, and the live
    validity verdict (a re-ingested or deleted reference shows here as
    broken; nothing recomputes automatically)."""

    from app.track_dna.reference import reference_verdict

    rows = []
    tracks = (Track.query.filter(Track.created_by.is_(None))
              .order_by(Track.name).all())
    for track in tracks:
        reference = None
        reference_ok = None
        reference_error = None
        if track.reference_session_id is not None:
            session = db.session.get(Session, track.reference_session_id)
            if session is not None:
                reference = {
                    'session_id': session.id,
                    'lap_number': track.reference_lap_number,
                    'date': (session.date.isoformat()
                             if session.date else None),
                    'device': session.data_source,
                }
                verdict = reference_verdict(track)
                reference_ok = verdict['ok']
                reference_error = verdict.get('error')
        card = (TrackDnaCard.query.filter_by(track_id=track.id)
                .order_by(TrackDnaCard.methodology_version.desc()).first())
        rows.append({'track': track, 'card': card,
                     'reference': reference,
                     'reference_ok': reference_ok,
                     'reference_error': reference_error})
    return rows


def _mapkit_token_status():
    """Return (days_left, status) for the configured MapKit JS token.

    status: 'ok', 'expiring' (< 30 days left), 'expired',
            'unknown' (not a JWT), or 'unconfigured'.
    """
    token = current_app.config.get('MAPKIT_TOKEN')
    if not token:
        return None, 'unconfigured'
    exp = _mapkit_token_exp(token)
    if exp is None:
        return None, 'unknown'
    days_left = int((exp - time.time()) // 86400)
    if days_left < 0:
        return days_left, 'expired'
    if days_left < 30:
        return days_left, 'expiring'
    return days_left, 'ok'


@bp.route('/tracks/<int:track_id>/compute-dna', methods=['POST'])
@login_required
def compute_track_dna(track_id):
    """The manual card trigger — the same scope as
    ``flask compute-track-dna TRACK_ID``. Synchronous by design
    (single-lap compute is fast). Admin + official tracks only."""
    _require_admin()
    track = db.session.get(Track, track_id)
    if track is None:
        abort(404)

    from app.track_dna.cards import build_card

    card, result = build_card(track.id)
    if card is None:
        flash(f'Track DNA — {track.name}: '
              f'{result.get("error", "failed")}', 'warning')
    else:
        flash(f'Track DNA — {track.name}: '
              f'overall {card.overall_score:.2f}/10', 'success')
    return redirect(url_for('admin.dashboard'))


@bp.route('/')
@login_required
def dashboard():
    _require_admin()

    total_users = User.query.count()
    total_sessions = Session.query.count()
    total_laps = Lap.query.count()
    total_tracks = Track.query.count()

    zero_lap_sessions = Session.query.filter(
        db.or_(Session.total_laps == 0, Session.total_laps.is_(None))
    ).count()
    single_lap_sessions = Session.query.filter(Session.total_laps == 1).count()
    all_outlier_sessions = Session.query.filter(
        Session.total_laps > 0, Session.clean_laps == 0
    ).count()
    needs_reingest_count = Session.query.filter_by(needs_reingest=True).count()
    uploads_count = SessionUpload.query.count()
    missing_uploads = total_sessions - uploads_count

    problem_sessions = (
        Session.query
        .join(User)
        .outerjoin(Track)
        .filter(db.or_(
            Session.total_laps == 0,
            Session.total_laps.is_(None),
            Session.total_laps == 1,
            db.and_(Session.total_laps > 0, Session.clean_laps == 0),
            Session.needs_reingest.is_(True),
        ))
        .order_by(Session.created_at.desc())
        .limit(50)
        .all()
    )

    track_stats = (
        db.session.query(
            Session.track_id,
            func.count(Session.id).label('session_count'),
            func.count(
                db.case(
                    (db.or_(Session.total_laps == 0, Session.total_laps.is_(None)), 1),
                )
            ).label('zero_lap_count'),
        )
        .group_by(Session.track_id)
        .all()
    )
    stats_by_track = {r.track_id: r for r in track_stats}

    tracks = Track.query.order_by(Track.name).all()
    track_health = []
    for t in tracks:
        ts = stats_by_track.get(t.id)
        track_health.append({
            'track': t,
            'session_count': ts.session_count if ts else 0,
            'zero_lap_count': ts.zero_lap_count if ts else 0,
            'corner_count': t.corners.count(),
            'has_gate': t.sf_lat1 is not None,
        })

    recent_users = (
        db.session.query(
            User,
            func.count(Session.id).label('session_count'),
        )
        .outerjoin(Session)
        .group_by(User.id)
        .order_by(User.created_at.desc())
        .limit(10)
        .all()
    )

    mapkit_days_left, mapkit_status = _mapkit_token_status()

    return render_template(
        'admin/dashboard.html',
        total_users=total_users,
        total_sessions=total_sessions,
        total_laps=total_laps,
        total_tracks=total_tracks,

        zero_lap_sessions=zero_lap_sessions,
        single_lap_sessions=single_lap_sessions,
        all_outlier_sessions=all_outlier_sessions,
        needs_reingest_count=needs_reingest_count,
        missing_uploads=missing_uploads,
        problem_sessions=problem_sessions,
        track_health=track_health,
        recent_users=recent_users,
        mapkit_days_left=mapkit_days_left,
        mapkit_status=mapkit_status,
        dna_health=_dna_health(),
    )
