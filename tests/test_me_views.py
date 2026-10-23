import datetime
import json
import pytest
from test_privacy_matrix import XHR, World, day_str, now_iso, world  # noqa: F401

NOTE = ("This reading says behaviour is changing direction. It never states a diagnosis, "
        "a mental-health condition, or a performance judgement.")

def test_trend_shape(world):
    world.person('alice', level='my_trend')
    world.readings('alice', [10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 34, 40])
    res = world.login('alice').get('/api/me/trend?days=14')
    assert res.status_code == 200
    body = res.get_json()

    assert body['person'] == {'account_id': world.ids['alice'], 'username': 'alice'}
    assert [d['day'] for d in body['days']] == [day_str(-i) for i in range(13, -1, -1)]
    assert set(body['days'][0]) == {'day', 'drift_raw', 'drift', 'levels', 'confidence', 'baseline'}
    assert body['latest'] == body['days'][-1]
    assert body['latest']['drift'] == 40
    assert body['status'] == {'label': 'Early drift', 'band': 'early'}
    # 40 - 30 = 10 > 8
    assert body['horizon'] == '2 to 3 weeks if the trend continues'
    assert body['baseline_established'] is True
    assert body['days_observed'] == 14
    assert body['context'] == []

def test_trend_days_window(world):
    world.person('alice', level='my_trend')
    world.readings('alice', [10] * 20)
    world.login('alice')
    assert len(world.get('/api/me/trend').get_json()['days']) == 14
    assert len(world.get('/api/me/trend?days=5').get_json()['days']) == 5
    assert len(world.get('/api/me/trend?days=60').get_json()['days']) == 20

@pytest.mark.parametrize('days', ['0', '61', 'abc', '-1', '1.5'])
def test_trend_days_validation(world, days):
    world.person('alice')
    assert world.login('alice').get(f'/api/me/trend?days={days}').status_code == 400

def test_trend_empty(world):
    world.person('alice')
    body = world.login('alice').get('/api/me/trend').get_json()
    assert body['days'] == []
    assert body['latest'] is None and body['status'] is None and body['horizon'] is None
    assert body['baseline_established'] is False
    assert body['days_observed'] == 0

def test_own_data_visible_regardless_of_sharing(world):
    world.person('alice', level='nothing')
    world.readings('alice', [50] * 3)
    body = world.login('alice').get('/api/me/trend').get_json()
    assert body['days_observed'] == 3
    assert body['horizon'] == 'Not enough days yet'

def test_context_damps_drift(world):
    world.person('boss', role='manager')
    world.person('alice', level='my_trend')
    world.team('Nova', 'boss', ['alice'], context_tag='Exam week')
    world.team('Quiet', 'boss', ['alice'])
    world.readings('alice', [40, 10])
    body = world.login('alice').get('/api/me/trend').get_json()
    assert body['context'] == ['Exam week']
    assert [(d['drift_raw'], d['drift']) for d in body['days']] == [(40, 25), (10, 0)]
    assert body['status']['band'] == 'stable'

def test_revoked_devices_excluded_and_newest_device_wins(world):
    world.person('alice', level='my_trend')
    old = world.device('alice', revoked=True)
    world.readings('alice', [99] * 3, device_id=old)
    world.readings('alice', [10, 10, 10])
    later = world.device('alice')
    world.readings('alice', [30], device_id=later)  # same day as the last reading, received later
    body = world.login('alice').get('/api/me/trend').get_json()
    assert [d['drift_raw'] for d in body['days']] == [10, 10, 30]

def test_explain(world):
    world.person('alice', level='my_trend')
    lv = {'switching': 10, 'session': 30, 'checks': 20, 'screen': 20, 'steadiness': 0}
    world.readings('alice', [16], levels=[lv])
    body = world.login('alice').get('/api/me/explain').get_json()
    assert body['day'] == day_str()
    assert body['note'] == NOTE
    assert [f['key'] for f in body['factors']] == ['session', 'checks', 'screen', 'switching', 'steadiness']
    assert body['factors'][0] == {
        'key': 'session', 'label': 'Session length', 'level': 30, 'pct': 38,
        'cause': 'Your time in a single app is shorter than usual.',
    }

def test_explain_without_data(world):
    world.person('alice')
    body = world.login('alice').get('/api/me/explain').get_json()
    assert body == {'day': None, 'factors': [], 'note': NOTE}
