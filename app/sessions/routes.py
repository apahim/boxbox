import os
import tempfile

from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from sqlalchemy import or_

from app import db
from app.sessions import bp
from app.sessions.forms import SessionCreateForm, SessionEditForm
from app.models import Session, Track, TrackCorner, Team, TeamMember


@bp.route('/')
@login_required
def list_sessions():
    # User's own sessions + sessions visible via team membership
    team_ids = [
        m.team_id for m in
        TeamMember.query.filter_by(user_id=current_user.id).all()
    ]

    query = Session.query.filter(
        or_(
            Session.user_id == current_user.id,
            Session.team_id.in_(team_ids) if team_ids else False,
        )
    ).order_by(Session.date.desc())

    sessions = query.all()
    return render_template('sessions/list.html', sessions=sessions)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    form = SessionCreateForm()

    # Populate track choices
    tracks = Track.query.order_by(Track.name).all()
    form.track_id.choices = [(t.id, t.name) for t in tracks]

    # Populate team choices (user's teams + "None")
    memberships = TeamMember.query.filter_by(user_id=current_user.id).all()
    team_ids = [m.team_id for m in memberships]
    teams = Team.query.filter(Team.id.in_(team_ids)).all() if team_ids else []
    form.team_id.choices = [(0, '— No team —')] + [(t.id, t.name) for t in teams]

    if form.validate_on_submit():
        session_date = form.date.data

        # Save CSV to temp file
        csv_file = form.csv_file.data
        temp_fd, temp_path = tempfile.mkstemp(suffix='.csv')
        try:
            csv_file.save(temp_path)

            # Create session record
            track = Track.query.get(form.track_id.data)
            team_id = form.team_id.data if form.team_id.data != 0 else None

            session = Session(
                user_id=current_user.id,
                track_id=track.id,
                team_id=team_id,
                date=session_date,
                session_type=form.session_type.data or None,
                session_start=form.session_start.data.strftime('%H:%M') if form.session_start.data else None,
                kart_number=form.kart_number.data,
                driver_weight_kg=form.driver_weight_kg.data,
            )
            db.session.add(session)
            db.session.flush()  # Get session.id

            # Get track corners
            corners = TrackCorner.query.filter_by(track_id=track.id).order_by(TrackCorner.sort_order).all()
            track_corners = [
                {
                    'name': c.name, 'lat': c.lat, 'lon': c.lon,
                    'trap_lat1': c.trap_lat1, 'trap_lon1': c.trap_lon1,
                    'trap_lat2': c.trap_lat2, 'trap_lon2': c.trap_lon2,
                }
                for c in corners
            ] if corners else None
            track_coords = (track.lat, track.lon, track.timezone) if track else None

            # Run ingest pipeline
            from app.sessions.ingest import ingest_session
            ingest_session(temp_path, session, track_coords, track_corners)

            flash(f'Session uploaded successfully. {session.total_laps} laps processed.', 'success')
            return redirect(url_for('sessions.list_sessions'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error processing CSV: {e}', 'danger')
            return render_template('sessions/create.html', form=form)
        finally:
            os.close(temp_fd)
            os.unlink(temp_path)

    return render_template('sessions/create.html', form=form)


@bp.route('/<int:session_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(session_id):
    session = Session.query.get_or_404(session_id)

    if session.user_id != current_user.id:
        flash('You can only edit your own sessions.', 'danger')
        return redirect(url_for('sessions.list_sessions'))

    form = SessionEditForm(obj=session)

    # Populate choices
    tracks = Track.query.order_by(Track.name).all()
    form.track_id.choices = [(t.id, t.name) for t in tracks]

    memberships = TeamMember.query.filter_by(user_id=current_user.id).all()
    team_ids = [m.team_id for m in memberships]
    teams = Team.query.filter(Team.id.in_(team_ids)).all() if team_ids else []
    form.team_id.choices = [(0, '— No team —')] + [(t.id, t.name) for t in teams]

    if request.method == 'GET':
        form.date.data = session.date
        form.team_id.data = session.team_id or 0
        if session.session_start:
            from datetime import time as time_type
            parts = session.session_start.split(':')
            form.session_start.data = time_type(int(parts[0]), int(parts[1]))

    if form.validate_on_submit():
        session.date = form.date.data
        session.track_id = form.track_id.data
        session.team_id = form.team_id.data if form.team_id.data != 0 else None
        session.kart_number = form.kart_number.data
        session.driver_weight_kg = form.driver_weight_kg.data
        session.session_type = form.session_type.data or None
        session.session_start = form.session_start.data.strftime('%H:%M') if form.session_start.data else None

        db.session.commit()
        flash('Session updated.', 'success')
        return redirect(url_for('sessions.list_sessions'))

    return render_template('sessions/edit.html', form=form, session=session)


@bp.route('/<int:session_id>/delete', methods=['POST'])
@login_required
def delete(session_id):
    session = Session.query.get_or_404(session_id)

    if session.user_id != current_user.id:
        flash('You can only delete your own sessions.', 'danger')
        return redirect(url_for('sessions.list_sessions'))

    db.session.delete(session)
    db.session.commit()
    flash('Session deleted.', 'success')
    return redirect(url_for('sessions.list_sessions'))
