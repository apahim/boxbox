"""Tests for error handlers and production hardening."""


def test_404_html(client):
    """404 returns styled error page, not a stack trace."""
    resp = client.get('/nonexistent-page')
    assert resp.status_code == 404
    assert b'404' in resp.data
    assert b'BoxBox' in resp.data


def test_404_json(client):
    """404 returns JSON when requested via fetch."""
    resp = client.get('/nonexistent-page', headers={'X-Requested-With': 'fetch'})
    assert resp.status_code == 404
    data = resp.get_json()
    assert data['error'] == 'Not found'


def test_security_headers(client):
    """Responses include security headers."""
    resp = client.get('/health')
    assert resp.headers.get('X-Content-Type-Options') == 'nosniff'
    assert resp.headers.get('X-Frame-Options') == 'DENY'
    assert 'Content-Security-Policy' in resp.headers


def test_health_endpoint(client):
    """Health check returns ok."""
    resp = client.get('/health')
    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'ok'


def test_unauthenticated_redirect(client):
    """Unauthenticated users are redirected to login."""
    resp = client.get('/sessions/')
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_delete_nonexistent_session_404(client, app):
    """Deleting a non-existent session returns 404."""
    # Login as a test user
    from datetime import datetime, timezone
    from app import db
    from app.models import User

    with app.app_context():
        user = User(email='test@example.com', display_name='Test', google_id='g123',
                     terms_accepted_at=datetime.now(timezone.utc))
        db.session.add(user)
        db.session.commit()

    with client.session_transaction() as sess:
        sess['_user_id'] = '1'

    resp = client.post('/sessions/99999/delete')
    assert resp.status_code == 404
