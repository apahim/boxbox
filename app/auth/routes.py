from flask import render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, current_user

from app import db
from app.auth import bp
from app.auth.forms import RegisterForm, LoginForm
from app.models import User


@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = RegisterForm()
    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data.lower()).first():
            flash('Email already registered.', 'danger')
            return render_template('auth/register.html', form=form)

        user = User(
            email=form.email.data.lower(),
            display_name=form.display_name.data,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        flash('Registration successful. Please log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html', form=form)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user is None or not user.check_password(form.password.data):
            flash('Invalid email or password.', 'danger')
            return render_template('auth/login.html', form=form)

        login_user(user)
        next_page = request.args.get('next')
        return redirect(next_page or url_for('index'))

    return render_template('auth/login.html', form=form)


@bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
