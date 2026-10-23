import datetime
import json
from .db import get_db

def record(actor_id, action, target_id=None, team_id=None, detail=None):
    """Append an audit_log row. The caller commits."""
    get_db().execute(
        "INSERT INTO audit_log (at, actor_id, action, target_id, team_id, detail) VALUES (?, ?, ?, ?, ?, ?)",
        (
            datetime.datetime.now(datetime.UTC).isoformat(), actor_id, action, target_id, team_id,
            json.dumps(detail, sort_keys=True) if detail is not None else None,
        )
    )

def access_log_for(account_id, limit):
    rows = get_db().execute(
        """
        SELECT l.at, a.username AS by_name, l.action, t.name AS team_name
        FROM audit_log l
        LEFT JOIN accounts a ON a.id = l.actor_id
        LEFT JOIN teams t ON t.id = l.team_id
        WHERE l.target_id = ?
        ORDER BY l.id DESC
        LIMIT ?
        """,
        (account_id, limit)
    ).fetchall()
    return [{"at": r['at'], "by": r['by_name'], "action": r['action'], "team": r['team_name']} for r in rows]
