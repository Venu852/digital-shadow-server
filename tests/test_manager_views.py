import pytest
from test_privacy_matrix import XHR, World, day_str, now_iso, world  # noqa: F401

LEVEL_KEYS = ('switching', 'session', 'checks', 'screen', 'steadiness')

@pytest.fixture
def team(world):
    world.person('boss', role='manager')
    for name, level in [('alice', 'my_trend'), ('bob', 'my_trend'), ('cara', 'team_totals')]:
        world.person(name, level=level)
    team_id = world.team('Nova', 'boss', ['alice', 'bob', 'cara'])
    world.readings('alice', [10, 20, 30, 40])
    world.readings('bob', [11, 21, 31, 41])
    world.readings('cara', [12, 22, 32, 44])
    world.login('boss')
    return team_id

def test_overview_visible_team(world, team):
    body = world.get('/api/manager/overview').get_json()
    assert body == {'teams': [{
        'id': team, 'name': 'Nova', 'context': 'None', 'hidden': False,
        'members': 3, 'contributors': 3, 'latest_day': day_str(),
        'avg_raw': 42, 'avg': 42, 'status': {'label': 'Early drift', 'band': 'early'},
    }]}

def test_aggregate_values(world, team):
    body = world.get(f'/api/teams/{team}/aggregate').get_json()
    assert body['team'] == {'id': team, 'name': 'Nova'}
    assert body['context'] == 'None'
    assert body['hidden'] is False
    # (10+11+12)/3 = 11; (40+41+44)/3 = 41.67 -> 42
    assert [e['avg_raw'] for e in body['series']] == [11, 21, 31, 42]
    assert body['latest'] == {'day': day_str(), 'avg_raw': 42, 'avg': 42, 'contributors': 3}
    assert body['levels_avg'] == {k: 42 for k in LEVEL_KEYS}
    assert body['status'] == {'label': 'Early drift', 'band': 'early'}
    assert body['horizon'] == '2 to 3 weeks if the trend continues'

def test_aggregate_context_damp(world, team):
    res = world.client.put(f'/api/teams/{team}/settings', json={'context_tag': 'Deadline crunch'}, headers=XHR)
    assert res.status_code == 200
    body = world.get(f'/api/teams/{team}/aggregate').get_json()
    assert body['context'] == 'Deadline crunch'
    assert [(e['avg_raw'], e['avg']) for e in body['series']] == [(11, 0), (21, 6), (31, 16), (42, 27)]
    overview = world.get('/api/manager/overview').get_json()['teams'][0]
    assert (overview['avg_raw'], overview['avg']) == (42, 27)

def test_day_with_fewer_than_three_readings_is_skipped(world, team):
    # Only alice reports 5 days ago
    world.readings('alice', [80], end_offset=-5)
    body = world.get(f'/api/teams/{team}/aggregate?days=14').get_json()
    assert day_str(-5) not in [e['day'] for e in body['series']]
    assert len(body['series']) == 4

def test_aggregate_days_param(world, team):
    assert len(world.get(f'/api/teams/{team}/aggregate?days=2').get_json()['series']) == 2
    assert world.get(f'/api/teams/{team}/aggregate?days=61').status_code == 400

def test_people_and_person_views(world, team):
    body = world.get(f'/api/teams/{team}/people').get_json()
    assert body == {'people': [
        {'account_id': world.ids['alice'], 'username': 'alice'},
        {'account_id': world.ids['bob'], 'username': 'bob'},
    ]}

    trend = world.get(f"/api/teams/{team}/people/{world.ids['bob']}/trend").get_json()
    assert trend['person'] == {'account_id': world.ids['bob'], 'username': 'bob'}
    assert [d['drift_raw'] for d in trend['days']] == [11, 21, 31, 41]
    assert set(trend) == {'person', 'days', 'latest', 'status', 'horizon',
                          'baseline_established', 'days_observed', 'context'}

    explain = world.get(f"/api/teams/{team}/people/{world.ids['bob']}/explain").get_json()
    assert explain['day'] == day_str()
    assert explain['factors'][0]['cause'] == 'Switching between apps is more frequent than baseline.'

def test_person_trend_uses_team_context(world, team):
    world.client.put(f'/api/teams/{team}/settings', json={'context_tag': 'Exam week'}, headers=XHR)
    trend = world.get(f"/api/teams/{team}/people/{world.ids['alice']}/trend").get_json()
    assert trend['context'] == ['Exam week']
    assert trend['latest']['drift'] == 25

def test_settings_defaults_and_update(world, team):
    body = world.get(f'/api/teams/{team}/settings').get_json()
    assert body == {
        'human_review': True, 'context_tag': 'None',
        'context_options': ['None', 'Exam week', 'Deadline crunch', 'Product launch', 'Holiday or break'],
    }
    res = world.client.put(f'/api/teams/{team}/settings', json={'human_review': False}, headers=XHR)
    assert res.status_code == 200
    assert res.get_json()['human_review'] is False
    assert res.get_json()['context_tag'] == 'None'

    res = world.client.put(f'/api/teams/{team}/settings', json={'context_tag': 'Product launch'}, headers=XHR)
    assert res.get_json()['human_review'] is False
    assert world.get(f'/api/teams/{team}/settings').get_json()['context_tag'] == 'Product launch'

    rows = world.query("SELECT action, team_id, target_id FROM audit_log WHERE action = 'update_settings'")
    assert rows == [{'action': 'update_settings', 'team_id': team, 'target_id': None}] * 2

@pytest.mark.parametrize('body', [
    {'human_review': 'yes'},
    {'human_review': 1},
    {'context_tag': 'Party'},
    {'context_tag': None},
    {'colour': 'red'},
])
def test_settings_validation(world, team, body):
    res = world.client.put(f'/api/teams/{team}/settings', json=body, headers=XHR)
    assert res.status_code == 400
    assert world.get(f'/api/teams/{team}/settings').get_json()['context_tag'] == 'None'

def test_settings_put_requires_xhr(world, team):
    assert world.client.put(f'/api/teams/{team}/settings', json={'human_review': False}).status_code == 400
