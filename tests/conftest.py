import os
import tempfile
import pytest
from app import create_app

@pytest.fixture
def app():
    db_fd, db_path = tempfile.mkstemp()
    app = create_app({
        'TESTING': True,
        'DATABASE': db_path,
        'SECRET_KEY': 'test_secret_key',
        'COOKIE_SECURE': False
    })

    yield app

    os.close(db_fd)
    # The DB should be closed by teardown_appcontext if it was used.
    # We might need a small sleep or a more robust cleanup on Windows.
    import time
    time.sleep(0.1)
    try:
        os.unlink(db_path)
    except PermissionError:
        pass # Handle or log if cleanup fails


@pytest.fixture
def client(app):
    return app.test_client()

class AuthActions:
    def __init__(self, client):
        self._client = client

    def register(self, username='testuser', password='password123', role='individual', headers=None):
        if headers is None:
            headers = {'X-Requested-With': 'XMLHttpRequest'}
        return self._client.post(
            '/api/register',
            json={'username': username, 'password': password, 'role': role},
            headers=headers
        )

    def login(self, username='testuser', password='password123', headers=None):
        if headers is None:
            headers = {'X-Requested-With': 'XMLHttpRequest'}
        return self._client.post(
            '/api/login',
            json={'username': username, 'password': password},
            headers=headers
        )

    def logout(self, headers=None):
        if headers is None:
            headers = {'X-Requested-With': 'XMLHttpRequest'}
        return self._client.post('/api/logout', headers=headers)

@pytest.fixture
def auth(client):
    return AuthActions(client)
