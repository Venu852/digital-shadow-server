# Digital Shadow Server

## Running the server
1. Create a venv: `python -m venv .venv`
2. Activate venv: `.venv\Scripts\activate`
3. Install deps: `pip install -r requirements.txt`
4. Run: `python run.py`

## Testing
Run `python -m pytest`

## Documentation

The full documentation set lives in the separate `digital-shadow-docs` repository
(`https://github.com/<your-github-name>/digital-shadow-docs`; on the reference machine
`F:\digital-shadow-docs`). For this server, start with:

- `03-admin-setup-guide.md`: installation, production configuration, tunnels, backups
- `06-api-reference.md`: every route
- `08-operations-runbook.md`: start and stop, backups and restore, users, incidents
- `09-troubleshooting.md`: known problems and fixes

`scripts\pilot_check.ps1` runs 25 end-to-end checks against a live server:
`powershell -ExecutionPolicy Bypass -File scripts\pilot_check.ps1 -Base https://your-server.example`
