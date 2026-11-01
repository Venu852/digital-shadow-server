r"""Copy the live database with sqlite3's online backup API.

Writes shadow-YYYYmmdd-HHMM.db into SHADOW_BACKUP_DIR (default F:\digital-shadow-backups),
keeps the 14 newest backups and prints the new file's path. Safe while the server runs.

    .venv\Scripts\python scripts\backup.py
"""
import datetime
import glob
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT, 'instance', 'shadow.db')
DEFAULT_DIR = r'F:\digital-shadow-backups'
KEEP = 14

def backup(db_path, backup_dir, now=None, keep=KEEP):
    """Writes one backup and removes all but the `keep` newest. Returns the new path."""
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f'No database at {db_path}')
    now = now or datetime.datetime.now()
    os.makedirs(backup_dir, exist_ok=True)
    target = os.path.join(backup_dir, now.strftime('shadow-%Y%m%d-%H%M.db'))

    source = sqlite3.connect(db_path)
    dest = sqlite3.connect(target)
    try:
        with dest:
            source.backup(dest)
    finally:
        dest.close()
        source.close()

    # The timestamped names sort oldest first
    backups = sorted(glob.glob(os.path.join(backup_dir, 'shadow-????????-????.db')))
    for old in backups[:-keep]:
        os.remove(old)
    return target

def main():
    db_path = os.environ.get('SHADOW_DB', DEFAULT_DB)
    backup_dir = os.environ.get('SHADOW_BACKUP_DIR') or DEFAULT_DIR
    try:
        print(backup(db_path, backup_dir))
    except (OSError, sqlite3.Error) as e:
        print(f'Backup failed: {e}', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
