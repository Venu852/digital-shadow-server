import json
import os
import shutil
import sqlite3
import pytest
from flask import Flask
from app import db as app_db

SOURCE = os.path.join(os.path.dirname(__file__), '..', 'app', 'migrations')
OLD_LEVELS = {'switching': 1, 'session': 1, 'checks': 1, 'screen': 1, 'steadiness': 1}
NEW_LEVELS = {'switching': 1, 'session': 1, 'checks': 1, 'screen': 1, 'night': 1, 'timing': 1}

def make_app(tmp_path, files):
    """A bare Flask app whose migrations folder holds only `files` ({name: sql})."""
    root = tmp_path / 'root'
    (root / 'migrations').mkdir(parents=True, exist_ok=True)
    for name in os.listdir(root / 'migrations'):
        os.remove(root / 'migrations' / name)
    for name, sql in files.items():
        (root / 'migrations' / name).write_text(sql, encoding='utf-8')
    app = Flask('migration_test', root_path=str(root))
    app.config['DATABASE'] = str(tmp_path / 'test.db')
    return app

def source(name):
    with open(os.path.join(SOURCE, name), encoding='utf-8') as f:
        return f.read()

def migrate(tmp_path, names, extra=None):
    files = {name: source(name) for name in names}
    files.update(extra or {})
    app = make_app(tmp_path, files)
    app_db.init_db(app)
    with app.app_context():
        app_db.close_db()

def connect(tmp_path):
    conn = sqlite3.connect(tmp_path / 'test.db')
    conn.row_factory = sqlite3.Row
    return conn

def test_004_drops_legacy_rows_and_maps_tags(tmp_path):
    old = ['001_init.sql', '002_devices_sharing_summaries.sql', '003_context_actions_audit.sql']
    migrate(tmp_path, old)

    conn = connect(tmp_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("INSERT INTO accounts (id, username, password_hash, role, created_at) VALUES "
                 "(1, 'boss', 'x', 'manager', 't'), (2, 'alice', 'x', 'individual', 't')")
    tags = ['Deadline crunch', 'Product launch', 'Exam week', 'None']
    for i, tag in enumerate(tags, start=1):
        conn.execute("INSERT INTO teams (id, name, manager_id, invite_code, created_at) VALUES (?, ?, 1, ?, 't')",
                     (i, f'T{i}', f'code{i}'))
        conn.execute("INSERT INTO team_settings (team_id, human_review, context_tag, updated_at) VALUES (?, ?, ?, ?)",
                     (i, i % 2, tag, f'u{i}'))
    conn.execute("INSERT INTO devices (id, account_id, name, token_hash, created_at) VALUES ('d', 2, 'P', 'h', 't')")
    for day, levels in (('2026-01-01', OLD_LEVELS), ('2026-01-02', NEW_LEVELS)):
        conn.execute("INSERT INTO daily_summaries (device_id, day, drift, levels_json, confidence, baseline, received_at)"
                     " VALUES ('d', ?, 1, ?, 50, 'established', 't')", (day, json.dumps(levels, sort_keys=True)))
    conn.commit()
    conn.close()

    migrate(tmp_path, old + ['004_signals_tags.sql'])
    conn = connect(tmp_path)
    conn.execute("PRAGMA foreign_keys = ON")
    assert [r['day'] for r in conn.execute("SELECT day FROM daily_summaries")] == ['2026-01-02']
    rows = conn.execute("SELECT team_id, human_review, context_tag, updated_at FROM team_settings ORDER BY team_id")
    assert [tuple(r) for r in rows] == [
        (1, 1, 'Busy period', 'u1'), (2, 0, 'New routine', 'u2'), (3, 1, 'Exam week', 'u3'), (4, 0, 'None', 'u4')]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE team_settings SET context_tag = 'Deadline crunch' WHERE team_id = 1")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO team_settings (team_id, context_tag, updated_at) VALUES (99, 'Travel', 'u')")
    # Settings still cascade when their team is deleted
    conn.execute("DELETE FROM teams WHERE id = 1")
    assert conn.execute("SELECT COUNT(*) FROM team_settings").fetchone()[0] == 3
    assert [r[0] for r in conn.execute("SELECT version FROM schema_version ORDER BY version")] == [1, 2, 3, 4]
    conn.close()

def test_failing_migration_leaves_nothing_behind(tmp_path):
    names = ['001_init.sql']
    migrate(tmp_path, names)
    broken = {'002_broken.sql': "CREATE TABLE half_done (id INTEGER);\nINSERT INTO no_such_table VALUES (1);"}
    with pytest.raises(sqlite3.OperationalError):
        migrate(tmp_path, names, broken)
    conn = connect(tmp_path)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'half_done'").fetchone() is None
    assert [r[0] for r in conn.execute("SELECT version FROM schema_version")] == [1]
    conn.close()
