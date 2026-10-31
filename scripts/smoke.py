import urllib.request
import urllib.parse
import json
import random
import string
import http.cookiejar
import sys

BASE_URL = "http://127.0.0.1:5050"

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

def request(method, path, data=None):
    url = f"{BASE_URL}{path}"
    headers = {
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/json'
    }
    body = json.dumps(data).encode('utf-8') if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with opener.open(req) as resp:
            status = resp.status
            content = resp.read().decode('utf-8')
            res_data = json.loads(content) if content else None
            return status, res_data
    except urllib.error.HTTPError as e:
        content = e.read().decode('utf-8')
        res_data = json.loads(content) if content else None
        return e.code, res_data

def rand_str(length=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def run_smoke_test():
    all_passed = True

    def check(step_name, condition, extra=""):
        nonlocal all_passed
        if condition:
            print(f"PASS: {step_name}")
        else:
            print(f"FAIL: {step_name} {extra}")
            all_passed = False

    mgr_user = f"mgr_{rand_str()}"
    ind_user = f"ind_{rand_str()}"
    password = "Password123!"

    # 1. Register Manager
    status, res = request("POST", "/api/register", {
        "username": mgr_user,
        "password": password,
        "role": "manager"
    })
    check("Register Manager", status == 201 and res.get("username") == mgr_user)

    # 2. Create Team
    status, res = request("POST", "/api/teams", {"name": f"Team_{rand_str()}"})
    check("Create Team", status == 201 and "invite_code" in res)
    invite_code = res.get("invite_code") if res else None

    # 3. Register Individual (this switches session context)
    status, res = request("POST", "/api/register", {
        "username": ind_user,
        "password": password,
        "role": "individual"
    })
    check("Register Individual", status == 201 and res.get("username") == ind_user)

    # 4. Join Team
    if invite_code:
        status, res = request("POST", "/api/teams/join", {"invite_code": invite_code, "accept": True})
        check("Join Team", status == 200 and "team_id" in res)

    # 5. List Teams as Individual
    status, res = request("GET", "/api/teams")
    check("List Teams (Individual)", status == 200 and isinstance(res, list) and len(res) == 1 and "invite_code" not in res[0])

    if all_passed:
        print("\nAll smoke tests passed successfully!")
        sys.exit(0)
    else:
        print("\nSome smoke tests failed!")
        sys.exit(1)

if __name__ == "__main__":
    run_smoke_test()
