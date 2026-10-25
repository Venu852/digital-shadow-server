import datetime
import re
import pytest
from app.db import get_db

XHR = {'X-Requested-With': 'XMLHttpRequest'}

def pair(client, username='phoneuser', password='password123', device_name='Pixel'):
    return client.post(
        '/api/devices/pair',
        json={'username': username, 'password': password, 'device_name': device_name}
    )

def bearer(token):
    return {'Authorization': f'Bearer {token}'}

def test_pair_ok_and_token_not_stored_plain(app, auth, client):
    auth.register(username='phoneuser', password='password123', role='individual')
    res = pair(client)
    assert res.status_code == 201
    data = res.get_json()
    assert re.fullmatch(r'[0-9a-f]{32}', data['device_id'])
    token = data['device_token']

    with app.app_context():
        row = get_db().execute(
            "SELECT token_hash FROM devices WHERE id = ?", (data['device_id'],)
        ).fetchone()
    assert row['token_hash'] != token
    assert re.fullmatch(r'[0-9a-f]{64}', row['token_hash'])

    res = client.get('/api/device/me', headers=bearer(token))
    assert res.status_code == 200
    assert res.get_json() == {
        'device_id': data['device_id'], 'username': 'phoneuser', 'sharing_level': 'nothing'
    }

def test_pair_device_name_length(auth, client):
    auth.register(username='phoneuser', password='password123', role='individual')
    assert pair(client, device_name='').status_code == 400
    assert pair(client, device_name='x' * 41).status_code == 400
    assert pair(client, device_name='x' * 40).status_code == 201

def test_pair_wrong_password_shares_lockout_with_login(auth, client):
    auth.register(username='phoneuser', password='password123', role='individual')
    auth.logout()

    for _ in range(3):
        assert pair(client, password='wrongpassword').status_code == 401
    for _ in range(2):
        assert auth.login(username='phoneuser', password='wrongpassword').status_code == 401

    # Five failures across both routes lock out both
    assert pair(client).status_code == 429
    assert auth.login(username='phoneuser', password='password123').status_code == 429

def test_manager_cannot_pair(auth, client):
    auth.register(username='mgrphone', password='password123', role='manager')
    assert pair(client, username='mgrphone').status_code == 403

def test_device_routes_require_token(auth, client):
    auth.register(username='phoneuser', password='password123', role='individual')
    assert client.get('/api/device/me').status_code == 401
    assert client.get('/api/device/me', headers=bearer('not-a-real-token')).status_code == 401
    assert client.get('/api/device/me', headers={'Authorization': 'Basic abc'}).status_code == 401

def test_revoked_token_is_rejected(auth, client):
    auth.register(username='phoneuser', password='password123', role='individual')
    data = pair(client).get_json()

    res = client.delete(f"/api/devices/{data['device_id']}", headers=XHR, json={})
    assert res.status_code == 204
    assert client.get('/api/device/me', headers=bearer(data['device_token'])).status_code == 401

def test_list_devices_shows_only_own(auth, client):
    auth.register(username='alice', password='password123', role='individual')
    pair(client, username='alice', device_name='Alice phone')
    auth.register(username='bob', password='password123', role='individual')
    pair(client, username='bob', device_name='Bob phone')

    res = client.get('/api/devices')
    assert res.status_code == 200
    devices = res.get_json()
    assert [d['name'] for d in devices] == ['Bob phone']
    assert set(devices[0]) == {'id', 'name', 'created_at', 'last_seen_at', 'revoked'}
    assert devices[0]['revoked'] is False

def test_cannot_revoke_someone_elses_device(auth, client):
    auth.register(username='alice', password='password123', role='individual')
    alice = pair(client, username='alice').get_json()
    auth.register(username='bob', password='password123', role='individual')

    res = client.delete(f"/api/devices/{alice['device_id']}", headers=XHR, json={})
    assert res.status_code == 404
    assert client.delete('/api/devices/unknown', headers=XHR, json={}).status_code == 404
    # Alice's device still works
    assert client.get('/api/device/me', headers=bearer(alice['device_token'])).status_code == 200

def test_manager_cannot_list_devices(auth, client):
    auth.register(username='mgrlist', password='password123', role='manager')
    assert client.get('/api/devices').status_code == 403

def test_cookie_device_routes_keep_xhr_check(auth, client):
    auth.register(username='phoneuser', password='password123', role='individual')
    data = pair(client).get_json()
    assert client.delete(f"/api/devices/{data['device_id']}", json={}).status_code == 400

def test_token_routes_ignore_cookies(auth, client):
    auth.register(username='alice', password='password123', role='individual')
    alice = pair(client, username='alice').get_json()
    # Logged in as bob via cookie, but using alice's token
    auth.register(username='bob', password='password123', role='individual')

    res = client.get('/api/device/me', headers=bearer(alice['device_token']))
    assert res.get_json()['username'] == 'alice'
    # The bob cookie alone is not enough
    assert client.get('/api/device/me').status_code == 401
    assert client.delete('/api/device/data', json={}).status_code == 401

def test_device_rate_limit(auth, client):
    auth.register(username='phoneuser', password='password123', role='individual')
    token = pair(client).get_json()['device_token']
    for _ in range(300):
        assert client.get('/api/device/me', headers=bearer(token)).status_code == 200
    assert client.get('/api/device/me', headers=bearer(token)).status_code == 429

def test_no_response_contains_hashes(auth, client):
    auth.register(username='phoneuser', password='password123', role='individual')
    responses = [pair(client)]
    data = responses[0].get_json()
    responses.append(client.get('/api/devices'))
    responses.append(client.get('/api/device/me', headers=bearer(data['device_token'])))
    responses.append(client.get('/api/me/sharing'))
    for res in responses:
        body = res.get_data(as_text=True)
        assert 'token_hash' not in body
        assert 'password_hash' not in body

def test_device_sharing_sets_level_and_records_changes_only(app, auth, client):
    auth.register(username='phoneuser', password='password123', role='individual')
    token = pair(client).get_json()['device_token']
    auth.logout()

    # First explicit choice adds a row even when it matches the default
    for level in ['nothing', 'nothing', 'team_totals', 'team_totals', 'my_trend']:
        res = client.put('/api/device/sharing', json={'level': level}, headers=bearer(token))
        assert res.status_code == 200
        assert res.get_json()['level'] == level
        assert res.get_json()['changed_at']
        assert client.get('/api/device/me', headers=bearer(token)).get_json()['sharing_level'] == level

    with app.app_context():
        rows = get_db().execute("SELECT level FROM sharing_consents ORDER BY id").fetchall()
    assert [r['level'] for r in rows] == ['nothing', 'team_totals', 'my_trend']

def test_device_sharing_unchanged_returns_current_row(auth, client):
    auth.register(username='phoneuser', password='password123', role='individual')
    token = pair(client).get_json()['device_token']
    first = client.put('/api/device/sharing', json={'level': 'my_trend'}, headers=bearer(token)).get_json()
    again = client.put('/api/device/sharing', json={'level': 'my_trend'}, headers=bearer(token)).get_json()
    assert again == first
    # Matches what the cookie route reports
    assert client.get('/api/me/sharing').get_json() == first

def test_device_sharing_invalid_level(auth, client):
    auth.register(username='phoneuser', password='password123', role='individual')
    token = pair(client).get_json()['device_token']
    for body in [{'level': 'everything'}, {}, {'level': None}, []]:
        res = client.put('/api/device/sharing', json=body, headers=bearer(token))
        assert res.status_code == 400
        assert res.get_json() == {'error': 'Invalid sharing level'}
    assert client.get('/api/device/me', headers=bearer(token)).get_json()['sharing_level'] == 'nothing'

def test_device_sharing_needs_token_not_cookie_or_xhr(auth, client):
    auth.register(username='phoneuser', password='password123', role='individual')
    data = pair(client).get_json()
    # Cookie (with XHR) is not enough
    res = client.put('/api/device/sharing', json={'level': 'my_trend'}, headers=XHR)
    assert res.status_code == 401
    # Token without X-Requested-With is accepted
    res = client.put('/api/device/sharing', json={'level': 'my_trend'}, headers=bearer(data['device_token']))
    assert res.status_code == 200

    client.delete(f"/api/devices/{data['device_id']}", headers=XHR, json={})
    res = client.put('/api/device/sharing', json={'level': 'nothing'}, headers=bearer(data['device_token']))
    assert res.status_code == 401

def test_device_sharing_nothing_stops_uploads(auth, client):
    auth.register(username='phoneuser', password='password123', role='individual')
    token = pair(client).get_json()['device_token']
    body = {
        'drift': 34, 'confidence': 76, 'baseline': 'established', 'tz': '+05:30',
        'levels': {'switching': 55, 'session': 40, 'checks': 35,
                   'screen': 30, 'night': 20, 'timing': 25},
    }
    day = datetime.datetime.now(datetime.UTC).date().isoformat()

    client.put('/api/device/sharing', json={'level': 'team_totals'}, headers=bearer(token))
    assert client.put(f'/api/device/days/{day}', json=body, headers=bearer(token)).status_code == 200
    client.put('/api/device/sharing', json={'level': 'nothing'}, headers=bearer(token))
    res = client.put(f'/api/device/days/{day}', json=body, headers=bearer(token))
    assert res.status_code == 403
    assert res.get_json() == {'error': 'sharing is off'}
