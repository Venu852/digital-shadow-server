"""Fill a running server with six demo people, two teams and 14 days of phone summaries.

Safe to run repeatedly: accounts, teams and memberships are reused, device tokens are
cached in instance/fake_phones_tokens.json, and day uploads replace the same rows.
"""
import argparse
import datetime
import http.cookiejar
import json
import math
import os
import random
import sys
import urllib.error
import urllib.request

PASSWORD = "demo-pass-1234"
DAYS = 14
TOKEN_CACHE = os.path.join(os.path.dirname(__file__), '..', 'instance', 'fake_phones_tokens.json')

TEAMS = {
    "Team Nova": {"manager": "manager.nova", "members": ["aditi", "rohan", "zara"]},
    "Team Atlas": {"manager": "manager.atlas", "members": ["meera", "kabir", "ishaan"]},
}
PEOPLE = {
    "aditi": ("stable", "my_trend"),
    "rohan": ("drifting", "my_trend"),
    "zara": ("mild", "team_totals"),
    "meera": ("recovering", "team_totals"),
    "kabir": ("stable", "my_trend"),
    "ishaan": ("stable", "nothing"),
}
PATTERNS = {
    "stable": lambda i: 10 + math.sin(i * 0.8) * 4,
    "drifting": lambda i: 8 + i * 4.2,
    "mild": lambda i: 14 + i * 1.8,
    "recovering": lambda i: 68 - i * 3.8,
}
LEVEL_KEYS = ["switching", "session", "checks", "screen", "steadiness"]

class Client:
    """One person's HTTP client with its own cookie jar."""

    def __init__(self, base_url):
        self.base_url = base_url.rstrip('/')
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def request(self, method, path, data=None, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        else:
            headers['X-Requested-With'] = 'XMLHttpRequest'
        body = json.dumps(data).encode('utf-8') if data is not None else None
        req = urllib.request.Request(self.base_url + path, data=body, headers=headers, method=method)
        try:
            with self.opener.open(req) as resp:
                content = resp.read().decode('utf-8')
                return resp.status, json.loads(content) if content else None
        except urllib.error.HTTPError as e:
            content = e.read().decode('utf-8')
            return e.code, json.loads(content) if content else None

def expect(status, res, *ok):
    if status not in ok:
        sys.exit(f"Unexpected response {status}: {res}")

def register_or_login(client, username, role):
    status, res = client.request('POST', '/api/register',
                                 {'username': username, 'password': PASSWORD, 'role': role})
    if status == 409:
        status, res = client.request('POST', '/api/login',
                                     {'username': username, 'password': PASSWORD})
    expect(status, res, 200, 201)

def ensure_team(client, name):
    status, res = client.request('POST', '/api/teams', {'name': name})
    if status == 201:
        return res['invite_code']
    expect(status, res, 409)
    status, teams = client.request('GET', '/api/teams')
    expect(status, teams, 200)
    for team in teams:
        if team['name'] == name:
            return team['invite_code']
    sys.exit(f"Team {name!r} exists but belongs to another manager")

def load_tokens():
    try:
        with open(TOKEN_CACHE, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}

def save_tokens(tokens):
    os.makedirs(os.path.dirname(TOKEN_CACHE), exist_ok=True)
    with open(TOKEN_CACHE, 'w', encoding='utf-8') as f:
        json.dump(tokens, f, indent=2)

def ensure_device(client, username, cached_token):
    """Reuse the cached device if its token still works, otherwise pair a new one."""
    if cached_token:
        status, res = client.request('GET', '/api/device/me', token=cached_token)
        if status == 200 and res['username'] == username:
            return cached_token, False
    status, res = client.request('POST', '/api/devices/pair', {
        'username': username, 'password': PASSWORD, 'device_name': f"{username}'s phone"
    })
    expect(status, res, 201)
    return res['device_token'], True

def clamp(value):
    return max(0, min(100, int(round(value))))

def make_summary(rng, pattern, i):
    base = clamp(PATTERNS[pattern](i) + rng.uniform(-3, 3))
    levels = {key: clamp(base + rng.randint(-8, 8)) for key in LEVEL_KEYS}
    drift = clamp(sum(levels.values()) / len(levels))
    usual = rng.randint(170, 230)
    hours = sorted(rng.sample(range(24), rng.randint(0, 3))) if drift > 30 else []
    return {
        'drift': drift,
        'levels': levels,
        'confidence': min(95, 40 + i * 5),
        'baseline': 'calibrating' if i < 7 else 'established',
        'forecast': {'screen_min': usual + drift, 'usual_min': usual},
        'unusual_hours': hours,
        'tz': '+05:30',
    }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:5050')
    parser.add_argument('--ishaan-level', default='nothing', choices=['nothing', 'team_totals', 'my_trend'],
                        help="ishaan's sharing level; anything but 'nothing' uploads his 14 days")
    args = parser.parse_args()

    tokens = load_tokens()
    cache = tokens.setdefault(args.base_url, {})

    invite_codes = {}
    for team_name, team in TEAMS.items():
        manager = Client(args.base_url)
        register_or_login(manager, team['manager'], 'manager')
        invite_codes[team_name] = ensure_team(manager, team_name)

    today = datetime.datetime.now(datetime.UTC).date()
    rows = []
    for team_name, team in TEAMS.items():
        for username in team['members']:
            pattern, level = PEOPLE[username]
            if username == 'ishaan':
                level = args.ishaan_level
            client = Client(args.base_url)
            register_or_login(client, username, 'individual')

            status, res = client.request('POST', '/api/teams/join', {'invite_code': invite_codes[team_name]})
            expect(status, res, 200, 409)
            status, res = client.request('PUT', '/api/me/sharing', {'level': level})
            expect(status, res, 200)

            token, paired = ensure_device(client, username, cache.get(username))
            cache[username] = token
            save_tokens(tokens)

            # Seeded per person so every run produces the same data
            rng = random.Random(f"fake-phones-{username}")
            stored = updated = 0
            result = None
            for i in range(DAYS):
                day = (today - datetime.timedelta(days=DAYS - 1 - i)).isoformat()
                status, res = client.request('PUT', f'/api/device/days/{day}',
                                             make_summary(rng, pattern, i), token=token)
                if status == 403 and res == {'error': 'sharing is off'}:
                    result = "skipped (sharing off)"
                    break
                expect(status, res, 200)
                stored += 1
                updated += res['updated']
            if result is None:
                result = f"uploaded {stored} days ({stored - updated} new, {updated} replaced)"

            rows.append((username, team_name, pattern, level,
                         "paired" if paired else "reused", result))

    headers = ("user", "team", "pattern", "sharing", "device", "result")
    widths = [max(len(str(r[c])) for r in rows + [headers]) for c in range(len(headers))]
    line = "  ".join("{:<%d}" % w for w in widths)
    print(line.format(*headers))
    print(line.format(*("-" * w for w in widths)))
    for row in rows:
        print(line.format(*row))

if __name__ == '__main__':
    main()
