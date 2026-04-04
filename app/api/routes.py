from functools import wraps

from flask import jsonify, request
from flask_login import current_user

from sqlalchemy import or_

from app import db
from app.api import bp
from app.models import (
    Session, ChartData, TeamMember, Track, CornerSummary, Telemetry, Lap,
)


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

            # Check access: own session or team member
            if session.user_id != current_user.id:
                if not session.team_id:
                    return jsonify(error='Access denied'), 403
                is_member = TeamMember.query.filter_by(
                    team_id=session.team_id, user_id=current_user.id
                ).first()
                if not is_member:
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
        session_type=session.session_type,
        kart_number=session.kart_number,
        driver_weight_kg=session.driver_weight_kg,
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


# ---- Evolution endpoints (cross-session) ----

def _user_sessions_query():
    """Return a query for sessions visible to the current user."""
    team_ids = [
        m.team_id for m in
        TeamMember.query.filter_by(user_id=current_user.id).all()
    ]
    return Session.query.filter(
        or_(
            Session.user_id == current_user.id,
            Session.team_id.in_(team_ids) if team_ids else False,
        )
    )


@bp.route('/evolution')
def evolution_trends():
    """Lap time trends across sessions for a track."""
    if not current_user.is_authenticated:
        return jsonify(error='Authentication required'), 401

    track_id = request.args.get('track_id', type=int)
    query = _user_sessions_query()
    if track_id:
        query = query.filter(Session.track_id == track_id)
    sessions = query.order_by(Session.date).all()

    data = []
    for s in sessions:
        data.append({
            'id': s.id,
            'date': str(s.date),
            'track': s.track.name if s.track else None,
            'track_id': s.track_id,
            'session_type': s.session_type,
            'best_lap_time': s.best_lap_time,
            'average_time': s.average_time,
            'median_time': s.median_time,
            'consistency_pct': s.consistency_pct,
            'total_laps': s.total_laps,
            'clean_laps': s.clean_laps,
            'top_speed_kmh': s.top_speed_kmh,
            'weather': s.weather,
        })
    return jsonify(data)


@bp.route('/evolution/corners')
def evolution_corners():
    """Corner improvement across sessions for a track."""
    if not current_user.is_authenticated:
        return jsonify(error='Authentication required'), 401

    track_id = request.args.get('track_id', type=int)
    if not track_id:
        return jsonify(error='track_id required'), 400

    sessions = _user_sessions_query().filter(
        Session.track_id == track_id
    ).order_by(Session.date).all()

    session_ids = [s.id for s in sessions]
    if not session_ids:
        return jsonify([])

    summaries = CornerSummary.query.filter(
        CornerSummary.session_id.in_(session_ids)
    ).order_by(CornerSummary.corner_index).all()

    # Group by corner, ordered by session date
    session_dates = {s.id: str(s.date) for s in sessions}
    corners = {}
    for cs in summaries:
        name = cs.corner_name
        if name not in corners:
            corners[name] = {
                'corner_name': name,
                'corner_index': cs.corner_index,
                'sessions': [],
            }
        corners[name]['sessions'].append({
            'session_id': cs.session_id,
            'date': session_dates.get(cs.session_id),
            'avg_time_loss': cs.avg_time_loss,
            'avg_min_speed': cs.avg_min_speed,
            'best_min_speed': cs.best_min_speed,
            'braking_spread': cs.braking_spread,
            'dominant_root_cause': cs.dominant_root_cause,
        })

    # Sort corners by index, sessions within each corner by date
    result = sorted(corners.values(), key=lambda c: c['corner_index'])
    for c in result:
        c['sessions'].sort(key=lambda s: s['date'])

    return jsonify(result)


@bp.route('/evolution/raceline')
def evolution_raceline():
    """Cross-session racing line comparison.

    Query params:
        session_ids: comma-separated session IDs
        laps: comma-separated lap numbers (one per session)
    """
    if not current_user.is_authenticated:
        return jsonify(error='Authentication required'), 401

    session_ids_str = request.args.get('session_ids', '')
    laps_str = request.args.get('laps', '')

    if not session_ids_str:
        return jsonify(error='session_ids required'), 400

    session_ids = [int(x) for x in session_ids_str.split(',') if x.strip()]
    lap_numbers = [int(x) for x in laps_str.split(',') if x.strip()] if laps_str else []

    sessions = []
    for i, sid in enumerate(session_ids):
        session = db.session.get(Session, sid)
        if not session:
            continue
        # Check access
        if session.user_id != current_user.id:
            if not session.team_id:
                continue
            is_member = TeamMember.query.filter_by(
                team_id=session.team_id, user_id=current_user.id
            ).first()
            if not is_member:
                continue

        # Get raceline data from ChartData
        cd = ChartData.query.filter_by(
            session_id=sid,
            chart_type='raceline',
            chart_key='overview',
        ).first()
        if not cd or not cd.data or 'laps' not in cd.data:
            continue

        # Filter to requested lap if specified
        all_laps = cd.data['laps']
        if i < len(lap_numbers):
            target_lap = lap_numbers[i]
            all_laps = [l for l in all_laps if l['lap'] == target_lap]

        sessions.append({
            'session_id': sid,
            'date': str(session.date),
            'session_type': session.session_type,
            'is_current': i == 0,
            'laps': all_laps,
        })

    return jsonify({'sessions': sessions})


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
