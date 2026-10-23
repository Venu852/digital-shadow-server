"""Shared read queries. Sharing levels are always read at call time, never cached."""
import datetime
import json
from .db import get_db
from .rules import CONTEXT_TAGS, MIN_GROUP, SIGNAL_KEYS, round_half_up
from .sharing import get_sharing

CONTRIBUTING_LEVELS = ('team_totals', 'my_trend')

def current_level(account_id):
    return get_sharing(account_id)['level']

def account_series(account_id, days):
    """Up to `days` newest daily readings from the account's non-revoked devices, ascending.

    The window ends at tomorrow (UTC) because a phone ahead of UTC may already report it.
    When several devices report the same day, the newest received_at wins.
    """
    today = datetime.datetime.now(datetime.UTC).date()
    start = (today - datetime.timedelta(days=days)).isoformat()
    end = (today + datetime.timedelta(days=1)).isoformat()
    rows = get_db().execute(
        """
        SELECT s.day, s.drift, s.levels_json, s.confidence, s.baseline
        FROM daily_summaries s
        JOIN devices d ON d.id = s.device_id
        WHERE d.account_id = ? AND d.revoked_at IS NULL AND s.day > ? AND s.day <= ?
        ORDER BY s.day, s.received_at
        """,
        (account_id, start, end)
    ).fetchall()

    by_day = {}
    for row in rows:
        by_day[row['day']] = {
            "day": row['day'],
            "drift_raw": row['drift'],
            "levels": json.loads(row['levels_json']),
            "confidence": row['confidence'],
            "baseline": row['baseline'],
        }
    return list(by_day.values())[-days:]

def team_settings(team_id):
    row = get_db().execute(
        "SELECT human_review, context_tag FROM team_settings WHERE team_id = ?", (team_id,)
    ).fetchone()
    if row is None:
        return {"human_review": True, "context_tag": CONTEXT_TAGS[0]}
    return {"human_review": bool(row['human_review']), "context_tag": row['context_tag']}

def account_context(account_id):
    """Context tags other than 'None' from every team the account belongs to."""
    rows = get_db().execute(
        """
        SELECT DISTINCT ts.context_tag
        FROM memberships m
        JOIN team_settings ts ON ts.team_id = m.team_id
        WHERE m.account_id = ? AND ts.context_tag != 'None'
        ORDER BY ts.context_tag
        """,
        (account_id,)
    ).fetchall()
    return [r['context_tag'] for r in rows]

def team_members(team_id):
    """Members with their current sharing level, ordered by username."""
    rows = get_db().execute(
        """
        SELECT a.id, a.username
        FROM memberships m
        JOIN accounts a ON a.id = m.account_id
        WHERE m.team_id = ?
        ORDER BY a.username
        """,
        (team_id,)
    ).fetchall()
    return [{"id": r['id'], "username": r['username'], "level": current_level(r['id'])} for r in rows]

def team_contributors(team_id):
    return [m for m in team_members(team_id) if m['level'] in CONTRIBUTING_LEVELS]

def team_daily_aggregates(contributors, days):
    """Per-day team averages; a day counts only when MIN_GROUP or more contributors have data."""
    per_day = {}
    for member in contributors:
        for reading in account_series(member['id'], days):
            per_day.setdefault(reading['day'], []).append(reading)

    series = []
    for day in sorted(per_day):
        readings = per_day[day]
        if len(readings) < MIN_GROUP:
            continue
        n = len(readings)
        series.append({
            "day": day,
            "avg_raw": round_half_up(sum(r['drift_raw'] for r in readings) / n),
            "levels_avg": {
                key: round_half_up(sum(r['levels'][key] for r in readings) / n)
                for key in SIGNAL_KEYS
            },
            "contributors": n,
        })
    return series[-days:]
