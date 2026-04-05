from flask import Flask, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect
from authlib.integrations.flask_client import OAuth

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
oauth = OAuth()


def create_app(config_name=None):
    app = Flask(__name__)

    if config_name == 'testing':
        from app.config import TestingConfig
        app.config.from_object(TestingConfig)
    else:
        from app.config import Config
        app.config.from_object(Config)

    if not app.config.get('TESTING') and not app.config.get('MAPKIT_TOKEN'):
        raise RuntimeError('MAPKIT_TOKEN environment variable is required')

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
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

    # CLI commands
    from app.cli import seed_tracks, import_session, reingest_session
    app.cli.add_command(seed_tracks)
    app.cli.add_command(import_session)
    app.cli.add_command(reingest_session)

    @app.route('/health')
    def health():
        return jsonify(status='ok')

    @app.route('/')
    def index():
        if current_user.is_authenticated:
            return redirect(url_for('sessions.list_sessions'))
        return redirect(url_for('auth.login'))

    return app
