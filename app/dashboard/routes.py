from flask import render_template, abort, flash, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_

from app import db
from app.dashboard import bp
from app.models import Session, TeamMember


@bp.route('/<int:session_id>')
@login_required
def view(session_id):
    session = db.session.get(Session, session_id)
    if not session:
        abort(404)

    # Check access: own session or team member
    if session.user_id != current_user.id:
        if not session.team_id:
            abort(403)
        is_member = TeamMember.query.filter_by(
            team_id=session.team_id, user_id=current_user.id
        ).first()
        if not is_member:
            abort(403)

    mapkit_token = current_app.config.get('MAPKIT_TOKEN', '')
    return render_template('dashboard/view.html', session=session, mapkit_token=mapkit_token)
