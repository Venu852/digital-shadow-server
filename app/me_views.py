import functools
from flask import Blueprint, request, jsonify, session, g
from werkzeug.security import check_password_hash
from . import data
from .audit import access_log_for
from .auth import login_required
from .db import get_db
from .rules import (EXPLAIN_NOTE, PERSONAL_SUGGESTION_THRESHOLD, display_drift, factor_breakdown,
                    horizon_for, personal_suggestions, status_for)

bp = Blueprint('me_views', __name__, url_prefix='/api/me')

MAX_DAYS = 60
EXPLAIN_WINDOW = 60

def parse_int_arg(name, default, lo, hi):
    """Returns the query arg as an int within [lo, hi], or None when invalid."""
    raw = request.args.get(name, str(default))
    if not raw.isdigit():
        return None
    value = int(raw)
    return value if lo <= value <= hi else None

def parse_days():
    return parse_int_arg('days', 14, 1, MAX_DAYS)

def individual_only(f):
    @functools.wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if g.user['role'] != 'individual':
            return jsonify({"error": "Only individuals can use this route"}), 403
        return f(*args, **kwargs)
    return decorated_function

def build_trend(account, days, context):
    """The trend view of one person. `context` is the list of tags that damp the drift."""
    readings = data.account_series(account['id'], days)
    shown = [{
        "day": r['day'],
        "drift_raw": r['drift_raw'],
        "drift": display_drift(r['drift_raw'], bool(context)),
        "levels": r['levels'],
        "confidence": r['confidence'],
        "baseline": r['baseline'],
    } for r in readings]
    latest = shown[-1] if shown else None
    return {
        "person": {"account_id": account['id'], "username": account['username']},
        "days": shown,
        "latest": latest,
        "status": status_for(latest['drift']) if latest else None,
        "horizon": horizon_for([d['drift'] for d in shown]) if latest else None,
        "baseline_established": bool(latest) and latest['baseline'] == 'established',
        "days_observed": len(shown),
        "context": context,
    }

def build_explain(account_id, voice):
    readings = data.account_series(account_id, EXPLAIN_WINDOW)
    latest = readings[-1] if readings else None
    return {
        "day": latest['day'] if latest else None,
        "factors": factor_breakdown(latest['levels'], voice) if latest else [],
        "note": EXPLAIN_NOTE,
    }

@bp.route('/trend', methods=['GET'])
@individual_only
def my_trend():
    days = parse_days()
    if days is None:
        return jsonify({"error": f"days must be 1-{MAX_DAYS}"}), 400
    # Your own data is always visible to you, whatever your sharing level
    return jsonify(build_trend(g.user, days, data.account_context(g.user['id']))), 200

@bp.route('/explain', methods=['GET'])
@individual_only
def my_explain():
    return jsonify(build_explain(g.user['id'], 'self')), 200

@bp.route('/suggestions', methods=['GET'])
@individual_only
def my_suggestions():
    # Shown only to the person; a coordinator never sees these
    readings = data.account_series(g.user['id'], 1)
    if not readings:
        return jsonify([]), 200
    latest = readings[-1]
    drift = display_drift(latest['drift_raw'], bool(data.account_context(g.user['id'])))
    if drift < PERSONAL_SUGGESTION_THRESHOLD:
        return jsonify([]), 200
    return jsonify(personal_suggestions(latest['levels'])), 200

@bp.route('/access-log', methods=['GET'])
@individual_only
def my_access_log():
    limit = parse_int_arg('limit', 50, 1, 200)
    if limit is None:
        return jsonify({"error": "limit must be 1-200"}), 400
    return jsonify(access_log_for(g.user['id'], limit)), 200

@bp.route('', methods=['DELETE'])
@login_required
def delete_me():
    body = request.get_json(silent=True)
    password = body.get('password') if isinstance(body, dict) else None
    if not isinstance(password, str) or not check_password_hash(g.user['password_hash'], password):
        return jsonify({"error": "Incorrect password."}), 401

    db = get_db()
    # Teams reference their manager without cascade, so remove them (and their memberships,
    # settings and decisions, which cascade) first. Devices, summaries, consents, memberships
    # and audit rows about this account cascade from the account itself.
    db.execute("DELETE FROM teams WHERE manager_id = ?", (g.user['id'],))
    db.execute("DELETE FROM accounts WHERE id = ?", (g.user['id'],))
    db.commit()

    session.clear()
    return '', 204
