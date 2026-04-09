import json
import re

from flask import render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func

from app import db
from app.tracks import bp
from app.tracks.forms import TrackForm
from app.models import Track, TrackCorner, Session, Telemetry, User, Event, EventParticipant, visible_tracks_for_user


def _slugify(name):
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '_', slug)
    return slug.strip('_')


@bp.route('/')
@login_required
def list_tracks():
    tracks = visible_tracks_for_user(current_user.id).all()

    # Build map of track_id → event names for events the user participates in
    event_track_map = {}
    participations = EventParticipant.query.filter(
        EventParticipant.user_id == current_user.id,
        EventParticipant.status.in_(['accepted', 'organizer']),
    ).all()
    event_ids = [p.event_id for p in participations]
    if event_ids:
        events = Event.query.filter(
            Event.id.in_(event_ids),
            Event.track_id.isnot(None),
        ).all()
        for e in events:
            event_track_map.setdefault(e.track_id, []).append(e.name)

    track_data = []
    for t in tracks:
        track_data.append({
            'track': t,
            'corner_count': t.corners.count(),
            'session_count': t.sessions.count(),
        })
    return render_template('tracks/list.html', tracks=track_data,
                           event_track_map=event_track_map)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    form = TrackForm()
    if form.validate_on_submit():
        slug = _slugify(form.name.data)
        if Track.query.filter_by(slug=slug).first():
            flash('A track with that name already exists.', 'danger')
            mapkit_token = current_app.config.get('MAPKIT_TOKEN', '')
            return render_template('tracks/create.html', form=form,
                                   mapkit_token=mapkit_token)

        lat = float(form.lat.data)
        lon = float(form.lon.data)

        # Auto-resolve timezone from coordinates
        from timezonefinder import TimezoneFinder
        tf = TimezoneFinder()
        tz = tf.timezone_at(lat=lat, lng=lon) or 'UTC'

        track = Track(
            name=form.name.data,
            slug=slug,
            lat=lat,
            lon=lon,
            timezone=tz,
            created_by=current_user.id,
        )
        db.session.add(track)
        db.session.commit()

        flash(f'Track "{track.name}" created. Add corners below.', 'success')
        return redirect(url_for('tracks.edit', slug=slug))

    mapkit_token = current_app.config.get('MAPKIT_TOKEN', '')
    return render_template('tracks/create.html', form=form,
                           mapkit_token=mapkit_token)


@bp.route('/<slug>/edit', methods=['GET', 'POST'])
@login_required
def edit(slug):
    track = Track.query.filter_by(slug=slug).first_or_404()

    is_fetch = request.headers.get('X-Requested-With') == 'fetch'
    readonly = (track.created_by != current_user.id)

    if request.method == 'POST':
        if readonly:
            if is_fetch:
                return jsonify(error='You do not have permission to edit this track.'), 403
            abort(403)

        corners_json = request.form.get('corners_json', '[]')
        try:
            corners_data = json.loads(corners_json)
        except json.JSONDecodeError:
            if is_fetch:
                return jsonify(error='Invalid corner data.'), 400
            flash('Invalid corner data.', 'danger')
            return redirect(url_for('tracks.edit', slug=slug))

        # Save start/finish gate if provided
        sf_json = request.form.get('sf_gate_json', '')
        if sf_json:
            try:
                sf = json.loads(sf_json)
                if sf:
                    track.sf_lat1 = float(sf['lat1'])
                    track.sf_lon1 = float(sf['lon1'])
                    track.sf_lat2 = float(sf['lat2'])
                    track.sf_lon2 = float(sf['lon2'])
                else:
                    track.sf_lat1 = None
                    track.sf_lon1 = None
                    track.sf_lat2 = None
                    track.sf_lon2 = None
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                pass  # keep existing gate data on malformed input
        else:
            track.sf_lat1 = None
            track.sf_lon1 = None
            track.sf_lat2 = None
            track.sf_lon2 = None

        # Delete existing corners and replace
        TrackCorner.query.filter_by(track_id=track.id).delete()

        for i, c in enumerate(corners_data):
            corner = TrackCorner(
                track_id=track.id,
                name=c.get('name', f'T{i+1}'),
                sort_order=i,
                trap_lat1=float(c['trap_lat1']),
                trap_lon1=float(c['trap_lon1']),
                trap_lat2=float(c['trap_lat2']),
                trap_lon2=float(c['trap_lon2']),
            )
            db.session.add(corner)

        # Mark all sessions for this track as needing re-ingestion
        Session.query.filter_by(track_id=track.id).update(
            {'needs_reingest': True},
        )

        db.session.commit()
        if is_fetch:
            return jsonify(ok=True)
        flash('Corners saved.', 'success')
        return redirect(url_for('tracks.edit', slug=slug))

    session_count = track.sessions.count()
    corners = TrackCorner.query.filter_by(track_id=track.id).order_by(TrackCorner.sort_order).all()
    corners_list = [
        {
            'name': c.name,
            'trap_lat1': c.trap_lat1, 'trap_lon1': c.trap_lon1,
            'trap_lat2': c.trap_lat2, 'trap_lon2': c.trap_lon2,
        }
        for c in corners
    ]

    mapkit_token = current_app.config.get('MAPKIT_TOKEN', '')

    sf_gate = None
    if track.sf_lat1 is not None:
        sf_gate = {
            'lat1': track.sf_lat1, 'lon1': track.sf_lon1,
            'lat2': track.sf_lat2, 'lon2': track.sf_lon2,
        }

    # Find unassigned sessions whose GPS data matches this track
    first_telem = db.session.query(
        Telemetry.session_id,
        func.min(Telemetry.id).label('first_id'),
    ).group_by(Telemetry.session_id).subquery()

    matching_sessions = db.session.query(Session).join(
        first_telem, Session.id == first_telem.c.session_id,
    ).join(
        Telemetry, Telemetry.id == first_telem.c.first_id,
    ).filter(
        Session.track_id.is_(None),
        Session.user_id == current_user.id,
        ((Telemetry.latitude - track.lat) * (Telemetry.latitude - track.lat)
         + (Telemetry.longitude - track.lon) * (Telemetry.longitude - track.lon)) <= 0.002,
    ).order_by(Session.date.desc()).all()

    creator_name = None
    if readonly and track.created_by:
        creator = db.session.get(User, track.created_by)
        if creator:
            creator_name = creator.display_name

    return render_template('tracks/edit.html',
                           track=track,
                           corners=corners_list,
                           corners_json=json.dumps(corners_list),
                           sf_gate_json=json.dumps(sf_gate),
                           session_count=session_count,
                           mapkit_token=mapkit_token,
                           matching_sessions=matching_sessions,
                           readonly=readonly,
                           creator_name=creator_name)


@bp.route('/<slug>/delete', methods=['POST'])
@login_required
def delete(slug):
    track = Track.query.filter_by(slug=slug).first_or_404()
    is_fetch = request.headers.get('X-Requested-With') == 'fetch'

    if track.created_by != current_user.id:
        if is_fetch:
            return jsonify(error='You do not have permission to delete this track.'), 403
        abort(403)

    session_count = track.sessions.count()

    if session_count > 0:
        msg = f'Cannot delete — track is used by {session_count} session{"s" if session_count != 1 else ""}.'
        if is_fetch:
            return jsonify(error=msg), 409
        flash(msg, 'danger')
        return redirect(url_for('tracks.list_tracks'))

    TrackCorner.query.filter_by(track_id=track.id).delete()
    db.session.delete(track)
    db.session.commit()

    if is_fetch:
        return jsonify(ok=True)
    flash('Track deleted.', 'success')
    return redirect(url_for('tracks.list_tracks'))


@bp.route('/<slug>/assign-sessions', methods=['POST'])
@login_required
def assign_sessions(slug):
    track = Track.query.filter_by(slug=slug).first_or_404()
    data = request.get_json()
    session_ids = data.get('session_ids', [])

    count = 0
    for sid in session_ids:
        s = db.session.get(Session, sid)
        if s and s.user_id == current_user.id and s.track_id is None:
            s.track_id = track.id
            s.needs_reingest = True
            count += 1

    db.session.commit()
    return jsonify(ok=True, count=count)
