from datetime import datetime, timezone

from flask import render_template, redirect, url_for
from flask_login import login_required, current_user

from app import db
from app.legal import bp


@bp.route('/terms')
def terms():
    return render_template('legal/terms.html')


@bp.route('/privacy')
def privacy():
    return render_template('legal/privacy.html')


@bp.route('/terms/accept', methods=['GET', 'POST'])
@login_required
def accept_terms():
    from flask import request
    if request.method == 'POST':
        current_user.terms_accepted_at = datetime.now(timezone.utc)
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('legal/accept.html')
