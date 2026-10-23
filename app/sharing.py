import datetime
from flask import Blueprint, request, jsonify, g
from .db import get_db
from .auth import login_required

bp = Blueprint('sharing', __name__, url_prefix='/api/me')

LEVELS = ('nothing', 'team_totals', 'my_trend')

def get_sharing(account_id):
    # The newest consent row is the current level; no row means 'nothing'
    db = get_db()
    row = db.execute(
        "SELECT level, changed_at FROM sharing_consents WHERE account_id = ? ORDER BY id DESC LIMIT 1",
        (account_id,)
    ).fetchone()
    if row is None:
        return {"level": "nothing", "changed_at": None}
    return {"level": row['level'], "changed_at": row['changed_at']}

@bp.route('/sharing', methods=['GET'])
@login_required
def get_my_sharing():
    if g.user['role'] != 'individual':
        return jsonify({"error": "Only individuals have sharing settings"}), 403
    return jsonify(get_sharing(g.user['id'])), 200

@bp.route('/sharing', methods=['PUT'])
@login_required
def set_my_sharing():
    if g.user['role'] != 'individual':
        return jsonify({"error": "Only individuals have sharing settings"}), 403

    data = request.get_json(silent=True)
    level = data.get('level') if isinstance(data, dict) else None
    if level not in LEVELS:
        return jsonify({"error": "Invalid sharing level"}), 400

    current = get_sharing(g.user['id'])
    # Only an actual change (or the first explicit choice) adds a consent row
    if current['changed_at'] is not None and current['level'] == level:
        return jsonify(current), 200

    changed_at = datetime.datetime.now(datetime.UTC).isoformat()
    db = get_db()
    db.execute(
        "INSERT INTO sharing_consents (account_id, level, changed_at) VALUES (?, ?, ?)",
        (g.user['id'], level, changed_at)
    )
    db.commit()

    return jsonify({"level": level, "changed_at": changed_at}), 200
