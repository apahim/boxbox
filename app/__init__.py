import hashlib
import logging
import time

from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from authlib.integrations.flask_client import OAuth

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
oauth = OAuth()
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"],
                  storage_uri="memory://")


def _configure_logging(app):
    if not app.debug and not app.testing:
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s %(name)s: %(message)s'
        ))
        app.logger.addHandler(handler)
        app.logger.setLevel(logging.INFO)


def _validate_env(app):
    """Ensure critical env vars are set for production."""
    if app.config.get('TESTING') or app.debug:
        return

    if not app.config.get('MAPKIT_TOKEN'):
        raise RuntimeError('MAPKIT_TOKEN environment variable is required')

    if app.config.get('SECRET_KEY') == 'dev-secret-change-me':
        raise RuntimeError('SECRET_KEY must be changed for production')

    if app.config.get('SQLALCHEMY_DATABASE_URI', '').startswith('sqlite:'):
        raise RuntimeError('DATABASE_URL must be set to a PostgreSQL URI for production')

    if not app.config.get('GOOGLE_CLIENT_ID') or not app.config.get('GOOGLE_CLIENT_SECRET'):
        raise RuntimeError('GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required')


def _register_error_handlers(app):
    def wants_json():
        return request.headers.get('X-Requested-With') == 'fetch'

    @app.errorhandler(403)
    def forbidden(e):
        if wants_json():
            return jsonify(error='Forbidden'), 403
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        if wants_json():
            return jsonify(error='Not found'), 404
        return render_template('errors/404.html'), 404

    @app.errorhandler(429)
    def rate_limited(e):
        if wants_json():
            return jsonify(error='Too many requests'), 429
        return render_template('errors/429.html'), 429

    @app.errorhandler(500)
    def internal_error(e):
        app.logger.exception('Unhandled exception')
        if wants_json():
            return jsonify(error='Internal server error'), 500
        return render_template('errors/500.html'), 500


def _add_security_headers(app):
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'

        if not app.debug:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'

        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdn.plot.ly https://cdn.apple-mapkit.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com; "
            "img-src 'self' data: https://*.apple-mapkit.com https://*.googleapis.com; "
            "connect-src 'self' https://*.apple-mapkit.com https://cdn.apple-mapkit.com https://cdn.jsdelivr.net; "
            "worker-src blob:; "
            "media-src 'self' blob:; "
        )
        response.headers['Content-Security-Policy'] = csp

        return response


def create_app(config_name=None):
    app = Flask(__name__)

    if config_name == 'testing':
        from app.config import TestingConfig
        app.config.from_object(TestingConfig)
    else:
        from app.config import Config
        app.config.from_object(Config)
        # Trust X-Forwarded-* headers from Caddy reverse proxy
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    _configure_logging(app)
    _validate_env(app)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.login_view = 'auth.login'

    oauth.init_app(app)
    oauth.register(
        name='google',
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'},
    )

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Blueprints
    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from app.tracks import bp as tracks_bp
    app.register_blueprint(tracks_bp, url_prefix='/tracks')

    from app.sessions import bp as sessions_bp
    app.register_blueprint(sessions_bp, url_prefix='/sessions')

    from app.api import bp as api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    from app.dashboard import bp as dashboard_bp
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard')

    from app.events import bp as events_bp
    app.register_blueprint(events_bp, url_prefix='/events')

    from app.legal import bp as legal_bp
    app.register_blueprint(legal_bp)

    # CLI commands
    from app.cli import seed_tracks, import_session, reingest_session, seed_demo, set_admin
    app.cli.add_command(seed_tracks)
    app.cli.add_command(import_session)
    app.cli.add_command(reingest_session)
    app.cli.add_command(seed_demo)
    app.cli.add_command(set_admin)

    _register_error_handlers(app)
    _add_security_headers(app)

    @app.before_request
    def check_terms_accepted():
        if not current_user.is_authenticated:
            return
        if current_user.terms_accepted_at:
            return
        allowed = {
            'auth.login', 'auth.logout', 'auth.callback', 'auth.login_google',
            'legal.terms', 'legal.privacy', 'legal.accept_terms', 'static',
            'dashboard.shared_view', 'health',
        }
        if request.endpoint in allowed:
            return
        return redirect(url_for('legal.accept_terms'))

    # Cache-busting version for static assets
    app.config['ASSET_VERSION'] = hashlib.md5(str(time.time()).encode()).hexdigest()[:8]

    @app.context_processor
    def inject_asset_version():
        return {'asset_v': app.config['ASSET_VERSION']}

    @app.context_processor
    def inject_pending_invite_count():
        if current_user.is_authenticated:
            from app.models import EventParticipant
            count = EventParticipant.query.filter_by(
                user_id=current_user.id, status='pending'
            ).count()
            return {'pending_invite_count': count}
        return {'pending_invite_count': 0}

    @app.route('/health')
    @limiter.exempt
    def health():
        return jsonify(status='ok')

    @app.route('/')
    def index():
        if current_user.is_authenticated:
            return redirect(url_for('sessions.list_sessions'))
        return redirect(url_for('auth.login'))

    return app
