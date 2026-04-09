from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, login_user, logout_user, current_user

from app import db, limiter, oauth
from app.auth import bp
from app.models import (User, Session, Track, TrackCorner, Telemetry, Lap,
                        CornerRecord, CornerSummary, SectorTime, ChartData,
                        SessionUpload, Event, EventParticipant)


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

    # Claim any pending event invitations that match this email
    EventParticipant.query.filter_by(
        email=email, user_id=None
    ).update({'user_id': user.id})
    db.session.commit()

    login_user(user)
    return redirect(url_for('index'))


@bp.route('/profile')
@login_required
def profile():
    session_count = Session.query.filter_by(user_id=current_user.id).count()
    track_count = Track.query.filter_by(created_by=current_user.id).count()
    return render_template('auth/profile.html',
                           session_count=session_count,
                           track_count=track_count)


@bp.route('/profile/delete', methods=['POST'])
@login_required
def delete_account():
    user = current_user._get_current_object()

    # Delete all session data
    sessions = Session.query.filter_by(user_id=user.id).all()
    for s in sessions:
        Telemetry.query.filter_by(session_id=s.id).delete()
        Lap.query.filter_by(session_id=s.id).delete()
        CornerRecord.query.filter_by(session_id=s.id).delete()
        CornerSummary.query.filter_by(session_id=s.id).delete()
        SectorTime.query.filter_by(session_id=s.id).delete()
        ChartData.query.filter_by(session_id=s.id).delete()
        SessionUpload.query.filter_by(session_id=s.id).delete()
        db.session.delete(s)

    # Delete events created by this user (cascade deletes participants)
    Event.query.filter_by(created_by=user.id).delete()

    # Remove this user from other events
    EventParticipant.query.filter_by(user_id=user.id).delete()

    # Delete all tracks created by user
    tracks = Track.query.filter_by(created_by=user.id).all()
    for t in tracks:
        TrackCorner.query.filter_by(track_id=t.id).delete()
        db.session.delete(t)

    db.session.delete(user)
    db.session.commit()

    logout_user()
    flash('Your account and all data have been deleted.', 'info')
    return redirect(url_for('auth.login'))


@bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
