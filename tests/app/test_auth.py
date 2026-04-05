from unittest.mock import patch, MagicMock

from flask_login import login_user

from app import db
from app.models import User


FAKE_GOOGLE_USERINFO = {
    'sub': 'google-123',
    'email': 'test@gmail.com',
    'name': 'Test User',
}


def _mock_authorize_access_token(userinfo=None):
    """Patch oauth.google.authorize_access_token to return fake token."""
    token = {'userinfo': userinfo or FAKE_GOOGLE_USERINFO}
    return patch('app.auth.routes.oauth.google.authorize_access_token', return_value=token)


class TestLogin:
    def test_login_page_loads(self, client):
        resp = client.get('/auth/login')
        assert resp.status_code == 200
        assert b'Sign in with Google' in resp.data

    def test_login_google_redirects(self, client):
        resp = client.get('/auth/login/google')
        assert resp.status_code == 302

    def test_protected_redirect(self, client):
        resp = client.get('/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']


class TestCallback:
    def test_creates_new_user(self, client, db_session):
        with _mock_authorize_access_token():
            resp = client.get('/auth/callback', follow_redirects=False)

        assert resp.status_code == 302
        user = User.query.filter_by(email='test@gmail.com').first()
        assert user is not None
        assert user.display_name == 'Test User'
        assert user.google_id == 'google-123'

    def test_links_existing_user_by_email(self, client, db_session):
        user = User(email='test@gmail.com', display_name='Existing', google_id=None)
        db_session.add(user)
        db_session.commit()

        with _mock_authorize_access_token():
            client.get('/auth/callback')

        user = User.query.filter_by(email='test@gmail.com').first()
        assert user.google_id == 'google-123'
        assert user.display_name == 'Existing'  # keeps original name

    def test_returning_user_by_google_id(self, client, db_session):
        user = User(email='test@gmail.com', display_name='Returning', google_id='google-123')
        db_session.add(user)
        db_session.commit()

        with _mock_authorize_access_token():
            resp = client.get('/auth/callback', follow_redirects=False)

        assert resp.status_code == 302
        assert User.query.count() == 1  # no duplicate created

    def test_handles_missing_userinfo(self, client, db_session):
        with patch('app.auth.routes.oauth.google.authorize_access_token', return_value={'userinfo': None}):
            resp = client.get('/auth/callback', follow_redirects=True)

        assert b'Failed to get user info' in resp.data
        assert User.query.count() == 0


class TestLogout:
    def test_logout(self, app, client, db_session):
        user = User(email='test@gmail.com', display_name='Test', google_id='google-123')
        db_session.add(user)
        db_session.commit()

        with client.session_transaction() as sess:
            pass
        with app.test_request_context():
            login_user(user)

        resp = client.get('/auth/logout', follow_redirects=True)
        assert b'Sign in' in resp.data
