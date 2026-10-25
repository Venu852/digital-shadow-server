import pytest
from test_privacy_matrix import XHR, World, day_str, now_iso, world  # noqa: F401

def lv(switching=0, session=0, checks=0, screen=0, night=0, timing=0):
    return {'switching': switching, 'session': session, 'checks': checks,
            'screen': screen, 'night': night, 'timing': timing}

@pytest.fixture
def team(world):
    world.person('boss', role='manager')
    for name in ('p1', 'p2', 'p3'):
        world.person(name, level='team_totals')
    team_id = world.team('Nova', 'boss', ['p1', 'p2', 'p3'])
    # Oldest to newest: two calm days, then six days at or above the threshold
    drifts = [10, 29, 30, 35, 40, 45, 50, 55]
    levels = [lv(switching=d) for d in drifts]
    levels[-1] = lv(switching=40, night=70)   # newest day: late-night use leads
    for name in ('p1', 'p2', 'p3'):
        world.readings(name, drifts, levels=levels)
    world.login('boss')
    return team_id

def get_actions(world, team_id):
    return world.get(f'/api/teams/{team_id}/actions').get_json()

def decide(world, team_id, day, decision):
    return world.client.put(f'/api/teams/{team_id}/actions/{day}', json={'decision': decision}, headers=XHR)

def test_four_newest_days_over_threshold(world, team):
    body = get_actions(world, team)
    assert body['hidden'] is False
    assert body['human_review'] is True
    assert [a['day'] for a in body['actions']] == [day_str(0), day_str(-1), day_str(-2), day_str(-3)]
    assert [a['drift'] for a in body['actions']] == [55, 50, 45, 40]
    assert body['actions'][0] == {
        'day': day_str(), 'drift': 55, 'signal': 'night', 'signal_label': 'Late-night use',
        'action': 'Avoid late-evening requests and deadlines; keep after-hours messages to a minimum.',
        'status': 'pending', 'decision': None,
    }
    assert body['actions'][1]['signal'] == 'switching'
    assert body['actions'][1]['action'] == 'Reduce parallel tasks so people can stay with one thing longer.'

def test_threshold_is_inclusive_and_uses_damped_avg(world, team):
    world.client.put(f'/api/teams/{team}/settings', json={'context_tag': 'Exam week'}, headers=XHR)
    # Damped: 55->40, 50->35, 45->30, 40->25: only three days remain at or above 30
    body = get_actions(world, team)
    assert [a['drift'] for a in body['actions']] == [40, 35, 30]

def test_approve_and_dismiss(world, team):
    res = decide(world, team, day_str(), 'approved')
    assert res.status_code == 200
    assert res.get_json() == {'day': day_str(), 'decision': 'approved'}
    assert decide(world, team, day_str(-1), 'dismissed').status_code == 200

    actions = get_actions(world, team)['actions']
    assert [(a['status'], a['decision']) for a in actions] == [
        ('approved', 'approved'), ('dismissed', 'dismissed'), ('pending', None), ('pending', None)]

    # A decision can be changed
    assert decide(world, team, day_str(), 'dismissed').status_code == 200
    assert get_actions(world, team)['actions'][0]['status'] == 'dismissed'

    rows = world.query("SELECT actor_id, team_id, detail FROM audit_log WHERE action = 'decide_action'")
    assert len(rows) == 3
    assert rows[0]['actor_id'] == world.ids['boss'] and rows[0]['team_id'] == team

def test_bad_decision_400(world, team):
    assert decide(world, team, day_str(), 'maybe').status_code == 400
    assert world.client.put(f'/api/teams/{team}/actions/{day_str()}', json={}, headers=XHR).status_code == 400

def test_non_action_day_404(world, team):
    assert decide(world, team, day_str(-7), 'approved').status_code == 404   # calm day
    assert decide(world, team, day_str(-4), 'approved').status_code == 404   # over threshold but not in the newest 4
    assert decide(world, team, 'not-a-day', 'approved').status_code == 404

def test_human_review_off(world, team):
    world.client.put(f'/api/teams/{team}/settings', json={'human_review': False}, headers=XHR)
    body = get_actions(world, team)
    assert body['human_review'] is False
    assert {a['status'] for a in body['actions']} == {'applied'}
    assert decide(world, team, day_str(), 'approved').status_code == 404

def test_hidden_team_has_no_actions(world, team):
    world.set_level('p3', 'nothing')
    body = get_actions(world, team)
    assert body['hidden'] is True
    assert body['actions'] == []
    assert decide(world, team, day_str(), 'approved').status_code == 404
