import pytest

def test_manager_creates_team(auth, client):
    auth.register(username='mgr1', password='password123', role='manager')

    res = client.post(
        '/api/teams',
        json={'name': 'Engineering'},
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    assert res.status_code == 201
    data = res.get_json()
    assert data['name'] == 'Engineering'
    assert 'invite_code' in data
    assert len(data['invite_code']) == 8

def test_individual_cannot_create_team(auth, client):
    auth.register(username='ind1', password='password123', role='individual')

    res = client.post(
        '/api/teams',
        json={'name': 'Engineering'},
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    assert res.status_code == 403

def test_individual_joins_and_case_insensitive(auth, client):
    auth.register(username='mgr2', password='password123', role='manager')
    res = client.post(
        '/api/teams',
        json={'name': 'Product'},
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    code = res.get_json()['invite_code']

    auth.register(username='ind2', password='password123', role='individual')

    # Join using lower-case code
    res = client.post(
        '/api/teams/join',
        json={'invite_code': code.lower()},
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    assert res.status_code == 200
    assert res.get_json()['name'] == 'Product'

def test_manager_cannot_join(auth, client):
    auth.register(username='mgr3', password='password123', role='manager')
    res = client.post(
        '/api/teams',
        json={'name': 'Sales'},
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    code = res.get_json()['invite_code']

    auth.register(username='mgr4', password='password123', role='manager')
    res = client.post(
        '/api/teams/join',
        json={'invite_code': code},
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    assert res.status_code == 403

def test_duplicate_join(auth, client):
    auth.register(username='mgr5', password='password123', role='manager')
    res = client.post(
        '/api/teams',
        json={'name': 'Marketing'},
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    code = res.get_json()['invite_code']

    auth.register(username='ind3', password='password123', role='individual')
    client.post(
        '/api/teams/join',
        json={'invite_code': code},
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )

    res = client.post(
        '/api/teams/join',
        json={'invite_code': code},
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    assert res.status_code == 409

def test_leave_works(auth, client):
    auth.register(username='mgr6', password='password123', role='manager')
    res = client.post(
        '/api/teams',
        json={'name': 'Support'},
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    team_id = res.get_json()['id']
    code = res.get_json()['invite_code']

    auth.register(username='ind4', password='password123', role='individual')
    client.post(
        '/api/teams/join',
        json={'invite_code': code},
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )

    res = client.delete(
        f'/api/teams/{team_id}/membership',
        headers={'X-Requested-With': 'XMLHttpRequest'},
        json={}
    )
    assert res.status_code == 204

def test_rotated_code_invalidates_old_one(auth, client):
    auth.register(username='mgr7', password='password123', role='manager')
    res = client.post(
        '/api/teams',
        json={'name': 'Design'},
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    team_id = res.get_json()['id']
    old_code = res.get_json()['invite_code']

    # Rotate code
    res = client.post(
        f'/api/teams/{team_id}/invite/rotate',
        headers={'X-Requested-With': 'XMLHttpRequest'},
        json={}
    )
    assert res.status_code == 200
    new_code = res.get_json()['invite_code']
    assert old_code != new_code

    auth.register(username='ind5', password='password123', role='individual')

    # Old code fails
    res = client.post(
        '/api/teams/join',
        json={'invite_code': old_code},
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    assert res.status_code == 404

    # New code works
    res = client.post(
        '/api/teams/join',
        json={'invite_code': new_code},
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    assert res.status_code == 200

def test_individual_team_list_never_contains_invite_code(auth, client):
    auth.register(username='mgr8', password='password123', role='manager')
    res = client.post(
        '/api/teams',
        json={'name': 'QA'},
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )
    code = res.get_json()['invite_code']

    auth.register(username='ind6', password='password123', role='individual')
    client.post(
        '/api/teams/join',
        json={'invite_code': code},
        headers={'X-Requested-With': 'XMLHttpRequest'}
    )

    res = client.get('/api/teams')
    assert res.status_code == 200
    teams = res.get_json()
    assert len(teams) == 1
    assert 'invite_code' not in teams[0]
    assert 'member_count' not in teams[0]
