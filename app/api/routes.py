from functools import wraps

from flask import jsonify, request
from flask_login import current_user

from app import db
from app.api import bp
from app.models import Session, ChartData, Track, Lap


def api_login_required(f):
    """Require authentication and session access for API endpoints."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify(error='Authentication required'), 401

        session_id = kwargs.get('session_id')
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
