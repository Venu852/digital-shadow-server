"""Who can see what. Also defines the World helper the other Phase 3 test modules import."""
import datetime
import json
import secrets
import uuid
import pytest
from werkzeug.security import generate_password_hash
from app.db import get_db

XHR = {'X-Requested-With': 'XMLHttpRequest'}
PASSWORD = 'password123'
# A cheap hash keeps account setup fast; login accepts any werkzeug hash method
FAST_HASH = generate_password_hash(PASSWORD, method='pbkdf2:sha256:1000')

def now_iso():
    return datetime.datetime.now(datetime.UTC).isoformat()

def day_str(offset=0):
    return (datetime.datetime.now(datetime.UTC).date() + datetime.timedelta(days=offset)).isoformat()

class World:
    """Builds accounts, teams and readings straight in the database, then calls the API."""

    def __init__(self, app, client):
        self.app = app
        self.client = client
        self.ids = {}

    def db(self, sql, params=()):
        with self.app.app_context():
            db = get_db()
            cursor = db.execute(sql, params)
            db.commit()
            return cursor

    def query(self, sql, params=()):
        with self.app.app_context():
            return [dict(r) for r in get_db().execute(sql, params).fetchall()]

    def person(self, username, role='individual', level=None):
        cursor = self.db(
            "INSERT INTO accounts (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (username, FAST_HASH, role, now_iso())
        )
        self.ids[username] = cursor.lastrowid
        if level:
            self.set_level(username, level)
        return cursor.lastrowid

    def set_level(self, username, level):
        self.db(
            "INSERT INTO sharing_consents (account_id, level, changed_at) VALUES (?, ?, ?)",
            (self.ids[username], level, now_iso())
        )

    def team(self, name, manager, members=(), context_tag=None, human_review=None):
        cursor = self.db(
            "INSERT INTO teams (name, manager_id, invite_code, created_at) VALUES (?, ?, ?, ?)",
            (name, self.ids[manager], secrets.token_hex(4).upper(), now_iso())
        )
        team_id = cursor.lastrowid
        self.ids[name] = team_id
        for member in members:
            self.db("INSERT INTO memberships (team_id, account_id, joined_at) VALUES (?, ?, ?)",
                    (team_id, self.ids[member], now_iso()))
        if context_tag is not None or human_review is not None:
            self.db("INSERT INTO team_settings (team_id, human_review, context_tag, updated_at) VALUES (?, ?, ?, ?)",
                    (team_id, int(human_review if human_review is not None else True),
                     context_tag or 'None', now_iso()))
        return team_id

    def device(self, username, revoked=False):
        device_id = uuid.uuid4().hex
        self.db(
            "INSERT INTO devices (id, account_id, name, token_hash, created_at, revoked_at) VALUES (?, ?, ?, ?, ?, ?)",
            (device_id, self.ids[username], 'Phone', secrets.token_hex(32), now_iso(),
             now_iso() if revoked else None)
        )
        return device_id

    def readings(self, username, drifts, levels=None, device_id=None, end_offset=0):
        """One reading per drift value, the last one on today + end_offset."""
        device_id = device_id or self.device(username)
        for i, drift in enumerate(drifts):
            lv = levels[i] if levels else {k: drift for k in
                                            ('switching', 'session', 'checks', 'screen', 'night', 'timing')}
            self.db(
                """INSERT OR REPLACE INTO daily_summaries
                   (device_id, day, drift, levels_json, confidence, baseline, received_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (device_id, day_str(end_offset - (len(drifts) - 1 - i)), drift, json.dumps(lv), 60,
                 'established' if i >= 6 else 'calibrating', now_iso())
            )
        return device_id

    def login(self, username):
        res = self.client.post('/api/login', json={'username': username, 'password': PASSWORD}, headers=XHR)
        assert res.status_code == 200
        return self

    def get(self, path):
        return self.client.get(path)

@pytest.fixture
def world(app, client):
    return World(app, client)

@pytest.fixture
def nova(world):
    """Team with alice/bob (my_trend), cara (team_totals), dan (nothing); all with 14 days."""
    world.person('boss', role='manager')
    world.person('alice', level='my_trend')
    world.person('bob', level='my_trend')
    world.person('cara', level='team_totals')
    world.person('dan', level='nothing')
    team_id = world.team('Nova', 'boss', ['alice', 'bob', 'cara', 'dan'])
    world.readings('alice', [10] * 14)
    world.readings('bob', [20] * 14)
    world.readings('cara', [30] * 14)
    world.readings('dan', [90] * 14)
    world.login('boss')
    return team_id

def aggregate(world, team_id):
    return world.get(f'/api/teams/{team_id}/aggregate')

def people(world, team_id):
    return [p['username'] for p in world.get(f'/api/teams/{team_id}/people').get_json()['people']]

def test_nothing_never_contributes_or_appears(world, nova):
    agg = aggregate(world, nova).get_json()
    assert agg['latest']['contributors'] == 3
    # dan's 90 would raise the mean above 20
    assert agg['latest']['avg_raw'] == 20
    assert 'dan' not in people(world, nova)
    assert world.get(f"/api/teams/{nova}/people/{world.ids['dan']}/trend").status_code == 404

def test_team_totals_contributes_but_trend_is_404(world, nova):
    assert 'cara' not in people(world, nova)
    assert world.get(f"/api/teams/{nova}/people/{world.ids['cara']}/trend").status_code == 404
    assert world.get(f"/api/teams/{nova}/people/{world.ids['cara']}/explain").status_code == 404

def test_my_trend_contributes_and_is_visible(world, nova):
    assert people(world, nova) == ['alice', 'bob']
    res = world.get(f"/api/teams/{nova}/people/{world.ids['alice']}/trend")
    assert res.status_code == 200
    assert len(res.get_json()['days']) == 14

def test_switching_to_nothing_removes_person_immediately(world, nova, client):
    alice = world.ids['alice']
    assert world.get(f'/api/teams/{nova}/people/{alice}/trend').status_code == 200

    world.login('alice')
    assert client.put('/api/me/sharing', json={'level': 'nothing'}, headers=XHR).status_code == 200
    world.login('boss')

    assert 'alice' not in people(world, nova)
    assert world.get(f'/api/teams/{nova}/people/{alice}/trend').status_code == 404
    assert world.get(f'/api/teams/{nova}/people/{alice}/explain').status_code == 404
    # bob and cara are left: below the minimum group, so the team is hidden
    agg = aggregate(world, nova).get_json()
    assert agg['hidden'] is True
    assert agg['series'] == []

def test_withdrawal_with_enough_others_recomputes_aggregate(world, nova):
    world.person('erin', level='my_trend')
    world.db("INSERT INTO memberships (team_id, account_id, joined_at) VALUES (?, ?, ?)",
             (nova, world.ids['erin'], now_iso()))
    world.readings('erin', [40] * 14)
    assert aggregate(world, nova).get_json()['latest'] == {
        'day': day_str(), 'avg_raw': 25, 'avg': 25, 'contributors': 4}

    world.set_level('erin', 'nothing')
    assert aggregate(world, nova).get_json()['latest']['contributors'] == 3
    assert aggregate(world, nova).get_json()['latest']['avg_raw'] == 20

def test_manager_of_another_team_gets_404(world, nova):
    world.person('other_boss', role='manager')
    world.login('other_boss')
    alice = world.ids['alice']
    for path in [
        f'/api/teams/{nova}/aggregate',
        f'/api/teams/{nova}/people',
        f'/api/teams/{nova}/people/{alice}/trend',
        f'/api/teams/{nova}/people/{alice}/explain',
        f'/api/teams/{nova}/actions',
        f'/api/teams/{nova}/settings',
    ]:
        assert world.get(path).status_code == 404, path
    res = world.client.put(f'/api/teams/{nova}/settings', json={'context_tag': 'Exam week'}, headers=XHR)
    assert res.status_code == 404
    res = world.client.put(f'/api/teams/{nova}/actions/{day_str()}', json={'decision': 'approved'}, headers=XHR)
    assert res.status_code == 404
    assert world.get('/api/manager/overview').get_json() == {'teams': []}

def test_person_trend_requires_membership_of_this_team(world, nova):
    world.person('outsider', level='my_trend')
    world.readings('outsider', [50] * 14)
    assert world.get(f"/api/teams/{nova}/people/{world.ids['outsider']}/trend").status_code == 404
    assert world.get(f'/api/teams/{nova}/people/999999/trend').status_code == 404

def test_individuals_403_on_manager_routes(world, nova):
    world.login('alice')
    for path in [
        '/api/manager/overview',
        f'/api/teams/{nova}/aggregate',
        f'/api/teams/{nova}/people',
        f"/api/teams/{nova}/people/{world.ids['bob']}/trend",
        f"/api/teams/{nova}/people/{world.ids['bob']}/explain",
        f'/api/teams/{nova}/actions',
        f'/api/teams/{nova}/settings',
    ]:
        assert world.get(path).status_code == 403, path

def test_managers_403_on_self_routes(world, nova):
    for path in ['/api/me/trend', '/api/me/explain', '/api/me/access-log']:
        assert world.get(path).status_code == 403, path

def test_unauthenticated_401(client):
    for path in ['/api/me/trend', '/api/manager/overview', '/api/teams/1/aggregate']:
        assert client.get(path).status_code == 401

NUMERIC_TEAM_FIELDS = ('members', 'contributors', 'latest_day', 'avg_raw', 'avg', 'status')

def two_sharing_team(world):
    world.person('boss', role='manager')
    world.person('p1', level='my_trend')
    world.person('p2', level='team_totals')
    world.person('p3', level='nothing')
    team_id = world.team('Small', 'boss', ['p1', 'p2', 'p3'])
    for name in ('p1', 'p2', 'p3'):
        world.readings(name, [60] * 14)
    world.login('boss')
    return team_id

def test_two_sharing_members_shows_no_numbers(world):
    team_id = two_sharing_team(world)

    team = world.get('/api/manager/overview').get_json()['teams'][0]
    assert team['hidden'] is True
    assert set(team) == {'id', 'name', 'context', 'hidden', *NUMERIC_TEAM_FIELDS}
    assert all(team[f] is None for f in NUMERIC_TEAM_FIELDS)

    agg = aggregate(world, team_id).get_json()
    assert agg['hidden'] is True
    assert agg['series'] == []
    assert all(agg[f] is None for f in ('latest', 'levels_avg', 'status', 'horizon'))

    actions = world.get(f'/api/teams/{team_id}/actions').get_json()
    assert actions['hidden'] is True
    assert actions['actions'] == []

def test_three_sharing_members_shows_numbers(world):
    team_id = two_sharing_team(world)
    world.set_level('p3', 'team_totals')

    team = world.get('/api/manager/overview').get_json()['teams'][0]
    assert team['hidden'] is False
    assert team['members'] == 3 and team['contributors'] == 3
    assert team['avg_raw'] == 60
    assert team['status'] == {'label': 'Elevated drift', 'band': 'elevated'}

    agg = aggregate(world, team_id).get_json()
    assert agg['hidden'] is False
    assert len(agg['series']) == 14
    assert agg['levels_avg'] == {k: 60 for k in ('switching', 'session', 'checks', 'screen', 'night', 'timing')}

    actions = world.get(f'/api/teams/{team_id}/actions').get_json()
    assert len(actions['actions']) == 4

def test_aggregate_json_has_no_usernames_or_ids(world, nova):
    body = aggregate(world, nova).get_data(as_text=True)
    for name in ('alice', 'bob', 'cara', 'dan', 'boss'):
        assert name not in body
    assert 'account_id' not in body
    assert 'username' not in body
    parsed = json.loads(body)
    assert set(parsed) == {'team', 'context', 'hidden', 'series', 'latest', 'levels_avg', 'status', 'horizon'}
    assert set(parsed['series'][0]) == {'day', 'avg_raw', 'avg', 'contributors'}
