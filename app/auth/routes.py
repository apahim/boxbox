from flask import render_template, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user

from app import db, limiter, oauth
from app.auth import bp
from app.models import User


@bp.route('/login')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    return render_template('auth/login.html')


@bp.route('/login/google')
def login_google():
    redirect_uri = url_for('auth.callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@bp.route('/callback')
@limiter.limit("10/minute")
def callback():
    token = oauth.google.authorize_access_token()
    user_info = token.get('userinfo')

    if not user_info:
        flash('Failed to get user info from Google.', 'danger')
        return redirect(url_for('auth.login'))

    google_id = user_info['sub']
    email = user_info['email'].lower()
    name = user_info.get('name', email)

    # Find by google_id (returning user) or by email (migration path)
    user = User.query.filter_by(google_id=google_id).first()
    if not user:
        user = User.query.filter_by(email=email).first()
        if user:
            user.google_id = google_id
        else:
            user = User(email=email, display_name=name, google_id=google_id)
            db.session.add(user)
        db.session.commit()

    login_user(user)
    return redirect(url_for('index'))


@bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
