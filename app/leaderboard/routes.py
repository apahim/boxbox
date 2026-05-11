import json
import re

from flask import render_template, redirect, url_for, flash, request, jsonify, abort, current_app
from flask_login import login_required, current_user

from app import db
from app.leaderboard import bp
from app.leaderboard.forms import LeaderboardForm
from app.models import (
    Leaderboard, LeaderboardShare, Track, User,
)

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

PERIOD_LABELS = {
    'last_30': 'Last 30 days',
    'last_90': 'Last 90 days',
    'this_year': 'This year',
    'all_time': 'All time',
    'custom': 'Custom range',
}


def _is_fetch():
    return request.headers.get('X-Requested-With') == 'fetch'


def _can_view(lb, user_id):
    if lb.visibility == 'official':
        return True
    if lb.created_by == user_id:
        return True
    if lb.visibility == 'shared':
        return LeaderboardShare.query.filter_by(
            leaderboard_id=lb.id, user_id=user_id
        ).first() is not None
    return False


def _period_label(lb):
    if lb.period_type == 'custom' and lb.period_start and lb.period_end:
        return f"{lb.period_start.strftime('%-d %b %Y')} – {lb.period_end.strftime('%-d %b %Y')}"
    return PERIOD_LABELS.get(lb.period_type, lb.period_type)


def _populate_track_choices(form):
    tracks = Track.query.filter(
        Track.created_by.is_(None)
    ).order_by(Track.name).all()
    form.track_id.choices = [(t.id, t.name) for t in tracks]


# ── List ──

@bp.route('/')
@login_required
def list_leaderboards():
    official = Leaderboard.query.filter_by(
        visibility='official'
    ).order_by(Leaderboard.name).all()

    shared_with_me = Leaderboard.query.join(LeaderboardShare).filter(
        LeaderboardShare.user_id == current_user.id,
        Leaderboard.created_by != current_user.id,
    ).order_by(Leaderboard.name).all()

    mine = Leaderboard.query.filter_by(
        created_by=current_user.id
    ).filter(
        Leaderboard.visibility != 'official'
    ).order_by(Leaderboard.created_at.desc()).all()

    shares_by_lb = {}
    if mine:
        mine_ids = [lb.id for lb in mine]
        all_shares = LeaderboardShare.query.filter(
            LeaderboardShare.leaderboard_id.in_(mine_ids)
        ).all()
        for s in all_shares:
            if s.user:
                shares_by_lb.setdefault(s.leaderboard_id, []).append({
                    'id': s.user.id,
                    'name': s.user.display_name,
                    'email': s.user.email,
                })

    return render_template('leaderboard/list.html',
                           official=official,
                           shared_with_me=shared_with_me,
                           mine=mine,
                           period_label=_period_label,
                           shares_by_lb=shares_by_lb,
                           is_admin=current_user.is_admin)


# ── Create ──

@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    form = LeaderboardForm()
    _populate_track_choices(form)

    if form.validate_on_submit():
        try:
            labels = json.loads(form.labels.data) if form.labels.data else []
        except (json.JSONDecodeError, TypeError):
            labels = []

        lb = Leaderboard(
            name=form.name.data,
            track_id=form.track_id.data,
            labels=labels,
            period_type=form.period_type.data,
            period_start=form.period_start.data if form.period_type.data == 'custom' else None,
            period_end=form.period_end.data if form.period_type.data == 'custom' else None,
            max_drivers=form.max_drivers.data,
            created_by=current_user.id,
        )
        db.session.add(lb)
        db.session.commit()

        flash(f'Leaderboard "{lb.name}" created.', 'success')
        return redirect(url_for('leaderboard.view', lb_id=lb.id))

    return render_template('leaderboard/create.html', form=form)


# ── View ──

@bp.route('/<int:lb_id>')
@login_required
def view(lb_id):
    lb = db.session.get(Leaderboard, lb_id)
    if not lb:
        abort(404)
    if not _can_view(lb, current_user.id):
        abort(403)

    is_creator = lb.created_by == current_user.id

    shared_users = []
    if is_creator:
        shares = LeaderboardShare.query.filter_by(
            leaderboard_id=lb.id
        ).all()
        shared_users = [
            {'id': s.user.id, 'name': s.user.display_name, 'email': s.user.email}
            for s in shares if s.user
        ]

    mapkit_token = current_app.config.get('MAPKIT_TOKEN', '')
    return render_template('leaderboard/view.html',
                           lb=lb,
                           is_creator=is_creator,
                           shared_users=shared_users,
                           period_label=_period_label(lb),
                           mapkit_token=mapkit_token)


# ── Edit ──

@bp.route('/<int:lb_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(lb_id):
    lb = db.session.get(Leaderboard, lb_id)
    if not lb:
        abort(404)
    if lb.created_by != current_user.id:
        abort(403)

    form = LeaderboardForm(obj=lb)
    _populate_track_choices(form)

    if request.method == 'GET':
        form.name.data = lb.name
        form.track_id.data = lb.track_id
        form.labels.data = json.dumps(lb.labels or [])
        form.period_type.data = lb.period_type
        form.period_start.data = lb.period_start
        form.period_end.data = lb.period_end
        form.max_drivers.data = lb.max_drivers

    if form.validate_on_submit():
        try:
            labels = json.loads(form.labels.data) if form.labels.data else []
        except (json.JSONDecodeError, TypeError):
            labels = []

        lb.name = form.name.data
        lb.track_id = form.track_id.data
        lb.labels = labels
        lb.period_type = form.period_type.data
        lb.period_start = form.period_start.data if form.period_type.data == 'custom' else None
        lb.period_end = form.period_end.data if form.period_type.data == 'custom' else None
        lb.max_drivers = form.max_drivers.data
        db.session.commit()

        flash('Leaderboard updated.', 'success')
        return redirect(url_for('leaderboard.view', lb_id=lb.id))

    form.submit.label.text = 'Save Changes'
    return render_template('leaderboard/create.html', form=form, lb=lb)


# ── Delete ──

@bp.route('/<int:lb_id>/delete', methods=['POST'])
@login_required
def delete(lb_id):
    lb = db.session.get(Leaderboard, lb_id)
    if not lb:
        abort(404)
    if lb.created_by != current_user.id:
        abort(403)

    db.session.delete(lb)
    db.session.commit()

    if _is_fetch():
        return jsonify(ok=True)
    flash('Leaderboard deleted.', 'success')
    return redirect(url_for('leaderboard.list_leaderboards'))


# ── Share ──

@bp.route('/<int:lb_id>/share', methods=['POST'])
@login_required
def share(lb_id):
    lb = db.session.get(Leaderboard, lb_id)
    if not lb:
        abort(404)
    if lb.created_by != current_user.id:
        abort(403)

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
            errors.append(f'{email}: cannot share with yourself')
            continue

        user = User.query.filter_by(email=email).first()
        if not user:
            errors.append(f'{email}: user not found')
            continue

        existing = LeaderboardShare.query.filter_by(
            leaderboard_id=lb.id, user_id=user.id
        ).first()
        if existing:
            errors.append(f'{email}: already shared')
            continue

        share = LeaderboardShare(leaderboard_id=lb.id, user_id=user.id)
        db.session.add(share)
        added.append(email)

    if added and lb.visibility == 'personal':
        lb.visibility = 'shared'

    db.session.commit()
    return jsonify(added=added, errors=errors)


# ── Unshare ──

@bp.route('/<int:lb_id>/unshare/<int:user_id>', methods=['POST'])
@login_required
def unshare(lb_id, user_id):
    lb = db.session.get(Leaderboard, lb_id)
    if not lb:
        abort(404)
    if lb.created_by != current_user.id:
        abort(403)

    share = LeaderboardShare.query.filter_by(
        leaderboard_id=lb.id, user_id=user_id
    ).first()
    if share:
        db.session.delete(share)

        remaining = LeaderboardShare.query.filter_by(
            leaderboard_id=lb.id
        ).count()
        if remaining <= 1 and lb.visibility == 'shared':
            lb.visibility = 'personal'

        db.session.commit()

    if _is_fetch():
        return jsonify(ok=True)
    return redirect(url_for('leaderboard.view', lb_id=lb.id))


# ── Publish / Unpublish (admin) ──

@bp.route('/<int:lb_id>/publish', methods=['POST'])
@login_required
def publish(lb_id):
    if not current_user.is_admin:
        abort(403)

    lb = db.session.get(Leaderboard, lb_id)
    if not lb:
        abort(404)

    lb.visibility = 'official'
    db.session.commit()

    if _is_fetch():
        return jsonify(ok=True)
    flash('Leaderboard published as official.', 'success')
    return redirect(url_for('leaderboard.view', lb_id=lb.id))


@bp.route('/<int:lb_id>/unpublish', methods=['POST'])
@login_required
def unpublish(lb_id):
    if not current_user.is_admin:
        abort(403)

    lb = db.session.get(Leaderboard, lb_id)
    if not lb:
        abort(404)

    has_shares = LeaderboardShare.query.filter_by(
        leaderboard_id=lb.id
    ).first() is not None
    lb.visibility = 'shared' if has_shares else 'personal'
    db.session.commit()

    if _is_fetch():
        return jsonify(ok=True)
    flash('Leaderboard unpublished.', 'success')
    return redirect(url_for('leaderboard.view', lb_id=lb.id))
