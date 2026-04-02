from app.models import User


class TestRegister:
    def test_register_page_loads(self, client):
        resp = client.get('/auth/register')
        assert resp.status_code == 200
        assert b'Register' in resp.data

    def test_register_success(self, client, db_session):
        resp = client.post('/auth/register', data={
            'email': 'new@test.com',
            'display_name': 'New User',
            'password': 'secret123',
            'password2': 'secret123',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'Registration successful' in resp.data

        user = User.query.filter_by(email='new@test.com').first()
        assert user is not None
        assert user.display_name == 'New User'

    def test_register_duplicate_email(self, client, db_session):
        # First registration
        client.post('/auth/register', data={
            'email': 'dup@test.com',
            'display_name': 'First',
            'password': 'secret123',
            'password2': 'secret123',
        })
        # Second registration with same email
        resp = client.post('/auth/register', data={
            'email': 'dup@test.com',
            'display_name': 'Second',
            'password': 'secret123',
            'password2': 'secret123',
        }, follow_redirects=True)
        assert b'already registered' in resp.data

    def test_register_password_mismatch(self, client):
        resp = client.post('/auth/register', data={
            'email': 'test@test.com',
            'display_name': 'Test',
            'password': 'secret123',
            'password2': 'different',
        })
        assert resp.status_code == 200  # stays on form


class TestLogin:
    def _register(self, client):
        client.post('/auth/register', data={
            'email': 'user@test.com',
            'display_name': 'User',
            'password': 'secret123',
            'password2': 'secret123',
        })

    def test_login_page_loads(self, client):
        resp = client.get('/auth/login')
        assert resp.status_code == 200
        assert b'Log In' in resp.data

    def test_login_success(self, client, db_session):
        self._register(client)
        resp = client.post('/auth/login', data={
            'email': 'user@test.com',
            'password': 'secret123',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert b'User' in resp.data  # display name shown

    def test_login_wrong_password(self, client, db_session):
        self._register(client)
        resp = client.post('/auth/login', data={
            'email': 'user@test.com',
            'password': 'wrong',
        }, follow_redirects=True)
        assert b'Invalid email or password' in resp.data

    def test_logout(self, client, db_session):
        self._register(client)
        client.post('/auth/login', data={
            'email': 'user@test.com',
            'password': 'secret123',
        })
        resp = client.get('/auth/logout', follow_redirects=True)
        assert b'Log In' in resp.data

    def test_protected_redirect(self, client):
        resp = client.get('/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']
