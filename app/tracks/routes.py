import json
import re

from flask import render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user

from app import db
from app.tracks import bp
from app.tracks.forms import TrackForm
from app.models import Track, TrackCorner


def _slugify(name):
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '_', slug)
    return slug.strip('_')


@bp.route('/')
@login_required
def list_tracks():
    tracks = Track.query.order_by(Track.name).all()
    track_data = []
    for t in tracks:
        track_data.append({
            'track': t,
            'corner_count': t.corners.count(),
        })
    return render_template('tracks/list.html', tracks=track_data)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    form = TrackForm()
    if form.validate_on_submit():
        slug = _slugify(form.name.data)
        if Track.query.filter_by(slug=slug).first():
            flash('A track with that name already exists.', 'danger')
            return render_template('tracks/create.html', form=form)

        track = Track(
            name=form.name.data,
            slug=slug,
            lat=form.lat.data,
            lon=form.lon.data,
            timezone=form.timezone.data or 'UTC',
            created_by=current_user.id,
        )
        db.session.add(track)
        db.session.commit()

        flash(f'Track "{track.name}" created. Add corners below.', 'success')
        return redirect(url_for('tracks.edit', slug=slug))

    return render_template('tracks/create.html', form=form)


@bp.route('/<slug>/edit', methods=['GET', 'POST'])
@login_required
def edit(slug):
    track = Track.query.filter_by(slug=slug).first_or_404()

    if request.method == 'POST':
        corners_json = request.form.get('corners_json', '[]')
        try:
            corners_data = json.loads(corners_json)
        except json.JSONDecodeError:
            flash('Invalid corner data.', 'danger')
            return redirect(url_for('tracks.edit', slug=slug))

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

        db.session.commit()
        flash('Corners saved.', 'success')
        return redirect(url_for('tracks.edit', slug=slug))

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

    return render_template('tracks/edit.html',
                           track=track,
                           corners=corners_list,
                           corners_json=json.dumps(corners_list),
                           mapkit_token=mapkit_token)
