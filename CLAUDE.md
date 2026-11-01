# Digital Shadow Server

## Stack
- Python 3.11+
- Flask 3
- waitress (production server, run_prod.py)
- SQLite3 (standard library)
- pytest

## Running the server
```bash
# Set up venv if not done
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Run server (development)
python run.py

# Production (waitress, 127.0.0.1:SHADOW_PORT, 8 threads); loads the untracked .env.ps1
# (copy .env.ps1.example). Going live behind a tunnel: docs/GO_LIVE.md
powershell -ExecutionPolicy Bypass -File start_prod.ps1

# Back up the database (sqlite3 online backup) into SHADOW_BACKUP_DIR (default F:\digital-shadow-backups), keeps 14
.venv\Scripts\python scripts\backup.py
# Register the daily backup task once
powershell -ExecutionPolicy Bypass -File scripts\backup_task.ps1

# Run server and also serve the built dashboard (F:\digital-shadow-dashboard, `npm run build`)
$env:SHADOW_DASHBOARD_DIR="F:\digital-shadow-dashboard\dist"; python run.py
```
SHADOW_RETENTION_DAYS (default 90, minimum 14) and SHADOW_AUDIT_RETENTION_DAYS (default 365) set how long daily_summaries and audit_log rows are kept; app/retention.py purges on startup and at most every 6 hours (before_request).

Production settings (all optional; see .env.ps1.example):
- COOKIE_SECURE=1: Secure session cookie and Strict-Transport-Security (max-age 15552000). Set only behind HTTPS.
- SHADOW_CLIENT_IP_HEADER (default empty = ignore proxy headers): when set AND the connection comes from loopback, app/clientip.py client_ip() takes the client IP from that header (X-Forwarded-For: the right-most entry that parses as an IP; any other header, e.g. CF-Connecting-IP: its value if it is an IP); otherwise the connection address. Used by the login/pairing lockout, the registration limit and the request log. run_prod.py passes clear_untrusted_proxy_headers=False so waitress does not strip X-Forwarded-For first.
- SHADOW_ENROLL_CODE: when set, POST /api/register needs a matching "enroll_code" (hmac.compare_digest), else 403 "Enrollment code required.". Unset = open registration (development).
- SHADOW_PORT (default 5050), SHADOW_BACKUP_DIR (scripts/backup.py).

Request log: instance/server.log (app/requestlog.py, rotating 5 MB x 5; config LOG_FILE), one line per request: UTC time, method, path without query string, status, duration, client IP. Never bodies, headers, passwords or tokens.

SHADOW_DASHBOARD_DIR is optional. When it names an existing folder, app/dashboard.py serves its files at / and returns index.html for any other non-/api path (single-page app fallback); unknown /api paths and paths that escape the folder (..) stay 404.

## Testing
```bash
# Run all tests
python -m pytest -q

# Run smoke test (requires server running)
python scripts/smoke.py

# Fill the server with 6 demo people, 2 teams and 14 days of phone data (requires server running).
# Each day carries the six signal levels and drift = their mean, rounded half up.
# Safe to re-run; device tokens are cached in instance/fake_phones_tokens.json.
python scripts/fake_phones.py [--base-url http://127.0.0.1:5050] [--ishaan-level nothing|team_totals|my_trend]

# Check the read APIs' privacy rules against the fake_phones data (requires server running)
python scripts/inspect_views.py

# Dev only: set a group's newest adopted suggestion to N days ago so the impact check has data
python scripts/demo_backdate.py --team "Team Nova" --days 8 --i-know-this-edits-data
```

Phase 3 tests share the `World` helper and `world` fixture defined in tests/test_privacy_matrix.py.

## Locked Decisions
- A manager sees an individual only when that person's CURRENT sharing level is 'my_trend' AND they are a member of a team the manager owns. Otherwise 404, never saying which check failed.
- Join team via invite code ONLY; manager cannot add members.
- Team aggregates need at least 3 contributors (current level team_totals or my_trend); otherwise the team is hidden and no numeric field is returned. A day counts only when 3+ contributors have data that day.
- Sharing levels are read at request time on every view; withdrawing consent removes a person from every view immediately (data stays stored until the person deletes it).
- Aggregate responses never contain usernames or account ids.
- Every manager view of a person (view_trend, view_explain) is written to audit_log; a person can always read who viewed them via GET /api/me/access-log.
- Context tags: None | Exam week | Travel | Holiday or break | Busy period | New routine. A non-'None' team context tag damps the displayed drift by 15 (clamped at 0); the raw value is also returned. A manager viewing a person sees only their own team's context.
- Scoring rules and wording live in app/rules.py (pure functions); shared queries in app/data.py.
- DELETE /api/me removes the account and everything attached; a manager's teams are deleted first.
- Bind to 127.0.0.1 ONLY.
- The server stores nothing from a phone unless that person's sharing level allows it ('nothing' -> 403 "sharing is off"; no consent row means 'nothing').
- Phones upload ONLY the daily summary fields (drift, levels, confidence, baseline, forecast, unusual_hours, tz); no app names, no raw data. Unknown fields -> 400.
- `levels` holds exactly the six signals, each an int 0-100, in this order: switching (App switching), session (Session length), checks (Phone checks), screen (Screen time), night (Late-night use), timing (Routine timing). Any other key set -> 400. The keys live in app/rules.py SIGNALS.
- SUGGESTION_THRESHOLD (30, app/rules.py): a group day whose displayed average drift is at or above it gets a group suggestion for its top signal (the 4 newest such days, shown to the coordinator).
- GET /api/me/suggestions (individuals only; managers 403): when the person's latest displayed drift is 20 (PERSONAL_SUGGESTION_THRESHOLD) or more, up to 2 personal suggestions for the highest signals, else []. Only the person ever sees these.
- Wording: the product measures a person's own phone-use rhythm and how it shifts, never performance, productivity or wellbeing.
- Phones authenticate with a device token (`Authorization: Bearer`), never the password after pairing. Only the token's SHA-256 hex is stored; the token is returned once.
- Sharing levels: nothing | team_totals | my_trend. Each change adds a sharing_consents row; the newest row is current.
- A person sets their level from the dashboard (PUT /api/me/sharing, cookie) or from a paired phone (PUT /api/device/sharing, Bearer token). Both use app/sharing.py set_sharing: a row is added only for the first choice or a real change; both return 200 {level, changed_at}, invalid level -> 400.

- Joining a group: GET /api/teams/preview?code= (individuals only, else 403; case-insensitive; unknown code -> 404 "Invite code not found."; 20 calls/hour per account, in-memory, then 429) returns {team:{name}, coordinator:{username}, agreement}. The four agreement lines are GROUP_AGREEMENT in app/rules.py. POST /api/teams/join needs "accept": true, else 400 "Please confirm the group agreement.".
- Coordinator decisions live in action_decisions: 'approved' = Adopt, 'dismissed' = Not now. PUT /api/teams/<id>/actions/<day> stores, with either decision, the signal the suggestion list shows for that day (action_decisions.signal, migration 005), so impact and group updates never change afterwards. Impact and group updates use the STORED signal and leave out decisions whose signal is NULL (or not one of the six keys). At app start, data.backfill_decision_signals() fills NULL signals from current data when that day still has 3+ contributors, otherwise leaves them NULL; it only touches NULL rows, so re-running it changes nothing (the pure part is rules.backfill_signals).
- GET /api/teams/<id>/impact (that team's coordinator; other teams 404): hidden team -> {hidden: true, items: []}. Otherwise one item per 'approved' decision decided in the last 60 days, newest first, comparing the 7 calendar days before and the 7 after the UTC date of decided_at (that date itself is in neither). Only days with 3+ contributors count; drift = mean raw team average, signal_level = mean average level of the adopted signal; null when a window has no days; change null unless both windows have days; complete = after.days >= 5; note "An observation, not proof.".
- GET /api/me/group-updates (individuals): every group the person belongs to, at any sharing level, with its 'approved' decisions from the last 30 days as {day, signal_label, text} (the group suggestion text). No numbers.
- GET /api/teams/<id>/weekday-pattern?weeks=8 (coordinator of that team; weeks 2-26 else 400): raw daily team average per weekday (Mon=0) over the window ending tomorrow UTC. A weekday gets avg only with 3+ days; highest only when 4+ weekdays have an avg. Hidden team -> every avg null, days 0, highest null.
- GET /api/me/export (individuals): JSON attachment digital-shadow-export.json with the account {username, role, created_at}, sharing history, devices {id, name, created_at, last_seen_at, revoked}, all daily_summaries from the caller's devices, the access log and group memberships. Never password_hash, token_hash or anyone else's data.
- Retention: daily_summaries older than SHADOW_RETENTION_DAYS and audit_log rows older than SHADOW_AUDIT_RETENTION_DAYS are deleted (app/retention.py purge(db, today, ...), a pure function of "today").

## Standing Rules
- Migrations are append-only (numbered SQL files in app/migrations/). Each file runs atomically with its schema_version row (app/db.py); never put BEGIN/COMMIT in a migration file.
- Every protected route needs authentication.
- Never commit `instance/` or secrets.
- Dependencies need approval (currently only flask, pytest).
- All errors are returned as JSON: `{"error": "<message>"}`.
- All POST/PUT/DELETE /api/ routes require `X-Requested-With: XMLHttpRequest`, except the device token routes listed in `app/devices.py` TOKEN_ENDPOINTS (pair, /api/device/*), which never read cookies.
- Device token routes are rate limited to 300 requests/hour per device (in-memory).
- POST /api/register is limited to 10 per hour per client IP (in-memory, 429); created accounts and wrong enrollment codes count, other rejections (bad fields, taken username) do not.
- Every response has X-Content-Type-Options nosniff, X-Frame-Options DENY, Referrer-Policy no-referrer, Permissions-Policy "geolocation=(), camera=(), microphone=()", Cache-Control no-store and the CSP in app/__init__.py (script-src 'self', no inline scripts: the built dashboard must keep loading under it); HSTS only when COOKIE_SECURE=1.
- Public routes (no login): GET /api/health -> {"ok": true, "version": "1", "db": <SELECT 1 worked>}; GET /api/config -> {"enroll_required": bool}.
- Never log passwords, tokens or request bodies.
