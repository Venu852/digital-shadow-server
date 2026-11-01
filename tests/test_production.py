import importlib.util
import os
import sqlite3
import datetime
import pytest
from app import create_app
from app.clientip import client_ip

XRW = {'X-Requested-With': 'XMLHttpRequest'}
SECRET = 'Sup3r-Secret-Pa55word'

def make_app(tmp_path, **config):
    base = {
        'TESTING': True,
        'DATABASE': str(tmp_path / 'shadow.db'),
        'SECRET_KEY': 'test_secret_key',
        'COOKIE_SECURE': False,
        'LOG_FILE': str(tmp_path / 'server.log'),
    }
    base.update(config)
    return create_app(base)

def register(client, username, enroll_code=None, **kwargs):
    body = {'username': username, 'password': 'password123', 'role': 'individual'}
    if enroll_code is not None:
        body['enroll_code'] = enroll_code
    return client.post('/api/register', json=body, headers=XRW, **kwargs)

def login(client, username, password, headers=None, remote='127.0.0.1'):
    return client.post('/api/login', json={'username': username, 'password': password},
                       headers={**XRW, **(headers or {})}, environ_base={'REMOTE_ADDR': remote})

def ip_for(app, headers=None, remote='127.0.0.1'):
    with app.test_request_context('/api/me', headers=headers or {},
                                  environ_base={'REMOTE_ADDR': remote}):
        return client_ip()

# ---------------- client IP behind a proxy ----------------

def test_default_ignores_proxy_headers(tmp_path):
    app = make_app(tmp_path, CLIENT_IP_HEADER='')
    assert ip_for(app, {'X-Forwarded-For': '203.0.113.9'}) == '127.0.0.1'
    assert ip_for(app, {'CF-Connecting-IP': '203.0.113.9'}) == '127.0.0.1'

def test_x_forwarded_for_takes_right_most_ip(tmp_path):
    app = make_app(tmp_path, CLIENT_IP_HEADER='X-Forwarded-For')
    assert ip_for(app, {'X-Forwarded-For': '203.0.113.9'}) == '203.0.113.9'
    # A client can prepend anything; the proxy's own entry is the last one
    assert ip_for(app, {'X-Forwarded-For': '1.1.1.1, 198.51.100.7'}) == '198.51.100.7'
    assert ip_for(app, {'X-Forwarded-For': '198.51.100.7, not-an-ip'}) == '198.51.100.7'
    assert ip_for(app, {'X-Forwarded-For': '2001:db8::1'}) == '2001:db8::1'
    assert ip_for(app) == '127.0.0.1'

def test_cf_connecting_ip(tmp_path):
    app = make_app(tmp_path, CLIENT_IP_HEADER='CF-Connecting-IP')
    assert ip_for(app, {'CF-Connecting-IP': '203.0.113.9'}) == '203.0.113.9'
    # Only the configured header is read
    assert ip_for(app, {'X-Forwarded-For': '203.0.113.9'}) == '127.0.0.1'

def test_spoofing_is_ignored(tmp_path):
    app = make_app(tmp_path, CLIENT_IP_HEADER='X-Forwarded-For')
    # Not from loopback: the header is never trusted
    assert ip_for(app, {'X-Forwarded-For': '203.0.113.9'}, remote='10.0.0.5') == '10.0.0.5'
    # From loopback but no valid IP in the value
    assert ip_for(app, {'X-Forwarded-For': 'evil, also-evil'}) == '127.0.0.1'
    cf = make_app(tmp_path / 'cf', CLIENT_IP_HEADER='CF-Connecting-IP')
    assert ip_for(cf, {'CF-Connecting-IP': '1.2.3.4; drop'}) == '127.0.0.1'
    assert ip_for(cf, {'CF-Connecting-IP': '203.0.113.9'}, remote='192.168.1.20') == '192.168.1.20'

def test_lockout_uses_forwarded_client_ip(tmp_path):
    app = make_app(tmp_path, CLIENT_IP_HEADER='X-Forwarded-For')
    client = app.test_client()
    register(client, 'alice')
    attacker = {'X-Forwarded-For': '203.0.113.9'}
    for _ in range(5):
        assert login(client, 'alice', 'wrong-password', attacker).status_code == 401
    assert login(client, 'alice', 'password123', attacker).status_code == 429
    # Someone else behind the same tunnel is not locked out
    assert login(client, 'alice', 'password123', {'X-Forwarded-For': '198.51.100.7'}).status_code == 200

def test_lockout_cannot_be_dodged_by_spoofing(tmp_path):
    app = make_app(tmp_path, CLIENT_IP_HEADER='X-Forwarded-For')
    client = app.test_client()
    register(client, 'alice')
    for i in range(5):
        res = login(client, 'alice', 'wrong-password', {'X-Forwarded-For': f'203.0.113.{i}'},
                    remote='10.0.0.5')
        assert res.status_code == 401
    assert login(client, 'alice', 'password123', {'X-Forwarded-For': '203.0.113.99'},
                 remote='10.0.0.5').status_code == 429

def test_default_mode_lockout_is_per_connection(tmp_path):
    client = make_app(tmp_path).test_client()
    register(client, 'alice')
    for i in range(5):
        login(client, 'alice', 'wrong-password', {'X-Forwarded-For': f'203.0.113.{i}'})
    assert login(client, 'alice', 'password123').status_code == 429

def test_pairing_lockout_uses_forwarded_ip(tmp_path):
    app = make_app(tmp_path, CLIENT_IP_HEADER='CF-Connecting-IP')
    client = app.test_client()
    register(client, 'alice')

    def pair(password, ip):
        return client.post('/api/devices/pair', headers={'CF-Connecting-IP': ip},
                           json={'username': 'alice', 'password': password, 'device_name': 'Phone'})
    for _ in range(5):
        assert pair('wrong-password', '203.0.113.9').status_code == 401
    assert pair('password123', '203.0.113.9').status_code == 429
    assert pair('password123', '198.51.100.7').status_code == 201

# ---------------- security headers ----------------

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self'; connect-src 'self'; frame-ancestors 'none'")

def check_headers(res):
    assert res.headers['X-Frame-Options'] == 'DENY'
    assert res.headers['X-Content-Type-Options'] == 'nosniff'
    assert res.headers['Referrer-Policy'] == 'no-referrer'
    assert res.headers['Permissions-Policy'] == 'geolocation=(), camera=(), microphone=()'
    assert res.headers['Content-Security-Policy'] == CSP

def test_headers_on_every_response(tmp_path):
    dist = tmp_path / 'dist'
    dist.mkdir()
    (dist / 'index.html').write_text('<!doctype html><div id="root"></div>', encoding='utf-8')
    client = make_app(tmp_path, DASHBOARD_DIR=str(dist)).test_client()
    for res in (client.get('/api/health'), client.get('/api/me'), client.get('/'),
                client.get('/api/nope'), client.post('/api/login', json={})):
        check_headers(res)
        assert 'Strict-Transport-Security' not in res.headers

def test_hsts_only_with_secure_cookies(tmp_path):
    client = make_app(tmp_path, COOKIE_SECURE=True).test_client()
    res = client.get('/api/health')
    check_headers(res)
    assert res.headers['Strict-Transport-Security'] == 'max-age=15552000'

# ---------------- health and config ----------------

def test_health(tmp_path):
    res = make_app(tmp_path).test_client().get('/api/health')
    assert res.status_code == 200
    assert res.get_json() == {"ok": True, "version": "1", "db": True}

def test_config_is_public(tmp_path):
    assert make_app(tmp_path).test_client().get('/api/config').get_json() == {"enroll_required": False}
    closed = make_app(tmp_path / 'closed', ENROLL_CODE='letmein-42').test_client()
    assert closed.get('/api/config').get_json() == {"enroll_required": True}

# ---------------- registration control ----------------

def test_enroll_code_required(tmp_path):
    client = make_app(tmp_path, ENROLL_CODE='letmein-42').test_client()
    for code in (None, '', 'wrong', 'LETMEIN-42', 42):
        res = register(client, 'alice', code)
        assert res.status_code == 403
        assert res.get_json() == {"error": "Enrollment code required."}
    res = register(client, 'alice', 'letmein-42')
    assert res.status_code == 201
    assert res.get_json()['username'] == 'alice'

def test_registration_open_without_code(tmp_path):
    client = make_app(tmp_path, ENROLL_CODE=None).test_client()
    assert register(client, 'alice').status_code == 201
    assert register(client, 'bob', 'anything').status_code == 201

def test_registration_rate_limit(tmp_path):
    client = make_app(tmp_path, CLIENT_IP_HEADER='X-Forwarded-For').test_client()
    one = {'headers': {**XRW, 'X-Forwarded-For': '203.0.113.9'}}
    for i in range(10):
        assert client.post('/api/register', json={'username': f'user{i}', 'password': 'password123',
                                                  'role': 'individual'}, **one).status_code == 201
    res = client.post('/api/register', json={'username': 'user10', 'password': 'password123',
                                             'role': 'individual'}, **one)
    assert res.status_code == 429
    assert 'error' in res.get_json()
    # Another client IP still registers
    assert client.post('/api/register', json={'username': 'other', 'password': 'password123',
                                              'role': 'individual'},
                       headers={**XRW, 'X-Forwarded-For': '198.51.100.7'}).status_code == 201

def test_wrong_enroll_codes_count_toward_limit(tmp_path):
    client = make_app(tmp_path, ENROLL_CODE='letmein-42').test_client()
    for i in range(10):
        assert register(client, f'user{i}', f'guess{i}').status_code == 403
    assert register(client, 'user10', 'letmein-42').status_code == 429

# ---------------- request log ----------------

def test_failed_login_leaves_no_secret_in_log(tmp_path):
    app = make_app(tmp_path, CLIENT_IP_HEADER='X-Forwarded-For')
    client = app.test_client()
    register(client, 'alice')
    res = client.post('/api/login?next=' + SECRET, json={'username': 'alice', 'password': SECRET},
                      headers={**XRW, 'X-Forwarded-For': '203.0.113.9', 'Authorization': 'Bearer ' + SECRET})
    assert res.status_code == 401
    text = (tmp_path / 'server.log').read_text(encoding='utf-8')
    assert SECRET not in text
    assert 'password' not in text.lower()
    line = text.strip().splitlines()[-1].split(' ')
    assert line[1:4] == ['POST', '/api/login', '401']
    assert line[4].endswith('ms')
    assert line[5] == '203.0.113.9'

def test_log_line_cannot_be_forged(tmp_path):
    client = make_app(tmp_path).test_client()
    client.get('/api/x%0A2026-01-01T00:00:00Z%20GET%20/fake%20200')
    lines = (tmp_path / 'server.log').read_text(encoding='utf-8').strip().splitlines()
    assert len(lines) == 1
    assert len(lines[0].split(' ')) == 6

# ---------------- backups ----------------

def load_backup_module():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts', 'backup.py')
    spec = importlib.util.spec_from_file_location('backup_script', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_backup_restores_accounts(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    register(client, 'alice')
    register(client, 'bob')
    backup = load_backup_module()

    out_dir = tmp_path / 'backups'
    path = backup.backup(app.config['DATABASE'], str(out_dir), now=datetime.datetime(2026, 11, 1, 3, 0))
    assert os.path.basename(path) == 'shadow-20261101-0300.db'

    # Restore into a fresh file and read it back
    restored = tmp_path / 'restored.db'
    src = sqlite3.connect(path)
    dst = sqlite3.connect(restored)
    src.backup(dst)
    src.close()
    names = [r[0] for r in dst.execute("SELECT username FROM accounts ORDER BY username")]
    dst.close()
    assert names == ['alice', 'bob']

def test_backup_keeps_14_newest(tmp_path):
    app = make_app(tmp_path)
    backup = load_backup_module()
    out_dir = tmp_path / 'backups'
    start = datetime.datetime(2026, 10, 1, 3, 0)
    for day in range(16):
        backup.backup(app.config['DATABASE'], str(out_dir), now=start + datetime.timedelta(days=day))
    files = sorted(os.listdir(out_dir))
    assert len(files) == 14
    assert files[0] == 'shadow-20261003-0300.db'
    assert files[-1] == 'shadow-20261016-0300.db'
