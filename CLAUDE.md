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
```

## Locked Decisions
- Managers can only see data with permission (future phase).
- Join team via invite code ONLY; manager cannot add members.
- Groups < 3 people are never shown (future phase).
- Bind to 127.0.0.1 ONLY.

## Standing Rules
- Migrations are append-only (numbered SQL files in app/migrations/).
- Every protected route needs authentication.
- Never commit `instance/` or secrets.
- Dependencies need approval (currently only flask, pytest).
- All errors are returned as JSON: `{"error": "<message>"}`.
- All POST/PUT/DELETE /api/ routes require `X-Requested-With: XMLHttpRequest`.
- All /api/ responses must have specific security headers.
