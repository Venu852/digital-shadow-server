"""Phase 8: invite preview, join agreement, impact check, group updates, weekday pattern,
retention and export."""
import datetime
import json
import pytest
from app import data, retention
from app.db import get_db
from app.rules import GROUP_AGREEMENT, backfill_signals
from test_privacy_matrix import XHR, World, now_iso, world  # noqa: F401

def today():
    return datetime.datetime.now(datetime.UTC).date()

def date_at(offset):
    return today() + datetime.timedelta(days=offset)

def lv(night=0, switching=0):
    return {'switching': switching, 'session': 0, 'checks': 0, 'screen': 0, 'night': night, 'timing': 0}

class Readings:
    """One device per person; put() stores a reading on a given day."""

    def __init__(self, world, names):
        self.world = world
        self.devices = {name: world.device(name) for name in names}

    def put(self, names, day, drift, levels):
        for name in names:
            self.world.db(
                """INSERT OR REPLACE INTO daily_summaries
                   (device_id, day, drift, levels_json, confidence, baseline, received_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (self.devices[name], day.isoformat(), drift, json.dumps(levels), 60, 'established', now_iso())
            )

def decide(world, team_id, day, decision, decided_on, signal='night'):
    decided_at = datetime.datetime.combine(decided_on, datetime.time(12, 0), datetime.UTC).isoformat()
    world.db(
        "INSERT INTO action_decisions (team_id, day, decision, decided_by, decided_at, signal)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (team_id, day.isoformat(), decision, world.ids['boss'], decided_at, signal)
    )

PEOPLE = ('p1', 'p2', 'p3')

@pytest.fixture
def group(world):
    world.person('boss', role='manager')
    for name in PEOPLE:
        world.person(name, level='team_totals')
    world.person('dan', level='nothing')
    team_id = world.team('Nova', 'boss', list(PEOPLE) + ['dan'])
    return team_id, Readings(world, PEOPLE)

# ---------------- preview and join ----------------

@pytest.fixture
def invite(world):
    world.person('boss', role='manager')
    world.person('ind')
    team_id = world.team('Nova', 'boss')
    return world.query("SELECT invite_code FROM teams WHERE id = ?", (team_id,))[0]['invite_code']

def test_preview_shows_group_coordinator_and_agreement(world, invite):
    world.login('ind')
    res = world.get(f'/api/teams/preview?code={invite.lower()}')
    assert res.status_code == 200
    assert res.get_json() == {
        "team": {"name": "Nova"},
        "coordinator": {"username": "boss"},
        "agreement": list(GROUP_AGREEMENT),
    }
    assert len(GROUP_AGREEMENT) == 4
    assert GROUP_AGREEMENT[0] == "The coordinator sees a group average only when at least 3 people share."

def test_preview_403_for_coordinators(world, invite):
    world.login('boss')
    assert world.get(f'/api/teams/preview?code={invite}').status_code == 403

def test_preview_unknown_code_404(world, invite):
    world.login('ind')
    res = world.get('/api/teams/preview?code=ZZZZZZZZ')
    assert res.status_code == 404
    assert res.get_json() == {"error": "Invite code not found."}
    assert world.get('/api/teams/preview').status_code == 404

def test_preview_429_after_20_calls(world, invite):
    world.login('ind')
    for _ in range(20):
        assert world.get('/api/teams/preview?code=ZZZZZZZZ').status_code == 404
    assert world.get(f'/api/teams/preview?code={invite}').status_code == 429

def test_join_without_accept_400(world, invite):
    world.login('ind')
    for body in ({'invite_code': invite}, {'invite_code': invite, 'accept': False},
                 {'invite_code': invite, 'accept': 'true'}):
        res = world.client.post('/api/teams/join', json=body, headers=XHR)
        assert res.status_code == 400
        assert res.get_json() == {"error": "Please confirm the group agreement."}
    assert world.query("SELECT * FROM memberships") == []
    res = world.client.post('/api/teams/join', json={'invite_code': invite, 'accept': True}, headers=XHR)
    assert res.status_code == 200

# ---------------- impact check ----------------

def impact(world, team_id):
    return world.get(f'/api/teams/{team_id}/impact')

def test_impact_windows_and_complete_flag(world, group):
    team_id, r = group
    adopted = date_at(-10)
    # Before window: the 7 days before adoption; drifts average 41, night levels average 60
    for offset, drift in zip(range(-17, -10), [40, 42, 40, 42, 40, 42, 41]):
        r.put(PEOPLE, date_at(offset), drift, lv(night=60))
    r.put(PEOPLE, date_at(-18), 99, lv(night=99))       # outside the window
    r.put(PEOPLE, adopted, 50, lv(night=80))             # the adoption day itself counts in neither
    for offset in range(-9, -5):                         # four after days
        r.put(PEOPLE, date_at(offset), 20, lv(night=30))
    r.put(['p1', 'p2'], date_at(-5), 90, lv(night=90))   # only 2 contributors: not counted
    decide(world, team_id, adopted, 'approved', adopted)
    world.login('boss')

    body = impact(world, team_id).get_json()
    assert body['hidden'] is False
    assert body['items'] == [{
        "day": adopted.isoformat(),
        "signal": "night",
        "signal_label": "Late-night use",
        "action": "Avoid late-evening requests and deadlines; keep after-hours messages to a minimum.",
        "adopted_at": adopted.isoformat(),
        "before": {"drift": 41, "signal_level": 60, "days": 7},
        "after": {"drift": 20, "signal_level": 30, "days": 4},
        "change": {"drift": -21, "signal_level": -30},
        "complete": False,
        "note": "An observation, not proof.",
    }]

    r.put(['p3'], date_at(-5), 90, lv(night=90))         # now 3 contributors that day
    item = impact(world, team_id).get_json()['items'][0]
    assert item['after'] == {"drift": 34, "signal_level": 42, "days": 5}
    assert item['complete'] is True

def test_impact_null_windows(world, group):
    team_id, r = group
    adopted = date_at(-20)
    r.put(PEOPLE, adopted, 50, lv(switching=70))
    decide(world, team_id, adopted, 'approved', adopted, signal='switching')
    world.login('boss')
    item = impact(world, team_id).get_json()['items'][0]
    assert item['signal'] == 'switching'
    assert item['before'] == {"drift": None, "signal_level": None, "days": 0}
    assert item['after'] == {"drift": None, "signal_level": None, "days": 0}
    assert item['change'] is None
    assert item['complete'] is False

def test_impact_only_recent_approved_newest_first(world, group):
    team_id, r = group
    for offset in (-3, -5, -8, -70):
        r.put(PEOPLE, date_at(offset), 50, lv(night=80))
    decide(world, team_id, date_at(-3), 'approved', date_at(-2))
    decide(world, team_id, date_at(-8), 'approved', date_at(-7))
    decide(world, team_id, date_at(-5), 'dismissed', date_at(-4))
    decide(world, team_id, date_at(-70), 'approved', date_at(-70))   # older than 60 days
    world.login('boss')
    items = impact(world, team_id).get_json()['items']
    assert [i['day'] for i in items] == [date_at(-3).isoformat(), date_at(-8).isoformat()]
    assert [i['adopted_at'] for i in items] == [date_at(-2).isoformat(), date_at(-7).isoformat()]

def test_impact_hidden_team(world, group):
    team_id, r = group
    r.put(PEOPLE, date_at(-3), 50, lv(night=80))
    decide(world, team_id, date_at(-3), 'approved', date_at(-3))
    world.set_level('p3', 'nothing')
    world.login('boss')
    assert impact(world, team_id).get_json() == {"hidden": True, "items": []}

def test_impact_other_coordinator_404(world, group):
    team_id, r = group
    world.person('other', role='manager')
    world.login('other')
    assert impact(world, team_id).status_code == 404
    assert world.get(f'/api/teams/{team_id}/weekday-pattern').status_code == 404

# ---------------- group updates ----------------

def test_group_updates_text_only_and_for_nothing_level(world, group):
    team_id, r = group
    for offset in (-3, -5, -40):
        r.put(PEOPLE, date_at(offset), 50, lv(night=80))
    decide(world, team_id, date_at(-3), 'approved', date_at(-3))
    decide(world, team_id, date_at(-5), 'dismissed', date_at(-5))
    decide(world, team_id, date_at(-40), 'approved', date_at(-40))   # older than 30 days
    world.team('Quiet', 'boss', ['dan'])

    world.login('dan')   # dan's level is 'nothing'
    body = world.get('/api/me/group-updates').get_json()
    assert body == {"groups": [
        {"team": {"id": team_id, "name": "Nova"}, "adopted": [{
            "day": date_at(-3).isoformat(),
            "signal_label": "Late-night use",
            "text": "Avoid late-evening requests and deadlines; keep after-hours messages to a minimum.",
        }]},
        {"team": {"id": world.ids['Quiet'], "name": "Quiet"}, "adopted": []},
    ]}
    for group_entry in body['groups']:
        for item in group_entry['adopted']:
            assert not any(isinstance(v, (int, float)) for v in item.values())
            assert not any(ch.isdigit() for ch in item['signal_label'] + item['text'])

def test_group_updates_individuals_only(world, group):
    world.login('boss')
    assert world.get('/api/me/group-updates').status_code == 403

# ---------------- stored decision signal ----------------

def put_decision(world, team_id, day, decision):
    return world.client.put(f'/api/teams/{team_id}/actions/{day.isoformat()}',
                            json={'decision': decision}, headers=XHR)

def stored_signals(world, team_id):
    rows = world.query("SELECT day, decision, signal FROM action_decisions WHERE team_id = ? ORDER BY day",
                       (team_id,))
    return [(r['day'], r['decision'], r['signal']) for r in rows]

def test_stored_signal_survives_later_level_changes(world, group):
    team_id, r = group
    day = date_at(-2)
    r.put(PEOPLE, day, 50, lv(night=80, switching=20))
    world.login('boss')
    assert put_decision(world, team_id, day, 'approved').status_code == 200
    assert stored_signals(world, team_id) == [(day.isoformat(), 'approved', 'night')]

    # The group's levels for that day change afterwards; switching is now the top signal
    r.put(PEOPLE, day, 50, lv(night=10, switching=90))
    item = impact(world, team_id).get_json()['items'][0]
    assert (item['signal'], item['signal_label']) == ('night', 'Late-night use')
    assert stored_signals(world, team_id) == [(day.isoformat(), 'approved', 'night')]
    world.login('p1')
    adopted = world.get('/api/me/group-updates').get_json()['groups'][0]['adopted']
    assert [a['signal_label'] for a in adopted] == ['Late-night use']

def test_dismissed_decision_stores_signal(world, group):
    team_id, r = group
    day = date_at(-1)
    r.put(PEOPLE, day, 50, lv(switching=70))
    world.login('boss')
    assert put_decision(world, team_id, day, 'dismissed').status_code == 200
    assert stored_signals(world, team_id) == [(day.isoformat(), 'dismissed', 'switching')]

def test_null_signal_left_out_of_impact_and_group_updates(world, group):
    team_id, r = group
    r.put(PEOPLE, date_at(-3), 50, lv(night=80))
    decide(world, team_id, date_at(-3), 'approved', date_at(-3), signal=None)
    world.login('boss')
    assert impact(world, team_id).get_json() == {"hidden": False, "items": []}
    world.login('p1')
    assert world.get('/api/me/group-updates').get_json()['groups'][0]['adopted'] == []

def test_backfill_signals_pure():
    decisions = [(1, '2026-01-01'), (1, '2026-01-02'), (2, '2026-01-01')]
    group_levels = {1: {'2026-01-01': lv(night=10, switching=50)}}
    assert backfill_signals(decisions, group_levels) == {(1, '2026-01-01'): 'switching'}
    assert backfill_signals([], group_levels) == {}

def test_backfill_fills_what_it_can_and_is_idempotent(world, group):
    team_id, r = group
    r.put(PEOPLE, date_at(-3), 50, lv(switching=70))
    r.put(['p1', 'p2'], date_at(-4), 50, lv(night=70))      # only 2 contributors: stays NULL
    r.put(PEOPLE, date_at(-5), 50, lv(switching=70))
    decide(world, team_id, date_at(-3), 'approved', date_at(-3), signal=None)
    decide(world, team_id, date_at(-4), 'approved', date_at(-4), signal=None)
    decide(world, team_id, date_at(-5), 'dismissed', date_at(-5), signal='night')   # already stored

    with world.app.app_context():
        assert data.backfill_decision_signals() == 1
    expected = [(date_at(-5).isoformat(), 'dismissed', 'night'),
                (date_at(-4).isoformat(), 'approved', None),
                (date_at(-3).isoformat(), 'approved', 'switching')]
    assert stored_signals(world, team_id) == expected

    # Running again changes nothing, even after the levels change
    r.put(PEOPLE, date_at(-3), 50, lv(night=90))
    with world.app.app_context():
        assert data.backfill_decision_signals() == 0
    assert stored_signals(world, team_id) == expected

def test_startup_runs_backfill(app, world, group):
    from app import create_app
    team_id, r = group
    r.put(PEOPLE, date_at(-3), 50, lv(night=70))
    decide(world, team_id, date_at(-3), 'approved', date_at(-3), signal=None)
    create_app({'TESTING': True, 'DATABASE': app.config['DATABASE'], 'SECRET_KEY': 'x'})
    assert stored_signals(world, team_id) == [(date_at(-3).isoformat(), 'approved', 'night')]

# ---------------- weekday pattern ----------------

def offsets_for(weekday, count):
    """The newest `count` offsets (<= 0) that fall on `weekday`."""
    result = []
    offset = 0
    while len(result) < count:
        if date_at(offset).weekday() == weekday:
            result.append(offset)
        offset -= 1
    return result

def weekday_body(world, team_id, weeks=8):
    return world.get(f'/api/teams/{team_id}/weekday-pattern?weeks={weeks}').get_json()

def test_weekday_thresholds(world, group):
    team_id, r = group
    for weekday, drift, count in ((0, 10, 3), (1, 20, 3), (2, 30, 3), (3, 90, 2)):
        for offset in offsets_for(weekday, count):
            r.put(PEOPLE, date_at(offset), drift, lv())
    world.login('boss')

    body = weekday_body(world, team_id)
    assert body['hidden'] is False and body['weeks'] == 8
    rows = {row['label']: row for row in body['by_weekday']}
    assert [row['weekday'] for row in body['by_weekday']] == list(range(7))
    assert list(rows) == ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    assert rows['Mon'] == {"weekday": 0, "label": "Mon", "avg": 10, "days": 3}
    assert rows['Thu'] == {"weekday": 3, "label": "Thu", "avg": None, "days": 2}   # only 2 days
    assert rows['Sun']['avg'] is None
    assert body['highest'] is None   # only 3 weekdays have values

    for offset in offsets_for(4, 3):
        r.put(PEOPLE, date_at(offset), 25, lv())
    assert weekday_body(world, team_id)['highest'] == 'Wed'

def test_weekday_window_and_validation(world, group):
    team_id, r = group
    for offset in offsets_for(0, 3):
        r.put(PEOPLE, date_at(offset), 10, lv())
    world.login('boss')
    # Two weeks hold only two Mondays
    assert weekday_body(world, team_id, weeks=2)['by_weekday'][0] == {
        "weekday": 0, "label": "Mon", "avg": None, "days": 2}
    for weeks in ('1', '27', 'abc', '-3'):
        res = world.get(f'/api/teams/{team_id}/weekday-pattern?weeks={weeks}')
        assert res.status_code == 400
        assert 'error' in res.get_json()

def test_weekday_hidden_team(world, group):
    team_id, r = group
    for offset in offsets_for(0, 3):
        r.put(PEOPLE, date_at(offset), 10, lv())
    world.set_level('p1', 'nothing')
    world.login('boss')
    body = weekday_body(world, team_id)
    assert body['hidden'] is True
    assert body['highest'] is None
    assert all(row['avg'] is None and row['days'] == 0 for row in body['by_weekday'])

# ---------------- retention ----------------

def test_retention_purge_with_fake_today(world, group):
    team_id, r = group
    fake_today = datetime.date(2030, 6, 1)
    for days_ago in (91, 90, 10):
        r.put(['p1'], fake_today - datetime.timedelta(days=days_ago), 10, lv())
    for days_ago in (400, 100):
        at = datetime.datetime.combine(fake_today - datetime.timedelta(days=days_ago),
                                       datetime.time(9), datetime.UTC).isoformat()
        world.db("INSERT INTO audit_log (at, actor_id, action, target_id) VALUES (?, ?, 'view_trend', ?)",
                 (at, world.ids['boss'], world.ids['p1']))

    with world.app.app_context():
        removed = retention.purge(get_db(), fake_today, 90, 365)
    assert removed == {"daily_summaries": 1, "audit_log": 1}
    days = [row['day'] for row in world.query("SELECT day FROM daily_summaries ORDER BY day")]
    assert days == [(fake_today - datetime.timedelta(days=n)).isoformat() for n in (90, 10)]
    audit = world.query("SELECT at FROM audit_log")
    assert len(audit) == 1 and audit[0]['at'].startswith((fake_today - datetime.timedelta(days=100)).isoformat())

def test_retention_settings(monkeypatch):
    monkeypatch.delenv('SHADOW_RETENTION_DAYS', raising=False)
    monkeypatch.delenv('SHADOW_AUDIT_RETENTION_DAYS', raising=False)
    assert retention.retention_settings() == (90, 365)
    monkeypatch.setenv('SHADOW_RETENTION_DAYS', '5')
    monkeypatch.setenv('SHADOW_AUDIT_RETENTION_DAYS', '730')
    assert retention.retention_settings() == (14, 730)

def test_startup_purges_old_summaries(app, world, group):
    from app import create_app
    team_id, r = group
    r.put(['p1'], date_at(-200), 10, lv())
    r.put(['p1'], date_at(-3), 10, lv())
    create_app({'TESTING': True, 'DATABASE': app.config['DATABASE'], 'SECRET_KEY': 'x'})
    assert [row['day'] for row in world.query("SELECT day FROM daily_summaries")] == [date_at(-3).isoformat()]

# ---------------- export ----------------

def test_export_contains_only_callers_data(world, group):
    team_id, r = group
    r.put(['p1', 'p2'], date_at(-1), 33, lv(night=40))
    world.db("INSERT INTO audit_log (at, actor_id, action, target_id, team_id) VALUES (?, ?, 'view_trend', ?, ?)",
             (now_iso(), world.ids['boss'], world.ids['p1'], team_id))
    world.db("INSERT INTO audit_log (at, actor_id, action, target_id, team_id) VALUES (?, ?, 'view_trend', ?, ?)",
             (now_iso(), world.ids['boss'], world.ids['p2'], team_id))
    world.login('p1')

    res = world.get('/api/me/export')
    assert res.status_code == 200
    assert res.headers['Content-Disposition'] == 'attachment; filename="digital-shadow-export.json"'
    raw = res.get_data(as_text=True)
    body = json.loads(raw)
    assert set(body) == {"exported_at", "account", "sharing_history", "devices", "daily_summaries",
                         "access_log", "groups"}
    assert body['account']['username'] == 'p1' and body['account']['role'] == 'individual'
    assert set(body['account']) == {"username", "role", "created_at"}
    assert [s['level'] for s in body['sharing_history']] == ['team_totals']
    assert body['devices'] == [{
        "id": r.devices['p1'], "name": "Phone", "created_at": body['devices'][0]['created_at'],
        "last_seen_at": None, "revoked": False}]
    assert [(s['day'], s['drift'], s['levels']['night']) for s in body['daily_summaries']] == [
        (date_at(-1).isoformat(), 33, 40)]
    assert len(body['access_log']) == 1 and body['access_log'][0]['by'] == 'boss'
    assert body['groups'] == [{"name": "Nova", "joined_at": body['groups'][0]['joined_at']}]

    token_hashes = [row['token_hash'] for row in world.query("SELECT token_hash FROM devices")]
    for secret in ['password_hash', 'token_hash', 'p2', 'p3', 'dan', r.devices['p2']] + token_hashes:
        assert secret not in raw

def test_export_individuals_only(world, group):
    world.login('boss')
    assert world.get('/api/me/export').status_code == 403
