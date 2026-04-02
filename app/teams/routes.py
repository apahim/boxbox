import re

from flask import render_template, redirect, url_for, flash
from flask_login import login_required, current_user

from app import db
from app.teams import bp
from app.teams.forms import TeamForm, AddMemberForm
from app.models import Team, TeamMember, User


def _slugify(name):
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    return slug.strip('-')


@bp.route('/')
@login_required
def list_teams():
    memberships = TeamMember.query.filter_by(user_id=current_user.id).all()
    team_ids = [m.team_id for m in memberships]
    teams = Team.query.filter(Team.id.in_(team_ids)).all() if team_ids else []
    return render_template('teams/list.html', teams=teams, memberships={m.team_id: m.role for m in memberships})


@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    form = TeamForm()
    if form.validate_on_submit():
        slug = _slugify(form.name.data)
        if Team.query.filter_by(slug=slug).first():
            flash('A team with that name already exists.', 'danger')
            return render_template('teams/create.html', form=form)

        team = Team(name=form.name.data, slug=slug, created_by=current_user.id)
        db.session.add(team)
        db.session.flush()

        owner = TeamMember(team_id=team.id, user_id=current_user.id, role='owner')
        db.session.add(owner)
        db.session.commit()

        flash(f'Team "{team.name}" created.', 'success')
        return redirect(url_for('teams.manage', slug=slug))

    return render_template('teams/create.html', form=form)


@bp.route('/<slug>/manage', methods=['GET', 'POST'])
@login_required
def manage(slug):
    team = Team.query.filter_by(slug=slug).first_or_404()

    ownership = TeamMember.query.filter_by(
        team_id=team.id, user_id=current_user.id, role='owner'
    ).first()
    if not ownership:
        flash('Only team owners can manage the team.', 'danger')
        return redirect(url_for('teams.list_teams'))

    form = AddMemberForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if not user:
            flash('No user found with that email.', 'warning')
        elif TeamMember.query.filter_by(team_id=team.id, user_id=user.id).first():
            flash('User is already a team member.', 'info')
        else:
            member = TeamMember(team_id=team.id, user_id=user.id, role='member')
            db.session.add(member)
            db.session.commit()
            flash(f'Added {user.display_name} to the team.', 'success')

        return redirect(url_for('teams.manage', slug=slug))

    members = TeamMember.query.filter_by(team_id=team.id).all()
    return render_template('teams/manage.html', team=team, members=members, form=form)


@bp.route('/<slug>/remove/<int:user_id>', methods=['POST'])
@login_required
def remove_member(slug, user_id):
    team = Team.query.filter_by(slug=slug).first_or_404()

    ownership = TeamMember.query.filter_by(
        team_id=team.id, user_id=current_user.id, role='owner'
    ).first()
    if not ownership:
        flash('Only team owners can remove members.', 'danger')
        return redirect(url_for('teams.list_teams'))

    if user_id == current_user.id:
        flash('You cannot remove yourself from the team.', 'warning')
        return redirect(url_for('teams.manage', slug=slug))

    member = TeamMember.query.filter_by(team_id=team.id, user_id=user_id).first()
    if member:
        db.session.delete(member)
        db.session.commit()
        flash('Member removed.', 'success')

    return redirect(url_for('teams.manage', slug=slug))
