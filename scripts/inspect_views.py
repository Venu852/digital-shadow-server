"""Check the privacy rules of the read APIs against a server loaded by fake_phones.py."""
import argparse
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request

PASSWORD = "demo-pass-1234"

class Client:
    """One logged-in person with their own cookie jar."""

    def __init__(self, base_url, username):
        self.base_url = base_url.rstrip('/')
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        status, res = self.request('POST', '/api/login', {'username': username, 'password': PASSWORD})
        if status != 200:
            sys.exit(f"Could not log in as {username}: {status} {res}")

    def request(self, method, path, data=None):
        headers = {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}
        body = json.dumps(data).encode('utf-8') if data is not None else None
        req = urllib.request.Request(self.base_url + path, data=body, headers=headers, method=method)
        try:
            with self.opener.open(req) as resp:
                content = resp.read().decode('utf-8')
                return resp.status, json.loads(content) if content else None
        except urllib.error.HTTPError as e:
            content = e.read().decode('utf-8')
            return e.code, json.loads(content) if content else None

    def get(self, path):
        return self.request('GET', path)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:5050')
    args = parser.parse_args()

    nova_mgr = Client(args.base_url, 'manager.nova')
    atlas_mgr = Client(args.base_url, 'manager.atlas')
    rohan = Client(args.base_url, 'rohan')
    zara = Client(args.base_url, 'zara')
    Client(args.base_url, 'aditi')

    results = []

    def check(name, condition, detail=""):
        results.append(condition)
        print(f"{'PASS' if condition else 'FAIL'}: {name}" + ("" if condition else f"  {detail}"))

    _, overview = nova_mgr.get('/api/manager/overview')
    nova = next((t for t in overview['teams'] if t['name'] == 'Team Nova'), None)
    _, atlas_overview = atlas_mgr.get('/api/manager/overview')
    atlas = next((t for t in atlas_overview['teams'] if t['name'] == 'Team Atlas'), None)
    check("Nova overview shows numbers and Atlas is hidden",
          nova is not None and nova['hidden'] is False and isinstance(nova['avg'], int)
          and atlas is not None and atlas['hidden'] is True and atlas['avg'] is None,
          f"nova={nova} atlas={atlas}")
    if nova is None:
        sys.exit("Team Nova not found; run scripts/fake_phones.py first")
    nova_id = nova['id']

    _, people = nova_mgr.get(f'/api/teams/{nova_id}/people')
    names = {p['username']: p['account_id'] for p in people['people']}
    check("Nova people list contains aditi and rohan but not zara",
          'aditi' in names and 'rohan' in names and 'zara' not in names, f"people={sorted(names)}")

    _, agg = nova_mgr.get(f'/api/teams/{nova_id}/aggregate')
    check("Nova aggregate has contributors 3",
          agg['latest'] is not None and agg['latest']['contributors'] == 3, f"latest={agg['latest']}")

    status, trend = nova_mgr.get(f"/api/teams/{nova_id}/people/{names.get('rohan')}/trend")
    check("rohan's trend as manager.nova returns 14 days",
          status == 200 and len(trend['days']) == 14, f"status={status}")

    _, zara_me = zara.get('/api/me')
    status, _ = nova_mgr.get(f"/api/teams/{nova_id}/people/{zara_me['id']}/trend")
    check("zara's trend as manager.nova returns 404", status == 404, f"status={status}")

    status, _ = atlas_mgr.get(f'/api/teams/{nova_id}/aggregate')
    check("manager.atlas cannot read Nova's aggregate (404)", status == 404, f"status={status}")

    _, log = rohan.get('/api/me/access-log')
    check("rohan's access-log shows manager.nova's view",
          any(e['by'] == 'manager.nova' and e['action'] == 'view_trend' for e in log), f"log={log[:3]}")

    status, my_trend = rohan.get('/api/me/trend')
    check("rohan's /api/me/trend returns 14 days",
          status == 200 and len(my_trend['days']) == 14, f"status={status}")

    sys.exit(0 if all(results) else 1)

if __name__ == '__main__':
    main()
