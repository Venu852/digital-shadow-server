import pytest
from app.db import get_db

def test_register_ok(auth):
    res = auth.register(username='User1', password='password123', role='individual')
    assert res.status_code == 201
    data = res.get_json()
    assert data['username'] == 'user1'
    assert data['role'] == 'individual'
    assert 'id' in data
    assert 'password_hash' not in data

def test_username_lowercased(auth):
    res = auth.register(username='CamelCaseUser', password='password123', role='individual')
    assert res.status_code == 201
    assert res.get_json()['username'] == 'camelcaseuser'

def test_bad_username_and_short_password(auth):
    res = auth.register(username='a', password='password123', role='individual')
    assert res.status_code == 400

    res = auth.register(username='valid_user', password='short', role='individual')
    assert res.status_code == 400

def test_duplicate_user(auth):
    auth.register(username='dupeuser', password='password123', role='individual')
    res = auth.register(username='dupeuser', password='password123', role='individual')
    assert res.status_code == 409

def test_login_ok(auth, client):
    auth.register(username='loginuser', password='password123', role='individual')
    auth.logout()

    res = auth.login(username='loginuser', password='password123')
    assert res.status_code == 200
    data = res.get_json()
    assert data['username'] == 'loginuser'
    assert 'password_hash' not in data

def test_wrong_password(auth):
    auth.register(username='wrongpassuser', password='password123', role='individual')
    auth.logout()

    res = auth.login(username='wrongpassuser', password='wrongpassword')
    assert res.status_code == 401
    assert res.get_json() == {"error": "Incorrect username or password."}

def test_lockout(auth):
    auth.register(username='lockuser', password='password123', role='individual')
    auth.logout()

    for _ in range(5):
        res = auth.login(username='lockuser', password='wrongpassword')
        assert res.status_code == 401

    # 6th attempt should be locked out
    res = auth.login(username='lockuser', password='wrongpassword')
    assert res.status_code == 429
    assert "Too many failed attempts" in res.get_json()['error']

def test_me_without_login(client):
    res = client.get('/api/me')
    assert res.status_code == 401

def test_missing_x_requested_with(client, auth):
    res = client.post(
        '/api/register',
        json={'username': 'testuser', 'password': 'password123', 'role': 'individual'}
    )
    assert res.status_code == 400

def test_stored_password_hash(app, auth):
    auth.register(username='hashuser', password='password123', role='individual')
    with app.app_context():
        db = get_db()
        user = db.execute("SELECT password_hash FROM accounts WHERE username = 'hashuser'").fetchone()
        assert user['password_hash'] != 'password123'
        assert user['password_hash'].startswith('scrypt:')

def test_no_response_contains_password_hash(auth, client):
    res = auth.register(username='nohashuser', password='password123', role='individual')
    assert 'password_hash' not in res.get_data(as_text=True)

    res = auth.login(username='nohashuser', password='password123')
    assert 'password_hash' not in res.get_data(as_text=True)

    res = client.get('/api/me')
    assert 'password_hash' not in res.get_data(as_text=True)
