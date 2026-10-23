import pytest
from test_privacy_matrix import XHR, PASSWORD, World, day_str, now_iso, world  # noqa: F401

@pytest.fixture
def team(world):
    world.person('boss', role='manager')
    for name in ('alice', 'bob', 'cara'):
        world.person(name, level='my_trend')
        world.readings(name, [20] * 3)
    return world.team('Nova', 'boss', ['alice', 'bob', 'cara'])

def test_access_log_shows_views_of_my_trend(world, team):
    world.login('boss')
    world.get(f"/api/teams/{team}/people/{world.ids['alice']}/trend")
    world.get(f"/api/teams/{team}/people/{world.ids['alice']}/explain")
    world.get(f"/api/teams/{team}/people/{world.ids['bob']}/trend")
    world.client.put(f'/api/teams/{team}/settings', json={'context_tag': 'Exam week'}, headers=XHR)

    log = world.login('alice').get('/api/me/access-log').get_json()
    assert [(e['by'], e['action'], e['team']) for e in log] == [
        ('boss', 'view_explain', 'Nova'), ('boss', 'view_trend', 'Nova')]
    assert set(log[0]) == {'at', 'by', 'action', 'team'}
    assert log[0]['at'] >= log[1]['at']

    assert len(world.login('bob').get('/api/me/access-log').get_json()) == 1
    assert world.login('cara').get('/api/me/access-log').get_json() == []

def test_refused_view_is_not_logged(world, team):
    world.set_level('alice', 'team_totals')
    world.login('boss')
    assert world.get(f"/api/teams/{team}/people/{world.ids['alice']}/trend").status_code == 404
    assert world.query("SELECT * FROM audit_log") == []

def test_access_log_limit(world, team):
    world.login('boss')
    for _ in range(5):
        world.get(f"/api/teams/{team}/people/{world.ids['alice']}/trend")
    world.login('alice')
    assert len(world.get('/api/me/access-log?limit=2').get_json()) == 2
    assert world.get('/api/me/access-log?limit=0').status_code == 400
    assert world.get('/api/me/access-log?limit=201').status_code == 400
    assert world.get('/api/me/access-log?limit=200').status_code == 200

def delete_me(world, password=PASSWORD, headers=XHR):
    return world.client.delete('/api/me', json={'password': password}, headers=headers)

def test_delete_individual(world, team):
    world.login('boss')
    world.get(f"/api/teams/{team}/people/{world.ids['alice']}/trend")
    alice = world.ids['alice']

    world.login('alice')
    assert delete_me(world, password='wrongpassword').status_code == 401
    assert delete_me(world, headers={}).status_code == 400
    assert world.get('/api/me').status_code == 200

    assert delete_me(world).status_code == 204
    assert world.get('/api/me').status_code == 401

    for table, column in [('accounts', 'id'), ('devices', 'account_id'), ('sharing_consents', 'account_id'),
                          ('memberships', 'account_id'), ('audit_log', 'target_id')]:
        assert world.query(f"SELECT * FROM {table} WHERE {column} = ?", (alice,)) == [], table
    assert world.query(
        "SELECT * FROM daily_summaries WHERE device_id NOT IN (SELECT id FROM devices)") == []
    assert len(world.query("SELECT * FROM daily_summaries")) == 6

    res = world.client.post('/api/login', json={'username': 'alice', 'password': PASSWORD}, headers=XHR)
    assert res.status_code == 401

def test_delete_manager(world, team):
    world.login('boss')
    world.client.put(f'/api/teams/{team}/settings', json={'context_tag': 'Exam week'}, headers=XHR)
    world.get(f"/api/teams/{team}/people/{world.ids['alice']}/trend")
    assert delete_me(world).status_code == 204

    assert world.query("SELECT * FROM accounts WHERE username = 'boss'") == []
    assert world.query("SELECT * FROM teams") == []
    assert world.query("SELECT * FROM memberships") == []
    assert world.query("SELECT * FROM team_settings") == []
    # Members keep their accounts and data
    assert len(world.query("SELECT * FROM accounts")) == 3
    assert len(world.query("SELECT * FROM daily_summaries")) == 9

    # The view stays in alice's log, but the deleted viewer and team are no longer named
    log = world.login('alice').get('/api/me/access-log').get_json()
    assert [(e['by'], e['action'], e['team']) for e in log] == [(None, 'view_trend', None)]

def test_delete_manager_with_decisions(world):
    world.person('boss', role='manager')
    for name in ('p1', 'p2', 'p3'):
        world.person(name, level='team_totals')
        world.readings(name, [50] * 3)
    team_id = world.team('Nova', 'boss', ['p1', 'p2', 'p3'])
    world.login('boss')
    res = world.client.put(f'/api/teams/{team_id}/actions/{day_str()}', json={'decision': 'approved'}, headers=XHR)
    assert res.status_code == 200
    assert delete_me(world).status_code == 204
    assert world.query("SELECT * FROM action_decisions") == []
