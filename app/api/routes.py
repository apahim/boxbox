from functools import wraps

from flask import jsonify, request
from flask_login import current_user

from app import db
from app.api import bp
from app.models import (
    Session, ChartData, Track, Telemetry, Lap, User,
    Leaderboard, LeaderboardShare, visible_tracks_for_user,
    format_driver_name, format_laptime,
)


def api_login_required(f):
    """Require authentication and session access for API endpoints.

    Supports share_token query parameter as an alternative to login,
    scoped to the specific session ID in the URL.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        session_id = kwargs.get('session_id')

        # Share token grants read-only access to a specific session
        if session_id:
            share_token = request.args.get('share_token')
            if share_token:
                session = Session.query.filter_by(
                    id=session_id, share_token=share_token
                ).first()
                if session:
                    if session.is_share_token_expired():
                        return jsonify(error='Share link has expired'), 401
                    kwargs['session'] = session
                    return f(*args, **kwargs)

        if not current_user.is_authenticated:
            return jsonify(error='Authentication required'), 401

        if session_id:
            session = db.session.get(Session, session_id)
            if not session:
                return jsonify(error='Session not found'), 404

            if session.user_id != current_user.id:
                return jsonify(error='Access denied'), 403

            kwargs['session'] = session

        return f(*args, **kwargs)
    return decorated


@bp.route('/sessions/<int:session_id>/summary')
@api_login_required
def session_summary(session_id, session):
    """Return session summary data."""
    excluded_laps = Lap.query.filter_by(
        session_id=session.id, is_outlier=True
    ).order_by(Lap.lap_number).all()

    return jsonify(
        id=session.id,
        date=str(session.date),
        track=session.track.name if session.track else None,
        labels=session.labels or [],
        total_laps=session.total_laps,
        clean_laps=session.clean_laps,
        best_lap_time=session.best_lap_time,
        average_time=session.average_time,
        median_time=session.median_time,
        std_dev=session.std_dev,
        consistency_pct=session.consistency_pct,
        top_speed_kmh=session.top_speed_kmh,
        max_lateral_g=session.max_lateral_g,
        max_braking_g=session.max_braking_g,
        max_accel_g=session.max_accel_g,
        weather=session.weather,
        coaching=session.coaching,
        excluded_laps=[
            {'lap': l.lap_number, 'seconds': l.seconds, 'reason': l.outlier_reason}
            for l in excluded_laps
        ],
        data_source=session.data_source,
        video_filename=session.video_filename,
        video_hash=session.video_hash,
    )


@bp.route('/sessions/<int:session_id>/charts/<chart_type>')
@api_login_required
def session_chart(session_id, session, chart_type):
    """Return an overview chart (stored in ChartData with key 'overview')."""
    cd = ChartData.query.filter_by(
        session_id=session_id,
        chart_type=chart_type,
        chart_key='overview',
    ).first()
    if not cd:
        return jsonify(error='Chart not found'), 404
    return jsonify(cd.data)


@bp.route('/sessions/<int:session_id>/charts/<chart_type>/<lap>')
@api_login_required
def session_chart_lap(session_id, session, chart_type, lap):
    """Return a per-lap chart."""
    cd = ChartData.query.filter_by(
        session_id=session_id,
        chart_type=chart_type,
        chart_key=str(lap),
    ).first()
    if not cd:
        return jsonify(error='Chart not found'), 404
    return jsonify(cd.data)


@bp.route('/sessions/<int:session_id>/laps')
@api_login_required
def session_laps(session_id, session):
    """Return the lap list."""
    cd = ChartData.query.filter_by(
        session_id=session_id,
        chart_type='lap_list',
        chart_key='overview',
    ).first()
    if not cd:
        return jsonify([])
    return jsonify(cd.data)


@bp.route('/sessions/<int:session_id>/corners')
@api_login_required
def session_corners(session_id, session):
    """Return corner analysis data."""
    cd = ChartData.query.filter_by(
        session_id=session_id,
        chart_type='corner_analysis',
        chart_key='overview',
    ).first()
    if not cd:
        return jsonify(error='No corner analysis'), 404
    return jsonify(cd.data)


@bp.route('/sessions/<int:session_id>/corners/map')
@api_login_required
def session_corner_map(session_id, session):
    """Return corner map data."""
    cd = ChartData.query.filter_by(
        session_id=session_id,
        chart_type='corner_map',
        chart_key='overview',
    ).first()
    if not cd:
        return jsonify(error='No corner map'), 404
    return jsonify(cd.data)


@bp.route('/sessions/<int:session_id>/sectors')
@api_login_required
def session_sectors(session_id, session):
    """Return sector data."""
    cd = ChartData.query.filter_by(
        session_id=session_id,
        chart_type='sector_table',
        chart_key='overview',
    ).first()
    if not cd:
        return jsonify(error='No sector data'), 404
    return jsonify(cd.data)


@bp.route('/sessions/<int:session_id>/video-filename', methods=['PUT'])
@api_login_required
def session_video_filename(session_id, session):
    """Save the local video filename for this session."""
    data = request.get_json(silent=True)
    if not data or 'filename' not in data:
        return jsonify(error='filename required'), 400
    session.video_filename = data['filename'] or None
    db.session.commit()
    return jsonify(ok=True)


@bp.route('/sessions/<int:session_id>/raceline')
@api_login_required
def session_raceline(session_id, session):
    """Return raceline data."""
    cd = ChartData.query.filter_by(
        session_id=session_id,
        chart_type='raceline',
        chart_key='overview',
    ).first()
    if not cd:
        return jsonify(error='No raceline data'), 404
    return jsonify(cd.data)


# ---- Utility queries ----

def _user_sessions_query():
    """Return a query for sessions visible to the current user."""
    return Session.query.filter_by(user_id=current_user.id)


@bp.route('/sessions/<int:session_id>/detect-track')
def detect_track(session_id):
    """Detect the best matching track from a session's first GPS coordinate."""
    if not current_user.is_authenticated:
        return jsonify(error='Authentication required'), 401

    session = db.session.get(Session, session_id)
    if not session or session.user_id != current_user.id:
        return jsonify(error='Not found'), 404

    first = Telemetry.query.filter_by(session_id=session_id).order_by(Telemetry.id).first()
    if not first or not first.latitude or not first.longitude:
        return jsonify(track_id=None)

    tracks = visible_tracks_for_user(current_user.id).all()
    best = None
    best_dist = float('inf')
    for t in tracks:
        d = (t.lat - first.latitude) ** 2 + (t.lon - first.longitude) ** 2
        if d < best_dist:
            best_dist = d
            best = t

    if best and best_dist <= 0.002:
        return jsonify(track_id=best.id, track_name=best.name)
    return jsonify(track_id=None)


@bp.route('/tracks/<int:track_id>/sessions')
def track_sessions(track_id):
    """Return the current user's sessions at a given track."""
    if not current_user.is_authenticated:
        return jsonify(error='Authentication required'), 401

    sessions = Session.query.filter_by(
        user_id=current_user.id, track_id=track_id
    ).order_by(Session.date.desc()).all()

    return jsonify([
        {'id': s.id, 'date': str(s.date), 'labels': s.labels or []}
        for s in sessions
    ])


@bp.route('/sessions/raceline')
def sessions_raceline():
    """Batch-fetch raceline chart data for multiple sessions."""
    if not current_user.is_authenticated:
        return jsonify(error='Authentication required'), 401

    ids_str = request.args.get('session_ids', '')
    if not ids_str:
        return jsonify(sessions=[])

    try:
        session_ids = [int(x) for x in ids_str.split(',')]
    except ValueError:
        return jsonify(error='Invalid session_ids'), 400

    sessions = Session.query.filter(
        Session.id.in_(session_ids),
        Session.user_id == current_user.id
    ).order_by(Session.date.desc()).all()

    result = []
    for s in sessions:
        cd = ChartData.query.filter_by(
            session_id=s.id, chart_type='raceline', chart_key='overview'
        ).first()
        if not cd or not cd.data:
            continue
        result.append({
            'session_id': s.id,
            'date': str(s.date),
            'labels': s.labels or [],
            'laps': cd.data.get('laps', []),
        })

    return jsonify(sessions=result)


@bp.route('/tracks/<int:track_id>/gate')
def track_gate(track_id):
    """Return start/finish gate coordinates for a track."""
    if not current_user.is_authenticated:
        return jsonify(error='Authentication required'), 401

    track = db.session.get(Track, track_id)
    if not track:
        return jsonify(error='Track not found'), 404

    if track.sf_lat1 is None:
        return jsonify(error='No start/finish gate configured'), 404

    return jsonify(
        sf_lat1=track.sf_lat1, sf_lon1=track.sf_lon1,
        sf_lat2=track.sf_lat2, sf_lon2=track.sf_lon2,
    )


@bp.route('/labels')
def api_labels():
    """Return distinct labels used across the current user's sessions."""
    if not current_user.is_authenticated:
        return jsonify(error='Authentication required'), 401

    sessions = _user_sessions_query().all()
    all_labels = set()
    for s in sessions:
        if s.labels:
            for label in s.labels:
                all_labels.add(label)
    return jsonify(sorted(all_labels))


@bp.route('/tracks')
def api_tracks():
    """Return list of tracks the user has sessions at."""
    if not current_user.is_authenticated:
        return jsonify(error='Authentication required'), 401

    sessions = _user_sessions_query().all()
    track_ids = set(s.track_id for s in sessions)
    tracks = Track.query.filter(Track.id.in_(track_ids)).order_by(Track.name).all()

    return jsonify([
        {'id': t.id, 'name': t.name, 'slug': t.slug}
        for t in tracks
    ])


# ── Leaderboard results ──

@bp.route('/leaderboard/<int:lb_id>/results')
def leaderboard_results(lb_id):
    """Compute and return leaderboard results."""
    if not current_user.is_authenticated:
        return jsonify(error='Authentication required'), 401

    lb = db.session.get(Leaderboard, lb_id)
    if not lb:
        return jsonify(error='Not found'), 404

    # Access check
    if lb.visibility == 'official':
        pass
    elif lb.created_by == current_user.id:
        pass
    elif lb.visibility == 'shared':
        if not LeaderboardShare.query.filter_by(
            leaderboard_id=lb.id, user_id=current_user.id
        ).first():
            return jsonify(error='Access denied'), 403
    else:
        return jsonify(error='Access denied'), 403

    results = _compute_leaderboard(lb, current_user.id)

    period_labels = {
        'last_30': 'Last 30 days',
        'last_90': 'Last 90 days',
        'this_year': 'This year',
        'all_time': 'All time',
    }
    if lb.period_type == 'custom' and lb.period_start and lb.period_end:
        plabel = f"{lb.period_start.strftime('%-d %b %Y')} – {lb.period_end.strftime('%-d %b %Y')}"
    else:
        plabel = period_labels.get(lb.period_type, lb.period_type)

    return jsonify(
        results=results,
        track_name=lb.track.name if lb.track else None,
        period_label=plabel,
    )


def _compute_leaderboard(lb, current_user_id):
    from datetime import date, timedelta
    from sqlalchemy import func

    today = date.today()
    if lb.period_type == 'last_30':
        start_date = today - timedelta(days=30)
        end_date = today
    elif lb.period_type == 'last_90':
        start_date = today - timedelta(days=90)
        end_date = today
    elif lb.period_type == 'this_year':
        start_date = date(today.year, 1, 1)
        end_date = today
    elif lb.period_type == 'custom':
        start_date = lb.period_start
        end_date = lb.period_end
    else:
        start_date = None
        end_date = None

    # Build base session filter
    session_query = Session.query.filter(
        Session.track_id == lb.track_id,
        Session.best_lap_time.isnot(None),
    )
    if start_date:
        session_query = session_query.filter(Session.date >= start_date)
    if end_date:
        session_query = session_query.filter(Session.date <= end_date)

    sessions = session_query.all()

    # Filter by labels in Python (SQLite compatible)
    required_labels = set(lb.labels or [])
    best_per_user = {}
    for s in sessions:
        if 'Demo' in (s.labels or []):
            continue
        if required_labels:
            session_labels = set(s.labels or [])
            if not required_labels.issubset(session_labels):
                continue
        uid = s.user_id
        if uid not in best_per_user or s.best_lap_time < best_per_user[uid][0]:
            best_per_user[uid] = (s.best_lap_time, s.date, s.data_source, s.labels)

    sorted_results = sorted(best_per_user.items(), key=lambda x: x[1][0])
    sorted_results = sorted_results[:lb.max_drivers]

    if not sorted_results:
        return []

    user_ids = [r[0] for r in sorted_results]
    users = {u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()}

    leader_time = sorted_results[0][1][0]
    results = []
    for i, (user_id, (best_time, lap_date, data_source, labels)) in enumerate(sorted_results):
        user = users.get(user_id)
        if not user:
            continue
        gap = best_time - leader_time
        results.append({
            'position': i + 1,
            'name': format_driver_name(user, current_user_id),
            'best_time': best_time,
            'best_time_fmt': format_laptime(best_time),
            'gap': round(gap, 3),
            'gap_fmt': f'+{gap:.3f}' if i > 0 else '',
            'is_self': user_id == current_user_id,
            'lap_date': lap_date.isoformat() if lap_date else None,
            'lap_date_fmt': lap_date.strftime('%-d %b %Y') if lap_date else '',
            'source': data_source or '',
            'labels': labels or [],
        })

    return results
