import time

from flask import render_template, abort, current_app, flash, redirect, \
    request, url_for
from flask_login import login_required, current_user
from sqlalchemy import func

from app import db, _mapkit_token_exp
from app.admin import bp
from app.models import User, Session, Lap, Track, SessionUpload, \
    TrackConfig, TrackDnaScorecard


def _require_admin():
    if not current_user.is_admin:
        abort(403)


def _dna_health():
    """Track DNA rows for the admin dashboard (plan 21.4): one row per
    (track, config) — tracks without configurations don't appear — with
    the latest card per condition (overall score, quality summary,
    computed date) and the staleness verdict from fingerprint drift
    (display-only: nothing recomputes automatically, D7 revised)."""

    from app.track_dna.scorecards import current_fingerprint

    rows = []
    configs = (TrackConfig.query.join(Track)
               .order_by(Track.name, TrackConfig.id).all())
    for config in configs:
        conditions = []
        cards = TrackDnaScorecard.query.filter_by(
            track_config_id=config.id).all()
        by_condition = {}
        for card in cards:
            best = by_condition.get(card.condition)
            if best is None or card.methodology_version > \
                    best.methodology_version:
                by_condition[card.condition] = card
        for condition in ('dry', 'wet'):
            card = by_condition.get(condition)
            if card is None:
                conditions.append({'condition': condition, 'card': None})
                continue
            counts = {}
            for dim in card.dimensions_json:
                quality = dim.get('quality')
                counts[quality] = counts.get(quality, 0) + 1
            stored = (card.dataset_json or {}).get('session_fingerprint')
            conditions.append({
                'condition': condition,
                'card': card,
                'quality_counts': counts,
                'stale': (stored is not None
                          and stored != current_fingerprint(
                              config.id, condition)),
            })
        rows.append({'track': config.track, 'config': config,
                     'conditions': conditions})
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
    """Phase 9 (plan 21.4): the manual scorecard trigger — every
    configuration x both conditions for one track, the same scope as
    ``flask compute-track-dna TRACK_ID``. Synchronous by design
    (gunicorn timeout 600 s; measured prod worst case ~19 s). D7
    revised: this and the CLI are the only callers of the builder."""
    _require_admin()
    track = db.session.get(Track, track_id)
    if track is None:
        abort(404)

    from app.track_dna.scorecards import CONDITIONS, build_scorecard

    configs = track.configs.order_by(TrackConfig.id).all()
    if not configs:
        flash(f'Track "{track.name}" has no configurations — create one '
              f'on its detail page first.', 'warning')
        return redirect(url_for('admin.dashboard'))

    summary = []
    for config in configs:
        for condition in CONDITIONS:
            card, result = build_scorecard(config.id, condition)
            if card is None:
                summary.append(f'{config.name} {condition}: '
                               f'{result.get("error", "failed")}')
            else:
                summary.append(f'{config.name} {condition}: '
                               f'{card.overall_score:.2f}')
    flash('Track DNA — ' + track.name + ': ' + '; '.join(summary),
          'success')
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
