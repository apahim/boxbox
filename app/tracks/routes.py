import json
import re

from flask import render_template, redirect, url_for, flash, request, current_app, jsonify, abort
from flask_login import login_required, current_user
from sqlalchemy import func

from app import db
from app.tracks import bp
from app.tracks.forms import TrackForm
from app.models import (Track, TrackDnaCard, TrackCorner, Session, Lap,
                        Telemetry, User, visible_tracks_for_user)


def _slugify(name):
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '_', slug)
    return slug.strip('_')


@bp.route('/')
@login_required
def list_tracks():
    tracks = visible_tracks_for_user(current_user.id).all()

    # Batch count queries to avoid per-track N+1
    corner_counts = dict(
        db.session.query(TrackCorner.track_id, func.count(TrackCorner.id))
        .group_by(TrackCorner.track_id)
        .all()
    )

    track_ids = [t.id for t in tracks]
    own_session_counts = {}
    all_session_counts = {}
    if track_ids:
        own_session_counts = dict(
            db.session.query(Session.track_id, func.count(Session.id))
            .filter(Session.track_id.in_(track_ids),
                    Session.user_id == current_user.id)
            .group_by(Session.track_id)
            .all()
        )
        all_session_counts = dict(
            db.session.query(Session.track_id, func.count(Session.id))
            .filter(Session.track_id.in_(track_ids))
            .group_by(Session.track_id)
            .all()
        )

    official_tracks = []
    user_tracks = []

    for t in tracks:
        if t.created_by == current_user.id or (t.created_by is None and current_user.is_admin):
            session_count = all_session_counts.get(t.id, 0)
        else:
            session_count = own_session_counts.get(t.id, 0)
        item = {
            'track': t,
            'corner_count': corner_counts.get(t.id, 0),
            'session_count': session_count,
        }
        if t.created_by is None:
            official_tracks.append(item)
        elif t.created_by == current_user.id:
            user_tracks.append(item)

    return render_template('tracks/list.html',
                           official_tracks=official_tracks,
                           user_tracks=user_tracks)


@bp.route('/<int:track_id>')
@login_required
def detail(track_id):
    track = db.session.get(Track, track_id)
    if not track:
        abort(404)

    # Same visibility as the tracks list: own tracks + official tracks
    is_official = (track.created_by is None)
    is_owner = (track.created_by == current_user.id) and not is_official
    if not is_official and not is_owner:
        abort(404)

    can_edit = is_owner or (is_official and current_user.is_admin)

    corners = TrackCorner.query.filter_by(track_id=track.id).order_by(TrackCorner.sort_order).all()
    corners_list = [
        {
            'name': c.name,
            'trap_lat1': c.trap_lat1, 'trap_lon1': c.trap_lon1,
            'trap_lat2': c.trap_lat2, 'trap_lon2': c.trap_lon2,
        }
        for c in corners
    ]

    sessions = Session.query.filter_by(
        user_id=current_user.id, track_id=track.id,
    ).order_by(Session.date.desc(), Session.id.desc()).all()

    best_lap = min((s.best_lap_time for s in sessions if s.best_lap_time), default=None)
    top_speed = max((s.top_speed_kmh for s in sessions if s.top_speed_kmh), default=None)
    total_laps = sum(s.total_laps or 0 for s in sessions)
    last_driven = sessions[0].date if sessions else None

    sf_gate = None
    if track.sf_lat1 is not None:
        sf_gate = {
            'lat1': track.sf_lat1, 'lon1': track.sf_lon1,
            'lat2': track.sf_lat2, 'lon2': track.sf_lon2,
        }

    mapkit_token = current_app.config.get('MAPKIT_TOKEN', '')

    return render_template('tracks/detail.html',
                           track=track,
                           corners=corners_list,
                           corners_json=json.dumps(corners_list),
                           sf_gate_json=json.dumps(sf_gate),
                           sessions=sessions,
                           best_lap=best_lap,
                           top_speed=top_speed,
                           total_laps=total_laps,
                           last_driven=last_driven,
                           session_count=len(sessions),
                           mapkit_token=mapkit_token,
                           can_edit=can_edit,
                           is_official=is_official)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    form = TrackForm()
    if form.validate_on_submit():
        is_official = current_user.is_admin and form.is_official.data
        owner_id = None if is_official else current_user.id

        slug = _slugify(form.name.data)
        if Track.query.filter_by(slug=slug, created_by=owner_id).first():
            flash('You already have a track with that name.', 'danger')
            mapkit_token = current_app.config.get('MAPKIT_TOKEN', '')
            return render_template('tracks/create.html', form=form,
                                   mapkit_token=mapkit_token)

        # Ensure unique slug across all users
        base_slug = slug
        counter = 2
        while Track.query.filter_by(slug=slug).first():
            slug = f'{base_slug}_{counter}'
            counter += 1

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
            created_by=owner_id,
        )
        db.session.add(track)
        db.session.commit()

        flash(f'Track "{track.name}" created. Add corners below.', 'success')
        return redirect(url_for('tracks.edit', track_id=track.id))

    mapkit_token = current_app.config.get('MAPKIT_TOKEN', '')
    return render_template('tracks/create.html', form=form,
                           mapkit_token=mapkit_token)


@bp.route('/<int:track_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(track_id):
    track = db.session.get(Track, track_id)
    if not track:
        abort(404)

    is_fetch = request.headers.get('X-Requested-With') == 'fetch'
    is_official = (track.created_by is None)
    is_owner = (track.created_by == current_user.id) and not is_official
    can_edit = is_owner or (is_official and current_user.is_admin)

    readonly = not can_edit

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
            return redirect(url_for('tracks.edit', track_id=track.id))

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
        return redirect(url_for('tracks.edit', track_id=track.id))

    if can_edit:
        session_count = track.sessions.count()
    else:
        session_count = track.sessions.filter_by(user_id=current_user.id).count()
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
    if readonly and not can_edit and not is_official:
        if track.created_by:
            creator = db.session.get(User, track.created_by)
            if creator:
                creator_name = creator.display_name

    # Track DNA (reference-lap): admin picker context. Official tracks
    # only — personal tracks render the section disabled.
    dna = {'official': is_official, 'is_admin': current_user.is_admin,
           'reference': None, 'reference_ok': None,
           'reference_error': None, 'card': None}
    if is_official:
        if track.reference_session_id is not None:
            ref_session = db.session.get(Session, track.reference_session_id)
            if ref_session is not None:
                ref_lap = Lap.query.filter_by(
                    session_id=ref_session.id,
                    lap_number=track.reference_lap_number).first()
                dna['reference'] = {
                    'session_id': ref_session.id,
                    'lap_number': track.reference_lap_number,
                    'date': (ref_session.date.isoformat()
                             if ref_session.date else None),
                    'device': ref_session.data_source,
                    'lap_time_s': (round(ref_lap.seconds, 3)
                                   if ref_lap else None),
                }
                from app.track_dna.reference import reference_verdict
                verdict = reference_verdict(track)
                dna['reference_ok'] = verdict['ok']
                dna['reference_error'] = verdict.get('error')
        card = (TrackDnaCard.query.filter_by(track_id=track.id)
                .order_by(TrackDnaCard.methodology_version.desc()).first())
        if card is not None:
            dna['card'] = {
                'overall_score': card.overall_score,
                'computed_at': (card.computed_at.isoformat()
                                if card.computed_at else None),
                'methodology_version': card.methodology_version,
            }
    dna_sessions = []
    if is_official and current_user.is_admin:
        for sess in (Session.query.filter_by(track_id=track.id)
                     .order_by(Session.date.desc(), Session.id.desc())
                     .all()):
            dna_sessions.append({
                'id': sess.id,
                'date': (sess.date.isoformat() if sess.date else None),
                'device': sess.data_source,
                'total_laps': sess.total_laps,
                'best_lap_time': sess.best_lap_time,
            })

    return render_template('tracks/edit.html',
                           track=track,
                           corners=corners_list,
                           corners_json=json.dumps(corners_list),
                           sf_gate_json=json.dumps(sf_gate),
                           session_count=session_count,
                           mapkit_token=mapkit_token,
                           matching_sessions=matching_sessions,
                           readonly=readonly,
                           is_owner=is_owner,
                           is_official=is_official,
                           can_edit=can_edit,
                           creator_name=creator_name,
                           dna=dna,
                           dna_sessions=dna_sessions)


@bp.route('/<int:track_id>/delete', methods=['POST'])
@login_required
def delete(track_id):
    track = db.session.get(Track, track_id)
    if not track:
        abort(404)
    is_fetch = request.headers.get('X-Requested-With') == 'fetch'

    is_official = (track.created_by is None)
    can_delete = (track.created_by == current_user.id and not is_official) or \
                 (is_official and current_user.is_admin)
    if not can_delete:
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


@bp.route('/<int:track_id>/assign-sessions', methods=['POST'])
@login_required
def assign_sessions(track_id):
    track = db.session.get(Track, track_id)
    if not track:
        abort(404)
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


# ---- Track DNA reference lap (admin, official tracks) ----
#
# Track DNA is admin-only and official-tracks-only: the card is a
# statement about a track in the public catalog, computed from the
# lap the admin selects.


def _official_track_or_404(track_id):
    track = db.session.get(Track, track_id)
    if not track:
        abort(404)
    if track.created_by is not None:
        abort(404)          # DNA exists on official tracks only
    return track


def _require_admin():
    if not current_user.is_admin:
        abort(403)


@bp.route('/<int:track_id>/reference-lap/laps')
@login_required
def reference_lap_laps(track_id):
    """Clean laps of one session on the track, for the admin picker."""
    _require_admin()
    track = _official_track_or_404(track_id)

    session_id = request.args.get('session_id', type=int)
    if session_id is None:
        return jsonify(error='session_id is required.'), 400
    session = db.session.get(Session, session_id)
    if session is None or session.track_id != track.id:
        return jsonify(error='Session not found on this track.'), 404

    laps = (Lap.query.filter_by(session_id=session.id, is_outlier=False)
            .order_by(Lap.lap_number).all())
    best = min((lap.seconds for lap in laps), default=None)
    return jsonify(laps=[{
        'lap': lap.lap_number,
        'seconds': round(lap.seconds, 3),
        'is_best': best is not None and lap.seconds == best,
    } for lap in laps])


@bp.route('/<int:track_id>/reference-lap', methods=['POST'])
@login_required
def set_reference_lap(track_id):
    """Set the track's DNA reference lap and compute its card.

    The lap is validated with the engine before anything is persisted:
    an unusable lap is rejected with its reason, never stored.
    """
    _require_admin()
    track = _official_track_or_404(track_id)

    from app.track_dna.cards import build_card
    from app.track_dna.reference import load_reference

    data = request.get_json(silent=True) or {}
    session_id = data.get('session_id')
    lap_number = data.get('lap_number')
    if not isinstance(session_id, int) or not isinstance(lap_number, int) \
            or lap_number < 1:
        return jsonify(error='session_id and lap_number are required.'), 400

    session = db.session.get(Session, session_id)
    if session is None or session.track_id != track.id:
        return jsonify(error='Session not found on this track.'), 404

    # Validate before committing: run the engine with the prospective
    # reference in place, then persist only when the lap is usable.
    track.reference_session_id = session.id
    track.reference_lap_number = lap_number
    ref = load_reference(track)
    if not ref['ok']:
        db.session.rollback()
        return jsonify(error=ref['error']), 400
    db.session.commit()

    card, result = build_card(track.id)
    if card is None:
        return jsonify(error=result.get('error', 'compute failed')), 500
    return jsonify(ok=True,
                   overall_score=card.overall_score,
                   lap_time_s=(card.dataset_json or {}).get('lap_time_s'))


@bp.route('/<int:track_id>/make-official', methods=['POST'])
@login_required
def make_official(track_id):
    """Make a personal track official (visible to all users). Admin only."""
    if not current_user.is_admin:
        abort(403)

    track = db.session.get(Track, track_id)
    if not track:
        abort(404)

    if track.created_by is not None:
        track.created_by = None
        db.session.commit()
        flash(f'Track "{track.name}" is now official.', 'success')

    return redirect(url_for('tracks.edit', track_id=track.id))


@bp.route('/<int:track_id>/make-personal', methods=['POST'])
@login_required
def make_personal(track_id):
    """Revert an official track to personal, managed by the acting admin."""
    if not current_user.is_admin:
        abort(403)

    track = db.session.get(Track, track_id)
    if not track:
        abort(404)

    if track.created_by is None:
        other_sessions = Session.query.filter(
            Session.track_id == track.id,
            Session.user_id != current_user.id,
        ).count()
        if other_sessions > 0:
            msg = (f'Cannot make personal — {other_sessions} session'
                   f'{"s" if other_sessions != 1 else ""} from other users '
                   f'{"are" if other_sessions != 1 else "is"} on this track.')
            if request.headers.get('X-Requested-With') == 'fetch':
                return jsonify(error=msg), 409
            flash(msg, 'danger')
            return redirect(url_for('tracks.edit', track_id=track.id))

        track.created_by = current_user.id
        db.session.commit()
        flash(f'Track "{track.name}" is now personal (managed by you).', 'success')

    return redirect(url_for('tracks.edit', track_id=track.id))
