"""Dev tool: move a group's newest adopted suggestion back in time so the impact check has
"after" days to show. Edits the database directly, so it needs --i-know-this-edits-data.

    python scripts/demo_backdate.py --team "Team Nova" --days 8 --i-know-this-edits-data
"""
import argparse
import datetime
import os
import sqlite3
import sys

DEFAULT_DB = os.environ.get(
    'SHADOW_DB', os.path.join(os.path.dirname(__file__), '..', 'instance', 'shadow.db'))

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--team', required=True, help="the group's name")
    parser.add_argument('--days', type=int, default=8, help="set decided_at to this many days ago (default 8)")
    parser.add_argument('--db', default=DEFAULT_DB, help="SQLite file (default: SHADOW_DB or instance/shadow.db)")
    parser.add_argument('--i-know-this-edits-data', dest='confirmed', action='store_true',
                        help="required: confirms you want to change stored decisions")
    args = parser.parse_args()

    if not args.confirmed:
        sys.exit("Refusing to run: pass --i-know-this-edits-data to change stored decisions.")
    if args.days < 0:
        sys.exit("--days must be 0 or more")
    if not os.path.exists(args.db):
        sys.exit(f"Database not found: {args.db}")

    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    team = db.execute("SELECT id FROM teams WHERE name = ?", (args.team,)).fetchone()
    if team is None:
        sys.exit(f"No group named {args.team!r}")
    decision = db.execute(
        """
        SELECT day, decided_at FROM action_decisions
        WHERE team_id = ? AND decision = 'approved'
        ORDER BY decided_at DESC, day DESC LIMIT 1
        """,
        (team['id'],)
    ).fetchone()
    if decision is None:
        sys.exit(f"{args.team} has no adopted suggestion yet; adopt one in the dashboard first.")

    decided_at = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=args.days)).isoformat()
    db.execute("UPDATE action_decisions SET decided_at = ? WHERE team_id = ? AND day = ?",
               (decided_at, team['id'], decision['day']))
    db.commit()
    db.close()
    print(f"{args.team}: suggestion for {decision['day']} now adopted at {decided_at} "
          f"(was {decision['decided_at']})")

if __name__ == '__main__':
    main()
