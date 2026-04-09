import logging
import re
from datetime import datetime, timezone

from flask import render_template, redirect, url_for, flash, request, jsonify, abort
from flask_login import login_required, current_user

from app import db
from app.events import bp
from app.events.forms import EventForm
from app.models import (
    Event, EventParticipant, Track, TrackCorner, Session, User,
    CornerSummary, SectorTime, visible_tracks_for_user,
)

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _is_fetch():
    return request.headers.get('X-Requested-With') == 'fetch'


def _require_participant(event, status_filter=None):
    """Return the current user's EventParticipant for this event, or abort."""
    q = EventParticipant.query.filter_by(
        event_id=event.id, user_id=current_user.id
    )
    if status_filter:
        q = q.filter(EventParticipant.status.in_(status_filter))
    p = q.first()
    if not p:
        abort(403)
    return p


def _require_organizer(event):
    """Abort 403 if current user is not the event organizer."""
    if event.created_by != current_user.id:
        abort(403)


def _format_laptime(seconds):
    """Format seconds as M:SS.mmm."""
    if seconds is None:
        return '—'
    mins = int(seconds // 60)
    secs = seconds % 60
    return f'{mins}:{secs:06.3f}'


# ── List ──

@bp.route('/')
@login_required
def list_events():
    # Pending invitations
    pending = EventParticipant.query.filter_by(
        user_id=current_user.id, status='pending'
    ).all()
    pending_events = []
    for p in pending:
        pending_events.append({
            'participant': p,
            'event': p.event,
            'organizer': p.event.creator,
        })

    # Events the user is part of (accepted or organizer)
    participations = EventParticipant.query.filter(
        EventParticipant.user_id == current_user.id,
        EventParticipant.status.in_(['accepted', 'organizer']),
    ).all()
    event_ids = [p.event_id for p in participations]

    # Also include events created by user (organizer is always a participant)
    created_ids = [e.id for e in Event.query.filter_by(created_by=current_user.id).all()]
    all_ids = list(set(event_ids + created_ids))

    events = Event.query.filter(Event.id.in_(all_ids)).order_by(
        Event.date.desc()
    ).all() if all_ids else []

    # Compute accepted count per event
    accepted_counts = {}
    for e in events:
        accepted_counts[e.id] = EventParticipant.query.filter(
            EventParticipant.event_id == e.id,
            EventParticipant.status.in_(['accepted', 'organizer']),
        ).count()

    return render_template('events/list.html',
                           pending_events=pending_events,
                           events=events,
                           accepted_counts=accepted_counts)


# ── Create ──

@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    form = EventForm()
    tracks = visible_tracks_for_user(current_user.id).all()
    form.track_id.choices = [(0, '— No track —')] + [(t.id, t.name) for t in tracks]

    if form.validate_on_submit():
        event = Event(
            name=form.name.data,
            date=form.date.data,
            time=form.time.data.strftime('%H:%M') if form.time.data else None,
            track_id=form.track_id.data,
            description=form.description.data or None,
            created_by=current_user.id,
        )
        db.session.add(event)
        db.session.flush()

        # Add creator as organizer participant
        organizer = EventParticipant(
            event_id=event.id,
            email=current_user.email,
            user_id=current_user.id,
            role='organizer',
            status='accepted',
            responded_at=datetime.now(timezone.utc),
        )
        db.session.add(organizer)
        db.session.commit()

        flash(f'Event "{event.name}" created. Invite participants below.', 'success')
        return redirect(url_for('events.view', event_id=event.id))

    return render_template('events/create.html', form=form)


# ── View / Dashboard ──

@bp.route('/<int:event_id>')
@login_required
def view(event_id):
    event = db.session.get(Event, event_id)
    if not event:
        abort(404)

    participant = EventParticipant.query.filter_by(
        event_id=event.id, user_id=current_user.id
    ).first()
    if not participant:
        abort(403)

    is_organizer = event.created_by == current_user.id

    # All participants
    participants = EventParticipant.query.filter_by(
        event_id=event.id
    ).order_by(
        EventParticipant.role.desc(),  # organizer first
        EventParticipant.status,
        EventParticipant.invited_at,
    ).all()

    # Build leaderboard from participants with linked sessions
    ranked = []
    unranked = []
    for p in participants:
        if p.session_id and p.session:
            display_name = p.user.display_name if p.user else p.email
            ranked.append({
                'participant': p,
                'name': display_name,
                'session': p.session,
                'best_lap': p.session.best_lap_time,
                'best_lap_fmt': _format_laptime(p.session.best_lap_time),
                'clean_laps': p.session.clean_laps,
                'total_laps': p.session.total_laps,
                'consistency': p.session.consistency_pct,
            })
        else:
            display_name = p.user.display_name if p.user else p.email
            unranked.append({
                'participant': p,
                'name': display_name,
            })

    # Sort by best lap time
    ranked.sort(key=lambda x: x['best_lap'] if x['best_lap'] is not None else float('inf'))

    # Compute gaps
    leader_time = ranked[0]['best_lap'] if ranked else None
    for i, entry in enumerate(ranked):
        entry['position'] = i + 1
        if leader_time and entry['best_lap']:
            entry['gap'] = entry['best_lap'] - leader_time
        else:
            entry['gap'] = None

    # Recap data (for completed events)
    recap = None
    if event.status == 'completed' and len(ranked) >= 2:
        recap = _build_recap(ranked)

    # Corner leaderboard data
    corner_leaders = None
    sector_leaders = None
    if event.track_id and len(ranked) >= 2:
        corner_leaders = _build_corner_leaderboard(event, ranked)
        sector_leaders = _build_sector_leaderboard(event, ranked)

    # Track info for display
    track_corner_names = []
    track_has_sf_gate = False
    if event.track:
        corners = TrackCorner.query.filter_by(
            track_id=event.track_id
        ).order_by(TrackCorner.sort_order).all()
        track_corner_names = [c.name for c in corners]
        track_has_sf_gate = event.track.sf_lat1 is not None

    return render_template('events/view.html',
                           event=event,
                           participant=participant,
                           is_organizer=is_organizer,
                           participants=participants,
                           ranked=ranked,
                           unranked=unranked,
                           recap=recap,
                           corner_leaders=corner_leaders,
                           sector_leaders=sector_leaders,
                           track_corner_names=track_corner_names,
                           track_has_sf_gate=track_has_sf_gate)


def _build_recap(ranked):
    """Build recap data for a completed event."""
    recap = {
        'podium': ranked[:3],
    }

    # Closest battle
    min_gap = float('inf')
    closest = None
    for i in range(len(ranked) - 1):
        a = ranked[i]
        b = ranked[i + 1]
        if a['best_lap'] and b['best_lap']:
            gap = b['best_lap'] - a['best_lap']
            if gap < min_gap:
                min_gap = gap
                closest = (a['name'], b['name'], gap)
    if closest:
        recap['closest_battle'] = {
            'driver_a': closest[0],
            'driver_b': closest[1],
            'gap': round(closest[2], 3),
        }

    # Most consistent
    best_consistency = None
    for entry in ranked:
        c = entry['consistency']
        if c is not None and c == c:  # NaN check
            if best_consistency is None or c > best_consistency['value']:
                best_consistency = {'name': entry['name'], 'value': c}
    recap['most_consistent'] = best_consistency

    return recap


def _build_corner_leaderboard(event, ranked):
    """Build per-corner leaderboard from CornerSummary data."""
    session_ids = [e['session']['id'] if isinstance(e['session'], dict)
                   else e['session'].id for e in ranked]
    summaries = CornerSummary.query.filter(
        CornerSummary.session_id.in_(session_ids)
    ).order_by(CornerSummary.corner_index).all()

    if not summaries:
        return None

    # Map session_id -> driver name
    session_to_name = {}
    for entry in ranked:
        sid = entry['session'].id if hasattr(entry['session'], 'id') else entry['session']['id']
        session_to_name[sid] = entry['name']

    # Group by corner
    corners = {}
    for s in summaries:
        key = (s.corner_index, s.corner_name)
        if key not in corners:
            corners[key] = []
        corners[key].append({
            'name': session_to_name.get(s.session_id, '?'),
            'min_speed': s.best_min_speed,
            'entry_speed': s.best_entry_speed,
            'exit_speed': s.best_exit_speed,
            'avg_time_loss': s.avg_time_loss,
        })

    # Sort each corner by min_speed descending (fastest first)
    result = []
    for (idx, corner_name), entries in sorted(corners.items()):
        entries.sort(key=lambda x: -(x['min_speed'] or 0))
        for i, e in enumerate(entries):
            e['position'] = i + 1
        result.append({
            'index': idx,
            'name': corner_name,
            'entries': entries,
            'fastest': entries[0] if entries else None,
        })

    return result


def _build_sector_leaderboard(event, ranked):
    """Build per-sector leaderboard from SectorTime data."""
    session_ids = [e['session'].id for e in ranked]

    # Get best sector time per session per sector
    sector_times = SectorTime.query.filter(
        SectorTime.session_id.in_(session_ids)
    ).all()

    if not sector_times:
        return None

    session_to_name = {e['session'].id: e['name'] for e in ranked}

    # Group by sector, find best time per driver per sector
    sectors = {}
    for st in sector_times:
        key = (st.sector_index, st.sector_name)
        if key not in sectors:
            sectors[key] = {}
        sid = st.session_id
        if sid not in sectors[key] or st.seconds < sectors[key][sid]['seconds']:
            sectors[key][sid] = {
                'name': session_to_name.get(sid, '?'),
                'seconds': st.seconds,
            }

    result = []
    for (idx, sector_name), driver_times in sorted(sectors.items()):
        entries = sorted(driver_times.values(), key=lambda x: x['seconds'])
        best = entries[0]['seconds'] if entries else 0
        for i, e in enumerate(entries):
            e['position'] = i + 1
            e['delta'] = round(e['seconds'] - best, 3)
            e['time_fmt'] = _format_laptime(e['seconds'])
        result.append({
            'index': idx,
            'name': sector_name or f'S{idx + 1}',
            'entries': entries,
            'fastest': entries[0] if entries else None,
        })

    return result


# ── Edit ──

@bp.route('/<int:event_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(event_id):
    event = db.session.get(Event, event_id)
    if not event:
        abort(404)
    _require_organizer(event)

    form = EventForm(obj=event)
    tracks = visible_tracks_for_user(current_user.id).all()
    form.track_id.choices = [(0, '— No track —')] + [(t.id, t.name) for t in tracks]

    if request.method == 'GET':
        form.name.data = event.name
        form.date.data = event.date
        if event.time:
            from datetime import time as time_type
            parts = event.time.split(':')
            form.time.data = time_type(int(parts[0]), int(parts[1]))
        form.track_id.data = event.track_id or 0
        form.description.data = event.description

    if form.validate_on_submit():
        old_track_id = event.track_id
        event.name = form.name.data
        event.date = form.date.data
        event.time = form.time.data.strftime('%H:%M') if form.time.data else None
        event.track_id = form.track_id.data
        event.description = form.description.data or None

        # If track changed, unlink sessions that don't match
        if event.track_id != old_track_id:
            for p in event.participants.all():
                if p.session_id:
                    s = db.session.get(Session, p.session_id)
                    if s and s.track_id != event.track_id:
                        p.session_id = None

        db.session.commit()
        flash('Event updated.', 'success')
        return redirect(url_for('events.view', event_id=event.id))

    form.submit.label.text = 'Save Changes'
    return render_template('events/edit.html', form=form, event=event)


# ── Delete ──

@bp.route('/<int:event_id>/delete', methods=['POST'])
@login_required
def delete(event_id):
    event = db.session.get(Event, event_id)
    if not event:
        abort(404)
    _require_organizer(event)

    db.session.delete(event)
    db.session.commit()

    if _is_fetch():
        return jsonify(ok=True)
    flash('Event deleted.', 'success')
    return redirect(url_for('events.list_events'))


# ── Invite ──

@bp.route('/<int:event_id>/invite', methods=['POST'])
@login_required
def invite(event_id):
    event = db.session.get(Event, event_id)
    if not event:
        abort(404)
    _require_organizer(event)

    data = request.get_json(silent=True)
    if not data or 'emails' not in data:
        return jsonify(error='emails required'), 400

    raw = data['emails']
    emails = [e.strip().lower() for e in raw.split(',') if e.strip()]

    added = []
    errors = []
    for email in emails:
        if not EMAIL_RE.match(email):
            errors.append(f'{email}: invalid email')
            continue

        if email == current_user.email:
            errors.append(f'{email}: cannot invite yourself')
            continue

        existing = EventParticipant.query.filter_by(
            event_id=event.id, email=email
        ).first()
        if existing:
            if existing.status == 'declined':
                # Re-invite: reset to pending
                existing.status = 'pending'
                existing.responded_at = None
                db.session.commit()
                added.append(email)
            else:
                errors.append(f'{email}: already invited')
            continue

        user = User.query.filter_by(email=email).first()
        p = EventParticipant(
            event_id=event.id,
            email=email,
            user_id=user.id if user else None,
            role='participant',
            status='pending',
        )
        db.session.add(p)
        added.append(email)

    db.session.commit()
    return jsonify(added=added, errors=errors)


# ── Remove participant ──

@bp.route('/<int:event_id>/remove/<int:participant_id>', methods=['POST'])
@login_required
def remove_participant(event_id, participant_id):
    event = db.session.get(Event, event_id)
    if not event:
        abort(404)
    _require_organizer(event)

    p = db.session.get(EventParticipant, participant_id)
    if not p or p.event_id != event.id:
        abort(404)

    if p.user_id == current_user.id:
        return jsonify(error='Cannot remove yourself'), 400

    db.session.delete(p)
    db.session.commit()

    if _is_fetch():
        return jsonify(ok=True)
    return redirect(url_for('events.view', event_id=event.id))


# ── Accept / Decline ──

@bp.route('/<int:event_id>/accept', methods=['POST'])
@login_required
def accept(event_id):
    event = db.session.get(Event, event_id)
    if not event:
        abort(404)

    p = EventParticipant.query.filter_by(
        event_id=event.id, user_id=current_user.id, status='pending'
    ).first()
    if not p:
        return jsonify(error='No pending invitation'), 404

    p.status = 'accepted'
    p.responded_at = datetime.now(timezone.utc)
    db.session.commit()

    if _is_fetch():
        return jsonify(ok=True)
    flash(f'You joined "{event.name}".', 'success')
    return redirect(url_for('events.view', event_id=event.id))


@bp.route('/<int:event_id>/decline', methods=['POST'])
@login_required
def decline(event_id):
    event = db.session.get(Event, event_id)
    if not event:
        abort(404)

    p = EventParticipant.query.filter_by(
        event_id=event.id, user_id=current_user.id, status='pending'
    ).first()
    if not p:
        return jsonify(error='No pending invitation'), 404

    p.status = 'declined'
    p.responded_at = datetime.now(timezone.utc)
    db.session.commit()

    if _is_fetch():
        return jsonify(ok=True)
    flash('Invitation declined.', 'info')
    return redirect(url_for('events.list_events'))


# ── Session linking ──

@bp.route('/<int:event_id>/link-session', methods=['POST'])
@login_required
def link_session(event_id):
    event = db.session.get(Event, event_id)
    if not event:
        abort(404)

    p = _require_participant(event, status_filter=['accepted', 'organizer'])

    if not event.track_id:
        return jsonify(error='Event has no track — cannot link sessions'), 400

    data = request.get_json(silent=True)
    if not data or 'session_id' not in data:
        return jsonify(error='session_id required'), 400

    session = db.session.get(Session, data['session_id'])
    if not session or session.user_id != current_user.id:
        return jsonify(error='Session not found'), 404

    if session.track_id != event.track_id:
        return jsonify(error='Session is not at the event track'), 400

    # Check if this session is already linked by another participant
    existing = EventParticipant.query.filter_by(
        event_id=event.id, session_id=session.id
    ).first()
    if existing and existing.id != p.id:
        return jsonify(error='This session is already linked by another participant'), 409

    p.session_id = session.id
    db.session.commit()

    return jsonify(ok=True)


@bp.route('/<int:event_id>/unlink-session', methods=['POST'])
@login_required
def unlink_session(event_id):
    event = db.session.get(Event, event_id)
    if not event:
        abort(404)

    p = _require_participant(event, status_filter=['accepted', 'organizer'])
    p.session_id = None
    db.session.commit()

    if _is_fetch():
        return jsonify(ok=True)
    return redirect(url_for('events.view', event_id=event.id))


@bp.route('/<int:event_id>/my-sessions')
@login_required
def my_sessions(event_id):
    """Return current user's sessions at the event's track."""
    event = db.session.get(Event, event_id)
    if not event:
        abort(404)

    _require_participant(event, status_filter=['accepted', 'organizer'])

    if not event.track_id:
        return jsonify([])

    sessions = Session.query.filter_by(
        user_id=current_user.id, track_id=event.track_id
    ).order_by(Session.date.desc()).all()

    return jsonify([
        {
            'id': s.id,
            'date': str(s.date),
            'date_fmt': s.date.strftime('%-d %b %Y'),
            'best_lap': s.best_lap_time,
            'best_lap_fmt': _format_laptime(s.best_lap_time),
            'total_laps': s.total_laps,
        }
        for s in sessions
    ])
