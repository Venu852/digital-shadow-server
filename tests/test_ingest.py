import datetime
import json
import pytest
from app.db import get_db

XHR = {'X-Requested-With': 'XMLHttpRequest'}

def today():
    return datetime.datetime.now(datetime.UTC).date()

def day_str(offset=0):
    return (today() + datetime.timedelta(days=offset)).isoformat()

def summary(**overrides):
    body = {
        'drift': 20,
        'levels': {'switching': 18, 'session': 22, 'checks': 20, 'screen': 19, 'steadiness': 21},
        'confidence': 70,
        'baseline': 'established',
        'forecast': {'screen_min': 210, 'usual_min': 190},
        'unusual_hours': [1, 2],
        'tz': '+05:30',
    }
    body.update(overrides)
    return body

def setup_device(auth, client, username='ingestuser', level='my_trend'):
    auth.register(username=username, password='password123', role='individual')
    if level is not None:
        client.put('/api/me/sharing', json={'level': level}, headers=XHR)
    res = client.post(
        '/api/devices/pair',
        json={'username': username, 'password': 'password123', 'device_name': 'Phone'}
    )
    data = res.get_json()
    return data['device_id'], {'Authorization': f"Bearer {data['device_token']}"}

def upload(client, headers, day=None, body=None):
    return client.put(f'/api/device/days/{day or day_str()}', json=body or summary(), headers=headers)

def count_rows(app):
    with app.app_context():
        return get_db().execute("SELECT COUNT(*) FROM daily_summaries").fetchone()[0]

def test_upload_ok_without_xhr_header(app, auth, client):
    _, headers = setup_device(auth, client)
    res = upload(client, headers)
    assert res.status_code == 200
    assert res.get_json() == {'stored': True, 'updated': False}
    assert count_rows(app) == 1

def test_upload_without_or_bad_token(app, auth, client):
    setup_device(auth, client)
    assert upload(client, {}).status_code == 401
    assert upload(client, {'Authorization': 'Bearer wrong'}).status_code == 401
    assert count_rows(app) == 0

def test_upload_with_revoked_token(app, auth, client):
    device_id, headers = setup_device(auth, client)
    client.delete(f'/api/devices/{device_id}', headers=XHR, json={})
    assert upload(client, headers).status_code == 401
    assert count_rows(app) == 0

@pytest.mark.parametrize('level', ['nothing', None])
def test_sharing_off_refuses_upload(app, auth, client, level):
    _, headers = setup_device(auth, client, level=level)
    res = upload(client, headers)
    assert res.status_code == 403
    assert res.get_json() == {'error': 'sharing is off'}
    assert count_rows(app) == 0

def test_reupload_is_idempotent(app, auth, client):
    device_id, headers = setup_device(auth, client)
    assert upload(client, headers, body=summary(drift=20)).get_json()['updated'] is False
    res = upload(client, headers, body=summary(drift=55, baseline='calibrating'))
    assert res.get_json() == {'stored': True, 'updated': True}

    with app.app_context():
        rows = get_db().execute(
            "SELECT drift, baseline FROM daily_summaries WHERE device_id = ?", (device_id,)
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]['drift'] == 55
    assert rows[0]['baseline'] == 'calibrating'

def test_optional_fields_can_be_omitted(app, auth, client):
    _, headers = setup_device(auth, client)
    body = summary()
    for key in ('forecast', 'unusual_hours', 'tz'):
        del body[key]
    assert upload(client, headers, body=body).status_code == 200

def bad_levels(change):
    levels = dict(summary()['levels'])
    change(levels)
    return levels

@pytest.mark.parametrize('body', [
    summary(drift=101),
    summary(drift=-1),
    summary(drift=True),
    summary(drift='20'),
    summary(levels=bad_levels(lambda l: l.pop('screen'))),
    summary(levels=bad_levels(lambda l: l.update(apps=5))),
    summary(levels=bad_levels(lambda l: l.update(screen=101))),
    summary(app_names=['chat']),
    summary(confidence=101),
    summary(baseline='unknown'),
    summary(forecast={'screen_min': -1, 'usual_min': 10}),
    summary(forecast={'screen_min': 1}),
    summary(unusual_hours=[24]),
    summary(unusual_hours=[1, 1]),
    summary(unusual_hours=list(range(24)) + [0]),
    summary(tz='Asia/Kolkata'),
    {k: v for k, v in summary().items() if k != 'drift'},
])
def test_invalid_body(app, auth, client, body):
    _, headers = setup_device(auth, client)
    assert upload(client, headers, body=body).status_code == 400
    assert count_rows(app) == 0

@pytest.mark.parametrize('day', [
    'not-a-day', '2026-02-30', '20261010', day_str(2), day_str(-401),
])
def test_invalid_day(app, auth, client, day):
    _, headers = setup_device(auth, client)
    assert upload(client, headers, day=day).status_code == 400
    assert count_rows(app) == 0

def test_day_bounds_accepted(auth, client):
    _, headers = setup_device(auth, client)
    assert upload(client, headers, day=day_str(1)).status_code == 200
    assert upload(client, headers, day=day_str(-400)).status_code == 200

def test_oversized_body(app, auth, client):
    _, headers = setup_device(auth, client)
    body = json.dumps(summary()) + ' ' * 4096
    res = client.put(
        f'/api/device/days/{day_str()}', data=body,
        headers={**headers, 'Content-Type': 'application/json'}
    )
    assert res.status_code == 413
    assert 'error' in res.get_json()
    assert count_rows(app) == 0

def test_delete_my_data(app, auth, client):
    _, headers = setup_device(auth, client)
    upload(client, headers, day=day_str(0))
    upload(client, headers, day=day_str(-1))
    # Another account's data survives
    _, other = setup_device(auth, client, username='otheruser')
    upload(client, other)
    assert count_rows(app) == 3

    # Cookie now belongs to otheruser
    assert client.delete('/api/me/data', headers=XHR, json={}).status_code == 204
    assert count_rows(app) == 2

def test_delete_device_data(app, auth, client):
    _, headers = setup_device(auth, client)
    upload(client, headers, day=day_str(0))
    upload(client, headers, day=day_str(-1))
    _, other = setup_device(auth, client, username='otheruser')
    upload(client, other)

    assert client.delete('/api/device/data', headers=headers, json={}).status_code == 204
    assert count_rows(app) == 1

def test_upload_response_has_no_hashes(auth, client):
    _, headers = setup_device(auth, client)
    body = upload(client, headers).get_data(as_text=True)
    assert 'token_hash' not in body
    assert 'password_hash' not in body
