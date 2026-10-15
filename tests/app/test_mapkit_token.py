"""Tests for MapKit token expiry checks and their admin dashboard visibility."""

import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import jwt
from flask import Flask

from app import db, _mapkit_token_exp, _validate_env
from app.models import User


def _prod_like_app(mapkit_token):
    """Minimal app that passes every production check except token expiry."""
    app = Flask(__name__)
    app.config.update(
        TESTING=False,
        DEBUG=False,
        SECRET_KEY='not-the-default',
        SQLALCHEMY_DATABASE_URI='postgresql://user:pass@localhost/boxbox',
        GOOGLE_CLIENT_ID='client-id',
        GOOGLE_CLIENT_SECRET='client-secret',
        MAPKIT_TOKEN=mapkit_token,
    )
    return app


def _make_jwt(claims):
    return jwt.encode(claims, 'x' * 32, algorithm='HS256')


@contextmanager
def _capture_logs(app):
    records = []

    class CaptureHandler(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = CaptureHandler()
    app.logger.addHandler(handler)
    try:
        yield records
    finally:
        app.logger.removeHandler(handler)


# ── _mapkit_token_exp ──

class TestMapkitTokenExp:
    def test_parses_exp_claim(self):
        exp = int(time.time()) + 3600
        assert _mapkit_token_exp(_make_jwt({'exp': exp})) == exp

    def test_non_jwt_returns_none(self):
        assert _mapkit_token_exp('test-token') is None

    def test_garbage_payload_returns_none(self):
        assert _mapkit_token_exp('x.!!!!!.y') is None

    def test_missing_exp_returns_none(self):
        assert _mapkit_token_exp(_make_jwt({'iss': 'team'})) is None


# ── _validate_env ──

class TestValidateEnvMapkitExpiry:
    def test_healthy_token_is_silent(self):
        app = _prod_like_app(_make_jwt({'exp': int(time.time()) + 90 * 86400}))
        with _capture_logs(app) as records:
            _validate_env(app)
        assert not [r for r in records if 'MAPKIT_TOKEN' in r.getMessage()]

    def test_expiring_within_30_days_warns(self):
        app = _prod_like_app(_make_jwt({'exp': int(time.time()) + 5 * 86400}))
        with _capture_logs(app) as records:
            _validate_env(app)
        assert any(
            r.levelno == logging.WARNING and 'MAPKIT_TOKEN expires' in r.getMessage()
            for r in records
        )

    def test_expired_token_logs_error(self):
        app = _prod_like_app(_make_jwt({'exp': int(time.time()) - 3600}))
        with _capture_logs(app) as records:
            _validate_env(app)
        assert any(
            r.levelno == logging.ERROR and 'MAPKIT_TOKEN has expired' in r.getMessage()
            for r in records
        )


# ── Admin dashboard visibility ──

class TestAdminDashboardMapkitCard:
    def test_shows_mapkit_token_status(self, app, client):
        with app.app_context():
            admin = User(
                email='admin@test.com', display_name='Admin User',
                google_id='g-admin', is_admin=True,
                terms_accepted_at=datetime.now(timezone.utc),
            )
            db.session.add(admin)
            db.session.commit()

            with client.session_transaction() as sess:
                sess['_user_id'] = str(admin.id)

            rv = client.get('/admin/')
            assert rv.status_code == 200
            body = rv.get_data(as_text=True)
            assert 'MapKit token' in body
            # TestingConfig uses a non-JWT token, so expiry is unknown
            assert 'Expiry unknown' in body

    def test_non_admin_gets_403(self, app, client):
        with app.app_context():
            user = User(
                email='user@test.com', display_name='Normal User',
                google_id='g-user', terms_accepted_at=datetime.now(timezone.utc),
            )
            db.session.add(user)
            db.session.commit()

            with client.session_transaction() as sess:
                sess['_user_id'] = str(user.id)

            rv = client.get('/admin/')
            assert rv.status_code == 403
