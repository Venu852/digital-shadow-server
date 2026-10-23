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
```

## Testing
```bash
# Run all tests
python -m pytest -q

# Run smoke test (requires server running)
python scripts/smoke.py

# Fill the server with 6 demo people, 2 teams and 14 days of phone data (requires server running).
# Safe to re-run; device tokens are cached in instance/fake_phones_tokens.json.
python scripts/fake_phones.py [--base-url http://127.0.0.1:5050]
```

## Locked Decisions
- Managers can only see data with permission (future phase).
- Join team via invite code ONLY; manager cannot add members.
- Groups < 3 people are never shown (future phase).
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
