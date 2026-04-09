from flask import render_template, abort, current_app
from flask_login import login_required, current_user

from app import db
from app.dashboard import bp
from app.models import Session, TrackCorner, EventParticipant


@bp.route('/<int:session_id>')
@login_required
def view(session_id):
    session = db.session.get(Session, session_id)
    if not session:
        abort(404)

    if session.user_id != current_user.id:
        # Check event-scoped access: both users must be accepted participants
        # of the same event where the target session is linked
        from sqlalchemy import and_
        has_access = db.session.query(EventParticipant).filter(
            EventParticipant.event_id.in_(
                db.session.query(EventParticipant.event_id).filter(
                    EventParticipant.session_id == session.id,
                    EventParticipant.status.in_(['accepted', 'organizer']),
                )
            ),
            EventParticipant.user_id == current_user.id,
            EventParticipant.status.in_(['accepted', 'organizer']),
        ).first()
        if not has_access:
            abort(403)

    has_corners = False
    has_gate = False
    if session.track:
        has_corners = TrackCorner.query.filter_by(track_id=session.track_id).first() is not None
        has_gate = session.track.sf_lat1 is not None

    mapkit_token = current_app.config.get('MAPKIT_TOKEN', '')
    return render_template('dashboard/view.html', session=session, mapkit_token=mapkit_token,
                           shared=False, has_corners=has_corners, has_gate=has_gate)


@bp.route('/share/<token>')
def shared_view(token):
    session = Session.query.filter_by(share_token=token).first_or_404()

    if session.is_share_token_expired():
        return render_template('errors/share_expired.html'), 410

    has_corners = False
    has_gate = False
    if session.track:
        has_corners = TrackCorner.query.filter_by(track_id=session.track_id).first() is not None
        has_gate = session.track.sf_lat1 is not None

    mapkit_token = current_app.config.get('MAPKIT_TOKEN', '')
    return render_template('dashboard/view.html', session=session, mapkit_token=mapkit_token,
                           shared=True, has_corners=has_corners, has_gate=has_gate)
