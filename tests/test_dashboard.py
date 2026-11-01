import os
import tempfile
import pytest
from app import create_app

INDEX = '<!doctype html><div id="root"></div>'

@pytest.fixture
def dash(tmp_path):
    folder = tmp_path / 'dist'
    (folder / 'assets').mkdir(parents=True)
    (folder / 'index.html').write_text(INDEX, encoding='utf-8')
    (folder / 'assets' / 'app.js').write_text('console.log(1)', encoding='utf-8')
    # A file next to the folder that must never be reachable
    (tmp_path / 'secret.txt').write_text('top secret', encoding='utf-8')
    return folder

def make_client(dashboard_dir):
    db_fd, db_path = tempfile.mkstemp()
    os.close(db_fd)
    app = create_app({
        'TESTING': True,
        'DATABASE': db_path,
        'SECRET_KEY': 'test_secret_key',
        'COOKIE_SECURE': False,
        'DASHBOARD_DIR': str(dashboard_dir) if dashboard_dir else None,
    })
    return app.test_client()

def test_root_serves_index(dash):
    res = make_client(dash).get('/')
    assert res.status_code == 200
    assert b'<div id="root">' in res.data

def test_existing_file_served(dash):
    res = make_client(dash).get('/assets/app.js')
    assert res.status_code == 200
    assert res.data == b'console.log(1)'

def test_spa_fallback(dash):
    res = make_client(dash).get('/some/path')
    assert res.status_code == 200
    assert b'<div id="root">' in res.data

def test_api_unchanged(dash):
    client = make_client(dash)
    res = client.get('/api/health')
    assert res.status_code == 200
    assert res.get_json() == {"ok": True, "version": "1", "db": True}
    assert client.get('/api/me').status_code == 401

def test_unknown_api_path_not_index(dash):
    res = make_client(dash).get('/api/does-not-exist')
    assert res.status_code == 404
    assert b'<div id="root">' not in res.data

@pytest.mark.parametrize('path', [
    '/../secret.txt',
    '/assets/../../secret.txt',
    '/%2e%2e/secret.txt',
    '/assets/%2e%2e/%2e%2e/secret.txt',
])
def test_escape_returns_404(dash, path):
    res = make_client(dash).get(path)
    assert res.status_code == 404
    assert b'top secret' not in res.data

def test_not_served_without_setting():
    res = make_client(None).get('/')
    assert res.status_code == 404
    assert make_client(None).get('/api/health').status_code == 200

def test_not_served_when_folder_missing(tmp_path):
    res = make_client(tmp_path / 'missing').get('/')
    assert res.status_code == 404
