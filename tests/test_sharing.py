import pytest
from app.db import get_db

XHR = {'X-Requested-With': 'XMLHttpRequest'}

def test_default_level_is_nothing(auth, client):
    auth.register(username='shareuser', password='password123', role='individual')
    res = client.get('/api/me/sharing')
    assert res.status_code == 200
    assert res.get_json() == {'level': 'nothing', 'changed_at': None}

def test_sharing_changes_are_recorded(app, auth, client):
    auth.register(username='shareuser', password='password123', role='individual')

    for level in ['team_totals', 'my_trend', 'nothing']:
        res = client.put('/api/me/sharing', json={'level': level}, headers=XHR)
        assert res.status_code == 200
        assert res.get_json()['level'] == level
        assert res.get_json()['changed_at']
        assert client.get('/api/me/sharing').get_json()['level'] == level

    with app.app_context():
        rows = get_db().execute(
            "SELECT level FROM sharing_consents ORDER BY id"
        ).fetchall()
    assert [r['level'] for r in rows] == ['team_totals', 'my_trend', 'nothing']

def test_invalid_level(auth, client):
    auth.register(username='shareuser', password='password123', role='individual')
    assert client.put('/api/me/sharing', json={'level': 'everything'}, headers=XHR).status_code == 400
    assert client.put('/api/me/sharing', json={}, headers=XHR).status_code == 400

def test_sharing_requires_login_and_xhr(auth, client):
    assert client.get('/api/me/sharing').status_code == 401
    auth.register(username='shareuser', password='password123', role='individual')
    assert client.put('/api/me/sharing', json={'level': 'my_trend'}).status_code == 400

def test_manager_has_no_sharing(auth, client):
    auth.register(username='mgrshare', password='password123', role='manager')
    assert client.get('/api/me/sharing').status_code == 403
    assert client.put('/api/me/sharing', json={'level': 'my_trend'}, headers=XHR).status_code == 403
