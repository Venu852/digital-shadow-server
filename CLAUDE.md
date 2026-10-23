# Digital Shadow Server

## Stack
- Python 3.11+
- Flask 3
- SQLite3 (standard library)
- pytest

## Running the server
```bash
# Set up venv if not done
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Run server
python run.py

# Run server and also serve the built dashboard (F:\digital-shadow-dashboard, `npm run build`)
$env:SHADOW_DASHBOARD_DIR="F:\digital-shadow-dashboard\dist"; python run.py
```
SHADOW_DASHBOARD_DIR is optional. When it names an existing folder, app/dashboard.py serves its files at / and returns index.html for any other non-/api path (single-page app fallback); unknown /api paths and paths that escape the folder (..) stay 404.

## Testing
```bash
# Run all tests
python -m pytest -q

# Run smoke test (requires server running)
python scripts/smoke.py

# Fill the server with 6 demo people, 2 teams and 14 days of phone data (requires server running).
# Safe to re-run; device tokens are cached in instance/fake_phones_tokens.json.
python scripts/fake_phones.py [--base-url http://127.0.0.1:5050] [--ishaan-level nothing|team_totals|my_trend]

# Check the read APIs' privacy rules against the fake_phones data (requires server running)
python scripts/inspect_views.py
```

Phase 3 tests share the `World` helper and `world` fixture defined in tests/test_privacy_matrix.py.

## Locked Decisions
- A manager sees an individual only when that person's CURRENT sharing level is 'my_trend' AND they are a member of a team the manager owns. Otherwise 404, never saying which check failed.
- Join team via invite code ONLY; manager cannot add members.
- Team aggregates need at least 3 contributors (current level team_totals or my_trend); otherwise the team is hidden and no numeric field is returned. A day counts only when 3+ contributors have data that day.
- Sharing levels are read at request time on every view; withdrawing consent removes a person from every view immediately (data stays stored until the person deletes it).
- Aggregate responses never contain usernames or account ids.
- Every manager view of a person (view_trend, view_explain) is written to audit_log; a person can always read who viewed them via GET /api/me/access-log.
- A non-'None' team context tag damps the displayed drift by 15 (clamped at 0); the raw value is also returned. A manager viewing a person sees only their own team's context.
- Scoring rules and wording live in app/rules.py (pure functions); shared queries in app/data.py.
- DELETE /api/me removes the account and everything attached; a manager's teams are deleted first.
- Bind to 127.0.0.1 ONLY.
- The server stores nothing from a phone unless that person's sharing level allows it ('nothing' -> 403 "sharing is off"; no consent row means 'nothing').
- Phones upload ONLY the daily summary fields (drift, five levels, confidence, baseline, forecast, unusual_hours, tz); no app names, no raw data. Unknown fields -> 400.
- Phones authenticate with a device token (`Authorization: Bearer`), never the password after pairing. Only the token's SHA-256 hex is stored; the token is returned once.
- Sharing levels: nothing | team_totals | my_trend. Each change adds a sharing_consents row; the newest row is current.

## Standing Rules
- Migrations are append-only (numbered SQL files in app/migrations/).
- Every protected route needs authentication.
- Never commit `instance/` or secrets.
- Dependencies need approval (currently only flask, pytest).
- All errors are returned as JSON: `{"error": "<message>"}`.
- All POST/PUT/DELETE /api/ routes require `X-Requested-With: XMLHttpRequest`, except the device token routes listed in `app/devices.py` TOKEN_ENDPOINTS (pair, /api/device/*), which never read cookies.
- Device token routes are rate limited to 300 requests/hour per device (in-memory).
- All /api/ responses must have specific security headers.
