import sqlite3
import os
import datetime
from flask import g, current_app

def get_db():
    if 'db' not in g:
        db_path = current_app.config['DATABASE']
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON;")
        g.db.execute("PRAGMA journal_mode = WAL;")
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db(app):
    db_path = app.config['DATABASE']
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    with app.app_context():
        db = get_db()
        # Check if schema_version exists
        try:
            res = db.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
            current_version = res['version'] if res else 0
        except sqlite3.OperationalError:
            current_version = 0

        migrations_dir = os.path.join(app.root_path, 'migrations')
        migration_files = sorted([f for f in os.listdir(migrations_dir) if f.endswith('.sql')])

        for filename in migration_files:
            version = int(filename.split('_')[0])
            if version > current_version:
                with open(os.path.join(migrations_dir, filename), 'r') as f:
                    script = f.read()
                applied_at = datetime.datetime.now(datetime.UTC).isoformat()
                # executescript runs in autocommit mode, so wrap the script and its version
                # row in one explicit transaction: a failing migration leaves nothing behind
                try:
                    db.executescript(
                        "BEGIN;\n" + script + "\n;"
                        f"INSERT INTO schema_version (version, applied_at) VALUES ({version}, '{applied_at}');\n"
                        "COMMIT;"
                    )
                except sqlite3.Error:
                    if db.in_transaction:
                        db.execute("ROLLBACK")
                    raise
