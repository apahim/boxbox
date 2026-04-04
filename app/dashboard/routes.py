from flask import render_template, abort, current_app
from flask_login import login_required, current_user

from app import db
from app.dashboard import bp
from app.models import Session


@bp.route('/<int:session_id>')
@login_required
def view(session_id):
    session = db.session.get(Session, session_id)
    if not session:
        abort(404)

    if session.user_id != current_user.id:
        abort(403)

    mapkit_token = current_app.config.get('MAPKIT_TOKEN', '')
    return render_template('dashboard/view.html', session=session, mapkit_token=mapkit_token)
