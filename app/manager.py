import datetime
import functools
from flask import Blueprint, request, jsonify, g
from . import data
from .audit import record
from .auth import login_required
from .db import get_db
from .me_views import MAX_DAYS, build_explain, build_trend, parse_days, parse_int_arg
from .rules import (CONTEXT_TAGS, IMPACT_NOTE, MIN_GROUP, SIGNALS_BY_KEY, SUGGESTION_THRESHOLD,
                    display_drift, horizon_for, impact_windows, status_for, top_signal,
                    weekday_pattern)

bp = Blueprint('manager', __name__, url_prefix='/api')

MAX_ACTIONS = 4
OVERVIEW_DAYS = 14
DECISIONS = ('approved', 'dismissed')
IMPACT_DAYS = 60

def manager_only(f):
    @functools.wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if g.user['role'] != 'manager':
            return jsonify({"error": "Only managers can use this route"}), 403
        return f(*args, **kwargs)
    return decorated_function

def own_team(f):
    """Manager-only route on a team the caller owns; any other team is 404."""
    @functools.wraps(f)
    @manager_only
    def decorated_function(team_id, *args, **kwargs):
        g.team = get_db().execute(
            "SELECT id, name FROM teams WHERE id = ? AND manager_id = ?", (team_id, g.user['id'])
        ).fetchone()
        if g.team is None:
            return jsonify({"error": "Team not found"}), 404
        return f(team_id, *args, **kwargs)
    return decorated_function

def team_view(team_id, days):
    """Settings, contributors, hidden flag and displayed daily series, all from current levels."""
    settings = data.team_settings(team_id)
    contributors = data.team_contributors(team_id)
    hidden = len(contributors) < MIN_GROUP
    series = [] if hidden else data.team_daily_aggregates(contributors, days)
    damp = settings['context_tag'] != 'None'
    for entry in series:
        entry['avg'] = display_drift(entry['avg_raw'], damp)
    return settings, contributors, hidden, series

def public_entry(entry):
    return {key: entry[key] for key in ('day', 'avg_raw', 'avg', 'contributors')}

def current_actions(team_id, settings, series):
    candidates = [e for e in reversed(series) if e['avg'] >= SUGGESTION_THRESHOLD][:MAX_ACTIONS]
    rows = get_db().execute(
        "SELECT day, decision FROM action_decisions WHERE team_id = ?", (team_id,)
    ).fetchall()
    decisions = {r['day']: r['decision'] for r in rows}

    actions = []
    for entry in candidates:
        signal = SIGNALS_BY_KEY[top_signal(entry['levels_avg'])]
        decision = decisions.get(entry['day'])
        if settings['human_review']:
            status = decision or 'pending'
        else:
            status = 'applied'
        actions.append({
            "day": entry['day'],
            "drift": entry['avg'],
            "signal": signal['key'],
            "signal_label": signal['label'],
            "action": signal['action'],
            "status": status,
            "decision": decision,
        })
    return actions

def visible_person(team_id, account_id):
    """The member only if they currently share 'my_trend'; callers never learn which check failed."""
    person = get_db().execute(
        """
        SELECT a.id, a.username
        FROM memberships m
        JOIN accounts a ON a.id = m.account_id
        WHERE m.team_id = ? AND m.account_id = ?
        """,
        (team_id, account_id)
    ).fetchone()
    if person is None or data.current_level(person['id']) != 'my_trend':
        return None
    return person

@bp.route('/manager/overview', methods=['GET'])
@manager_only
def overview():
    teams = get_db().execute(
        "SELECT id, name FROM teams WHERE manager_id = ? ORDER BY id", (g.user['id'],)
    ).fetchall()
    result = []
    for team in teams:
        settings, contributors, hidden, series = team_view(team['id'], OVERVIEW_DAYS)
        entry = {
            "id": team['id'], "name": team['name'], "context": settings['context_tag'],
            "hidden": hidden, "members": None, "contributors": None,
            "latest_day": None, "avg_raw": None, "avg": None, "status": None,
        }
        if not hidden:
            latest = series[-1] if series else None
            entry.update({
                "members": len(data.team_members(team['id'])),
                "contributors": len(contributors),
                "latest_day": latest['day'] if latest else None,
                "avg_raw": latest['avg_raw'] if latest else None,
                "avg": latest['avg'] if latest else None,
                "status": status_for(latest['avg']) if latest else None,
            })
        result.append(entry)
    return jsonify({"teams": result}), 200

@bp.route('/teams/<int:team_id>/aggregate', methods=['GET'])
@own_team
def aggregate(team_id):
    days = parse_days()
    if days is None:
        return jsonify({"error": f"days must be 1-{MAX_DAYS}"}), 400
    settings, _, hidden, series = team_view(team_id, days)
    latest = series[-1] if series else None
    # Never include usernames or account ids here
    return jsonify({
        "team": {"id": g.team['id'], "name": g.team['name']},
        "context": settings['context_tag'],
        "hidden": hidden,
        "series": [public_entry(e) for e in series],
        "latest": public_entry(latest) if latest else None,
        "levels_avg": latest['levels_avg'] if latest else None,
        "status": status_for(latest['avg']) if latest else None,
        "horizon": horizon_for([e['avg'] for e in series]) if latest else None,
    }), 200

@bp.route('/teams/<int:team_id>/people', methods=['GET'])
@own_team
def people(team_id):
    members = data.team_members(team_id)
    return jsonify({"people": [
        {"account_id": m['id'], "username": m['username']}
        for m in members if m['level'] == 'my_trend'
    ]}), 200

@bp.route('/teams/<int:team_id>/people/<int:account_id>/trend', methods=['GET'])
@own_team
def person_trend(team_id, account_id):
    days = parse_days()
    if days is None:
        return jsonify({"error": f"days must be 1-{MAX_DAYS}"}), 400
    person = visible_person(team_id, account_id)
    if person is None:
        return jsonify({"error": "Person not found"}), 404

    # The manager only sees the context of their own team
    tag = data.team_settings(team_id)['context_tag']
    result = build_trend(person, days, [tag] if tag != 'None' else [])
    record(g.user['id'], 'view_trend', target_id=person['id'], team_id=team_id)
    get_db().commit()
    return jsonify(result), 200

@bp.route('/teams/<int:team_id>/people/<int:account_id>/explain', methods=['GET'])
@own_team
def person_explain(team_id, account_id):
    person = visible_person(team_id, account_id)
    if person is None:
        return jsonify({"error": "Person not found"}), 404

    result = build_explain(person['id'], 'manager')
    record(g.user['id'], 'view_explain', target_id=person['id'], team_id=team_id)
    get_db().commit()
    return jsonify(result), 200

@bp.route('/teams/<int:team_id>/actions', methods=['GET'])
@own_team
def actions(team_id):
    settings, _, hidden, series = team_view(team_id, OVERVIEW_DAYS)
    return jsonify({
        "hidden": hidden,
        "human_review": settings['human_review'],
        "actions": [] if hidden else current_actions(team_id, settings, series),
    }), 200

@bp.route('/teams/<int:team_id>/actions/<day>', methods=['PUT'])
@own_team
def decide_action(team_id, day):
    body = request.get_json(silent=True)
    decision = body.get('decision') if isinstance(body, dict) else None
    if decision not in DECISIONS:
        return jsonify({"error": "decision must be 'approved' or 'dismissed'"}), 400

    settings, _, hidden, series = team_view(team_id, OVERVIEW_DAYS)
    # The signal shown for the day is stored with the decision, so later level changes never alter it
    signals = {} if hidden else {a['day']: a['signal'] for a in current_actions(team_id, settings, series)}
    if not settings['human_review'] or day not in signals:
        return jsonify({"error": "Action not found"}), 404

    db = get_db()
    db.execute(
        """
        INSERT INTO action_decisions (team_id, day, decision, decided_by, decided_at, signal)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(team_id, day) DO UPDATE SET
            decision = excluded.decision,
            decided_by = excluded.decided_by,
            decided_at = excluded.decided_at,
            signal = excluded.signal
        """,
        (team_id, day, decision, g.user['id'], datetime.datetime.now(datetime.UTC).isoformat(), signals[day])
    )
    record(g.user['id'], 'decide_action', team_id=team_id, detail={"day": day, "decision": decision})
    db.commit()
    return jsonify({"day": day, "decision": decision}), 200

def settings_response(settings):
    return {
        "human_review": settings['human_review'],
        "context_tag": settings['context_tag'],
        "context_options": list(CONTEXT_TAGS),
    }

@bp.route('/teams/<int:team_id>/settings', methods=['GET'])
@own_team
def get_settings(team_id):
    return jsonify(settings_response(data.team_settings(team_id))), 200

@bp.route('/teams/<int:team_id>/settings', methods=['PUT'])
@own_team
def update_settings(team_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) - {'human_review', 'context_tag'}:
        return jsonify({"error": "Only human_review and context_tag can be set"}), 400
    if 'human_review' in body and not isinstance(body['human_review'], bool):
        return jsonify({"error": "human_review must be true or false"}), 400
    if 'context_tag' in body and body['context_tag'] not in CONTEXT_TAGS:
        return jsonify({"error": "Invalid context_tag"}), 400

    settings = data.team_settings(team_id)
    settings.update(body)
    db = get_db()
    db.execute(
        """
        INSERT INTO team_settings (team_id, human_review, context_tag, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(team_id) DO UPDATE SET
            human_review = excluded.human_review,
            context_tag = excluded.context_tag,
            updated_at = excluded.updated_at
        """,
        (team_id, int(settings['human_review']), settings['context_tag'],
         datetime.datetime.now(datetime.UTC).isoformat())
    )
    record(g.user['id'], 'update_settings', team_id=team_id, detail=body)
    db.commit()
    return jsonify(settings_response(settings)), 200

@bp.route('/teams/<int:team_id>/impact', methods=['GET'])
@own_team
def impact(team_id):
    contributors = data.team_contributors(team_id)
    if len(contributors) < MIN_GROUP:
        return jsonify({"hidden": True, "items": []}), 200

    since = data.today_utc() - datetime.timedelta(days=IMPACT_DAYS)
    adopted, levels = data.adopted_with_signals(team_id, contributors, since, extra_days=7)
    items = []
    for a in adopted:
        signal = a['signal']
        items.append({
            "day": a['day'],
            "signal": signal['key'],
            "signal_label": signal['label'],
            "action": signal['action'],
            "adopted_at": a['adopted_on'].isoformat(),
            **impact_windows(a['adopted_on'], levels, signal['key']),
            "note": IMPACT_NOTE,
        })
    # Never include usernames or account ids here
    return jsonify({"hidden": False, "items": items}), 200

@bp.route('/teams/<int:team_id>/weekday-pattern', methods=['GET'])
@own_team
def weekday(team_id):
    weeks = parse_int_arg('weeks', 8, 2, 26)
    if weeks is None:
        return jsonify({"error": "weeks must be 2-26"}), 400

    contributors = data.team_contributors(team_id)
    hidden = len(contributors) < MIN_GROUP
    daily = []
    if not hidden:
        # The window ends at tomorrow (UTC), like the other team views
        end = data.today_utc() + datetime.timedelta(days=1)
        levels = data.team_daily_levels(contributors, end - datetime.timedelta(days=weeks * 7 - 1), end)
        daily = [(day, entry['avg_raw']) for day, entry in levels.items()]
    rows, highest = weekday_pattern(daily)
    return jsonify({"hidden": hidden, "weeks": weeks, "by_weekday": rows, "highest": highest}), 200
