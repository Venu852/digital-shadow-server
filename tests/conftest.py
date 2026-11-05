import os
import tempfile
import flask
import pytest
from app import create_app

# Settings from the operator's shell (for example after loading .env.ps1) must not reach the
# tests: they could point the default database at production or require an enrollment code.
SHADOW_ENV = (
    'SHADOW_DB', 'SHADOW_SECRET_KEY', 'COOKIE_SECURE', 'SHADOW_CLIENT_IP_HEADER',
    'SHADOW_ENROLL_CODE', 'SHADOW_DASHBOARD_DIR', 'SHADOW_RETENTION_DAYS',
    'SHADOW_AUDIT_RETENTION_DAYS', 'SHADOW_PORT', 'SHADOW_BACKUP_DIR',
)

@pytest.fixture(scope='session', autouse=True)
def isolated_instance(tmp_path_factory):
    """Every app built during the tests uses a temporary instance folder.

    Flask derives the instance folder from auto_find_instance_path; replacing it covers every
    create_app call, however a test imports it. The request log (LOG_FILE), the secret_key file
    and the default database therefore never touch the repository's instance/ folder.
    """
    instance = str(tmp_path_factory.mktemp('instance'))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(flask.Flask, 'auto_find_instance_path', lambda self: instance)
        for name in SHADOW_ENV:
            mp.delenv(name, raising=False)
        yield instance

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
