"""Deletes old daily summaries and audit rows. The purge takes "today" so tests can drive it."""
import datetime
import os
import time

DEFAULT_RETENTION_DAYS = 90
MIN_RETENTION_DAYS = 14
DEFAULT_AUDIT_RETENTION_DAYS = 365
PURGE_INTERVAL = 6 * 3600

def retention_settings():
    """(summary days, audit days) from SHADOW_RETENTION_DAYS and SHADOW_AUDIT_RETENTION_DAYS."""
    days = int(os.environ.get('SHADOW_RETENTION_DAYS', DEFAULT_RETENTION_DAYS))
    audit_days = int(os.environ.get('SHADOW_AUDIT_RETENTION_DAYS', DEFAULT_AUDIT_RETENTION_DAYS))
    return max(MIN_RETENTION_DAYS, days), audit_days

def purge(db, today, retention_days, audit_retention_days):
    """Delete daily_summaries older than `retention_days` before `today` (a date) and audit_log
    rows older than `audit_retention_days`. Returns the number of rows removed from each."""
    summary_cutoff = (today - datetime.timedelta(days=retention_days)).isoformat()
    audit_cutoff = (today - datetime.timedelta(days=audit_retention_days)).isoformat()
    summaries = db.execute("DELETE FROM daily_summaries WHERE day < ?", (summary_cutoff,)).rowcount
    # `at` is an ISO timestamp, so comparing with a date string keeps the cutoff day itself
    audit = db.execute("DELETE FROM audit_log WHERE at < ?", (audit_cutoff,)).rowcount
    db.commit()
    return {"daily_summaries": summaries, "audit_log": audit}

def run_purge(app, db):
    days, audit_days = app.config['RETENTION_DAYS'], app.config['AUDIT_RETENTION_DAYS']
    app.last_purge = time.monotonic()
    return purge(db, datetime.datetime.now(datetime.UTC).date(), days, audit_days)

def purge_due(app):
    return time.monotonic() - app.last_purge >= PURGE_INTERVAL
