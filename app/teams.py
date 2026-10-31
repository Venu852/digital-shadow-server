import datetime
import secrets
import time
from flask import Blueprint, request, jsonify, g, current_app
from .db import get_db
from .auth import login_required
from .rules import GROUP_AGREEMENT

bp = Blueprint('teams', __name__, url_prefix='/api/teams')

INVITE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
PREVIEW_LIMIT = 20
PREVIEW_WINDOW = 3600

def preview_rate_limited(account_id):
    # In-memory, per account: guessing invite codes through previews stays slow
    now = time.monotonic()
    hits = current_app.preview_rate_data.setdefault(account_id, [])
    hits[:] = [t for t in hits if now - t < PREVIEW_WINDOW]
    if len(hits) >= PREVIEW_LIMIT:
        return True
    hits.append(now)
    return False

def generate_invite_code():
    return "".join(secrets.choice(INVITE_CHARS) for _ in range(8))

@bp.route('', methods=['POST'])
@login_required
def create_team():
    if g.user['role'] != 'manager':
        return jsonify({"error": "Only managers can create teams"}), 403

    data = request.get_json()
    name = data.get('name', '')
    if not (2 <= len(name) <= 40):
        return jsonify({"error": "Name must be 2-40 characters"}), 400

    db = get_db()
    invite_code = generate_invite_code()
    try:
        cursor = db.execute(
            "INSERT INTO teams (name, manager_id, invite_code, created_at) VALUES (?, ?, ?, ?)",
            (name, g.user['id'], invite_code, datetime.datetime.now(datetime.UTC).isoformat())
        )
        db.commit()
        team_id = cursor.lastrowid
    except db.IntegrityError:
        return jsonify({"error": "Team name already exists"}), 409

    return jsonify({
        "id": team_id,
        "name": name,
        "invite_code": invite_code
    }), 201

@bp.route('', methods=['GET'])
@login_required
def list_teams():
    db = get_db()
    if g.user['role'] == 'manager':
        teams = db.execute(
            """
            SELECT t.id, t.name, t.invite_code, COUNT(m.account_id) as member_count
            FROM teams t
            LEFT JOIN memberships m ON t.id = m.team_id
            WHERE t.manager_id = ?
            GROUP BY t.id
            """,
            (g.user['id'],)
        ).fetchall()
        return jsonify([dict(t) for t in teams]), 200
    else:
        # Individual: list joined teams
        teams = db.execute(
            """
            SELECT t.id, t.name
            FROM teams t
            JOIN memberships m ON t.id = m.team_id
            WHERE m.account_id = ?
            """,
            (g.user['id'],)
        ).fetchall()
        return jsonify([dict(t) for t in teams]), 200

@bp.route('/preview', methods=['GET'])
@login_required
def preview_team():
    if g.user['role'] != 'individual':
        return jsonify({"error": "Only individuals can join teams"}), 403
    if preview_rate_limited(g.user['id']):
        return jsonify({"error": "Too many requests"}), 429

    invite_code = request.args.get('code', '').strip().upper()
    team = get_db().execute(
        """
        SELECT t.name, a.username AS coordinator
        FROM teams t
        JOIN accounts a ON a.id = t.manager_id
        WHERE UPPER(t.invite_code) = ?
        """,
        (invite_code,)
    ).fetchone()
    if not invite_code or team is None:
        return jsonify({"error": "Invite code not found."}), 404

    return jsonify({
        "team": {"name": team['name']},
        "coordinator": {"username": team['coordinator']},
        "agreement": list(GROUP_AGREEMENT),
    }), 200

@bp.route('/join', methods=['POST'])
@login_required
def join_team():
    if g.user['role'] != 'individual':
        return jsonify({"error": "Only individuals can join teams"}), 403

    data = request.get_json()
    if not isinstance(data, dict) or data.get('accept') is not True:
        return jsonify({"error": "Please confirm the group agreement."}), 400
    invite_code = data.get('invite_code', '').upper()

    db = get_db()
    team = db.execute(
        "SELECT id, name FROM teams WHERE UPPER(invite_code) = ?", (invite_code,)
    ).fetchone()

    if not team:
        return jsonify({"error": "Team not found"}), 404

    try:
        db.execute(
            "INSERT INTO memberships (team_id, account_id, joined_at) VALUES (?, ?, ?)",
            (team['id'], g.user['id'], datetime.datetime.now(datetime.UTC).isoformat())
        )
        db.commit()
    except db.IntegrityError:
        return jsonify({"error": "Already a member"}), 409

    return jsonify({
        "team_id": team['id'],
        "name": team['name']
    }), 200

@bp.route('/<int:team_id>/invite/rotate', methods=['POST'])
@login_required
def rotate_invite(team_id):
    if g.user['role'] != 'manager':
        return jsonify({"error": "Only managers can rotate invite codes"}), 403

    db = get_db()
    team = db.execute(
        "SELECT manager_id FROM teams WHERE id = ?", (team_id,)
    ).fetchone()

    if not team:
        return jsonify({"error": "Team not found"}), 404
    if team['manager_id'] != g.user['id']:
        return jsonify({"error": "Not your team"}), 403

    new_code = generate_invite_code()
    db.execute(
        "UPDATE teams SET invite_code = ? WHERE id = ?", (new_code, team_id)
    )
    db.commit()

    return jsonify({"invite_code": new_code}), 200

@bp.route('/<int:team_id>/membership', methods=['DELETE'])
@login_required
def leave_team(team_id):
    if g.user['role'] != 'individual':
        return jsonify({"error": "Only individuals can leave teams"}), 404 # Per requirements: else 404

    db = get_db()
    membership = db.execute(
        "SELECT 1 FROM memberships WHERE team_id = ? AND account_id = ?",
        (team_id, g.user['id'])
    ).fetchone()

    if not membership:
        return jsonify({"error": "Not a member"}), 404

    db.execute(
        "DELETE FROM memberships WHERE team_id = ? AND account_id = ?",
        (team_id, g.user['id'])
    )
    db.commit()

    return '', 204
