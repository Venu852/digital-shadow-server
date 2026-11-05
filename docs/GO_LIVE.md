# Going live

This guide puts Digital Shadow on the internet from your own laptop, step by step.
You do every account and tunnel step yourself; nothing here needs a domain name.

How it fits together:

```
phone / browser ──HTTPS──▶ tunnel (Tailscale Funnel or Cloudflare) ──http──▶ 127.0.0.1:5050 on your laptop
                                                                               (waitress + Flask + SQLite)
```

- The server only ever listens on `127.0.0.1`. Nobody on your Wi-Fi can reach it directly.
- The tunnel program on the laptop receives the public HTTPS traffic and passes it to
  `http://127.0.0.1:5050`. HTTPS ends at the tunnel.
- Phones pair over the public `https://` address, then use their device token. Phones only
  ever send daily summaries, never raw data or app names.

Contents:

1. [Prepare the server](#1-prepare-the-server) (once, whichever tunnel you use)
2. [Main path: Tailscale Funnel](#2-main-path-tailscale-funnel)
3. [Alternative: Cloudflare named tunnel](#3-alternative-cloudflare-named-tunnel) (needs a domain)
4. [Alternative: Cloudflare quick tunnel](#4-alternative-cloudflare-quick-tunnel) (for a quick test)
5. [Start the server automatically at logon](#5-start-the-server-automatically-at-logon)
6. [Keep the laptop awake](#6-keep-the-laptop-awake)
7. [Daily backups](#7-daily-backups)
8. [Verification checklist](#8-verification-checklist)
9. [Install the app on someone else's phone](#9-install-the-app-on-someone-elses-phone)
10. [Free-tier limits and when the laptop is off](#10-free-tier-limits-and-when-the-laptop-is-off)

All commands are for **Windows PowerShell**. Lines starting with `#` are comments.

---

## 1. Prepare the server

### 1.1 Install the dependencies

```powershell
cd F:\digital-shadow-server
python -m venv .venv            # skip if .venv already exists
.venv\Scripts\python -m pip install -r requirements.txt
```

`requirements.txt` now includes **waitress**, the production web server. (`python run.py`
is Flask's development server; do not put it on the internet.)

### 1.2 Build the dashboard

```powershell
cd F:\digital-shadow-dashboard
npm install                      # first time only
npm run build                    # writes F:\digital-shadow-dashboard\dist
```

### 1.3 Fill in your settings

```powershell
cd F:\digital-shadow-server
Copy-Item .env.ps1.example .env.ps1
notepad .env.ps1
```

`.env.ps1` is listed in `.gitignore` and must never be committed. The settings:

| Setting | What to put | Why |
|---|---|---|
| `SHADOW_PORT` | `5050` | The port the tunnel connects to. |
| `COOKIE_SECURE` | `1` | Sign-in cookies only travel over HTTPS, and browsers are told to always use HTTPS (the `Strict-Transport-Security` header). |
| `SHADOW_CLIENT_IP_HEADER` | `X-Forwarded-For` for Tailscale, `CF-Connecting-IP` for Cloudflare | Lets the server see each visitor's real IP for the login lockout and rate limits. Without it, every visitor looks like `127.0.0.1` (the tunnel). |
| `SHADOW_ENROLL_CODE` | A long random code, for example the output of `.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(12))"` | Nobody can create an account without it. Share it privately with the people you invite. |
| `SHADOW_DASHBOARD_DIR` | `F:\digital-shadow-dashboard\dist` | The server also serves the dashboard website. |
| `SHADOW_RETENTION_DAYS` | `90` (minimum 14) | Daily summaries older than this are deleted. |
| `SHADOW_BACKUP_DIR` | `F:\digital-shadow-backups` | Where the daily backups go (section 7). |

The client IP header is only believed when the connection itself comes from this laptop
(the tunnel). Someone on the internet who sends a fake `X-Forwarded-For` cannot dodge the
limits: the tunnel adds the real address as the last entry, and that is the one the server uses.

### 1.4 Start it by hand once

```powershell
powershell -ExecutionPolicy Bypass -File F:\digital-shadow-server\start_prod.ps1
```

You should see `Digital Shadow serving on http://127.0.0.1:5050 (waitress, 8 threads)`.
In a second PowerShell window:

```powershell
Invoke-RestMethod http://127.0.0.1:5050/api/health
# ok version db
# -- ------- --
# True 1     True
Invoke-RestMethod http://127.0.0.1:5050/api/config
# enroll_required
# ---------------
#            True
```

Leave the server running and set up a tunnel. If you already run `python run.py` for
development, stop it first: only one program can use port 5050.

---

## 2. Main path: Tailscale Funnel

Funnel gives you a free public address like `https://shadow-host.tail1234.ts.net` with a
real HTTPS certificate, without a domain.

### 2.1 Install and sign in

1. Download Tailscale for Windows from <https://tailscale.com/download/windows> and install it.
2. Click the Tailscale icon in the taskbar and **Log in**. Sign in with the account you want
   to own this (a personal account is fine).

### 2.2 Give the laptop a neutral name

The machine name becomes part of the public address, so do not use your own name.

1. Open the admin console at <https://login.tailscale.com/admin/machines>.
2. On your laptop's row, open the **…** menu, choose **Edit machine name**, and set something
   neutral such as `shadow-host`. Turn off **Auto-generate from OS hostname** if it is shown.
3. Optional: under **DNS**, the tailnet name (the `tail1234` part) can be renamed to a
   randomly generated one if the current one says something about you.

### 2.3 Turn on Funnel

In PowerShell (the server must be running, see 1.4):

```powershell
tailscale funnel --bg 5050
```

The first time, the CLI prints a link and asks you to enable **HTTPS certificates** and then
**Funnel** for your tailnet. Open each link, approve it in the browser, then run the command
again. When it works it prints your public address, for example:

```
Available on the internet:
https://shadow-host.tail1234.ts.net/
|-- proxy http://127.0.0.1:5050
```

`--bg` keeps Funnel running in the background, also after a reboot.

| Task | Command |
|---|---|
| See what is shared | `tailscale funnel status` |
| Stop sharing | `tailscale funnel reset` |

The first HTTPS request can take up to a minute while the certificate is issued.

### 2.4 Settings for Funnel

In `.env.ps1`:

```powershell
$env:COOKIE_SECURE = '1'
$env:SHADOW_CLIENT_IP_HEADER = 'X-Forwarded-For'
$env:SHADOW_ENROLL_CODE = '<your long random code>'
$env:SHADOW_DASHBOARD_DIR = 'F:\digital-shadow-dashboard\dist'
$env:SHADOW_RETENTION_DAYS = '90'
```

Restart the server after changing them (close its window, run `start_prod.ps1` again).

### 2.5 Check that real client IPs are logged

1. From your phone **on mobile data** (Wi-Fi off), open `https://<your address>/api/health`.
2. On the laptop:

   ```powershell
   Get-Content F:\digital-shadow-server\instance\server.log -Tail 5
   ```

   The last field of each line is the client IP. It must be your phone's public address,
   **not** `127.0.0.1`:

   ```
   2026-11-01T10:15:02Z GET /api/health 200 2ms 203.0.113.45
   ```

   If it shows `127.0.0.1`, `SHADOW_CLIENT_IP_HEADER` is not set (or the server was not
   restarted after setting it).

The log has one line per request: time, method, path (never the query string), status,
duration and client IP. It never contains bodies, headers, passwords or tokens. It rotates at
5 MB and keeps 5 old files (`server.log.1` … `server.log.5`).

### 2.6 Things to know about Funnel

- **The address is public.** Anyone who finds it can open the sign-in page. What protects you
  is the enrollment code (no account without it), the login lockout (5 wrong passwords lock
  that username from that IP for 5 minutes) and the rate limits (10 registrations per hour
  per IP, 300 requests per hour per paired phone).
- Funnel only listens on ports **443**, **8443** and **10000**. The command above uses 443,
  so the address has no port number.
- Tailscale does not publish Funnel's bandwidth limits. This app sends a few small JSON
  requests per phone per day, so it is far below anything that matters.
- The free **Personal** plan is for **non-commercial use**. Running this for a paid service or a
  company needs a paid plan.

---

## 3. Alternative: Cloudflare named tunnel

Use this if you own a domain whose DNS is on Cloudflare (the free plan is enough). The address
becomes e.g. `https://shadow.example.com`.

### 3.1 Install and log in

```powershell
winget install --id Cloudflare.cloudflared
# open a new PowerShell window so cloudflared is on the PATH
cloudflared tunnel login
```

`login` opens the browser; pick the domain. It saves a certificate to
`C:\Users\<you>\.cloudflared\cert.pem`.

### 3.2 Create the tunnel and its DNS name

```powershell
cloudflared tunnel create digital-shadow
# prints the tunnel ID (a UUID) and writes C:\Users\<you>\.cloudflared\<UUID>.json
cloudflared tunnel route dns digital-shadow shadow.example.com
```

Replace `example.com` with your domain.

### 3.3 Write the config

Create `C:\Users\<you>\.cloudflared\config.yml`:

```yaml
tunnel: <UUID>
credentials-file: C:\Users\<you>\.cloudflared\<UUID>.json

ingress:
  - hostname: shadow.example.com
    service: http://127.0.0.1:5050
  - service: http_status:404
```

The last rule is the catch-all: any other hostname gets a 404.

Test it in the foreground first:

```powershell
cloudflared tunnel run digital-shadow
```

### 3.4 Run it as a Windows service

In an **Administrator** PowerShell:

```powershell
cloudflared service install
```

The service runs as the system account. If it does not start, copy `config.yml` and
`<UUID>.json` into `C:\Windows\System32\config\systemprofile\.cloudflared\`, change
`credentials-file` in that copy to the new path, and restart the service
(`Restart-Service cloudflared`).

### 3.5 Settings for Cloudflare

In `.env.ps1`:

```powershell
$env:COOKIE_SECURE = '1'
$env:SHADOW_CLIENT_IP_HEADER = 'CF-Connecting-IP'
```

The rest is the same as 2.4. Check the log as in 2.5.

### 3.6 Cloudflare dashboard settings

- **SSL/TLS → Edge Certificates → Always Use HTTPS**: on.
- **Security → WAF → Rate limiting rules**: add a rule for requests where
  *URI Path* is in `/api/login`, `/api/register` and `/api/devices/pair`, counted per IP,
  blocking for a while when exceeded (for example 5 requests per 10 seconds). The free plan
  allows one such rule. The server has its own limits too; this stops floods earlier.
- **Optional, Cloudflare Access** (Zero Trust → Access → Applications): put the dashboard
  behind a sign-in (for example a one-time code sent to an allowed email list). Phones cannot
  answer an Access sign-in, so add a second application for the same hostname with the paths
  `/api/devices/pair` and `/api/device/*` and a **Bypass** policy (Everyone). Without the bypass,
  phones cannot pair or upload.

---

## 4. Alternative: Cloudflare quick tunnel

For a quick test only. No account and no domain needed:

```powershell
cloudflared tunnel --url http://127.0.0.1:5050
```

It prints a random address like `https://random-words.trycloudflare.com`. That address
**changes every time you run the command**, so every phone has to be paired again each time.
Use `SHADOW_CLIENT_IP_HEADER=CF-Connecting-IP`. Stop it with Ctrl+C.

---

## 5. Start the server automatically at logon

Run this once in PowerShell (as yourself, not as Administrator):

```powershell
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "F:\digital-shadow-server\start_prod.ps1"' `
  -WorkingDirectory 'F:\digital-shadow-server'
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'Digital Shadow server' -Action $action -Trigger $trigger -Settings $settings
```

- Start it now without logging off: `Start-ScheduledTask -TaskName 'Digital Shadow server'`
- Stop it: `Stop-ScheduledTask -TaskName 'Digital Shadow server'`
- Remove it: `Unregister-ScheduledTask -TaskName 'Digital Shadow server'`

Tailscale (with `--bg`) and the cloudflared service start by themselves.

---

## 6. Keep the laptop awake

While plugged in, the laptop must never sleep or hibernate:

```powershell
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
```

If you close the lid: **Control Panel → Hardware and Sound → Power Options → Choose what
closing the lid does → When I close the lid, Plugged in: Do nothing**.

The screen may still turn off; that is fine.

---

## 7. Daily backups

Make one backup by hand:

```powershell
cd F:\digital-shadow-server
.venv\Scripts\python scripts\backup.py
# F:\digital-shadow-backups\shadow-20261101-0300.db
```

It uses SQLite's online backup, so it is safe while the server is running, and keeps the 14
newest backups. Register the daily task once (runs at 03:00, or as soon as the laptop is on
after a missed run):

```powershell
powershell -ExecutionPolicy Bypass -File F:\digital-shadow-server\scripts\backup_task.ps1
Start-ScheduledTask -TaskName 'Digital Shadow backup'     # try it now
```

**Restoring:** the live database is the file `SHADOW_DB` points to (set in `.env.ps1`;
only when `SHADOW_DB` is not set is it `instance\shadow.db`).

1. Stop the server (close its window, or
   `Stop-ScheduledTask -TaskName 'Digital Shadow server'`).
2. Load the settings and check the target:

   ```powershell
   cd F:\digital-shadow-server
   . .\.env.ps1
   $env:SHADOW_DB
   ```

3. Keep the current file, and move the WAL files next to it aside if they exist:

   ```powershell
   Copy-Item $env:SHADOW_DB "$env:SHADOW_DB.before-restore"
   foreach ($x in '-wal', '-shm') { if (Test-Path "$env:SHADOW_DB$x") { Move-Item "$env:SHADOW_DB$x" "$env:SHADOW_DB$x.before-restore" } }
   ```

4. Copy the backup in:

   ```powershell
   Copy-Item "$env:SHADOW_BACKUP_DIR\shadow-YYYYmmdd-HHMM.db" $env:SHADOW_DB -Force
   ```

5. Start the server and check `http://127.0.0.1:5050/api/health`.

Backups contain everyone's account and daily summaries: keep them on this laptop or on a
disk only you control.

---

## 8. Verification checklist

Do this after setting up, and after any change to the tunnel.

- [ ] **HTTPS health check from another network.** On your phone with Wi-Fi off, open
      `https://<your address>/api/health`. You see `{"db":true,"ok":true,"version":"1"}`.
- [ ] **HSTS header present.** From any computer:
      ```powershell
      (Invoke-WebRequest -UseBasicParsing https://<your address>/api/health).Headers['Strict-Transport-Security']
      # max-age=15552000
      ```
      If it is empty, `COOKIE_SECURE` is not `1`.
- [ ] **Security headers.** The same response also has `Content-Security-Policy`,
      `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.
- [ ] **Enrollment code required.** On the dashboard, *Create account* shows an *Enrollment code*
      field, and a wrong code says "Enrollment code required.".
- [ ] **Sign-in from a phone on mobile data.** Open `https://<your address>` in the phone's
      browser and sign in.
- [ ] **Real IPs in the log** (section 2.5).
- [ ] **Pairing.** Pair the app with the `https://` address (section 9) and tap *Sync now*.
- [ ] **Revoking a device.** Sign in to the dashboard as that person, open *My privacy*, and in
      *My devices* click **Revoke** for the phone. In the app, *Sync now* now reports that the
      phone is signed out. Pair again afterwards.
- [ ] **Backups** are appearing in `SHADOW_BACKUP_DIR`.

---

## 9. Install the app on someone else's phone

The app is not in the Play Store, so you send the APK file yourself.

1. Build it on the laptop:

   ```powershell
   cd F:\test_app
   flutter build apk --release
   # build\app\outputs\flutter-apk\app-release.apk
   ```

   The debug APK (`flutter build apk --debug` → `app-debug.apk`) also works, but is larger.
   **Release builds accept only `https://` server addresses**
   ("Use an https:// address in release builds."); debug builds also allow
   `http://127.0.0.1:5050` for local testing.
   The release build is currently signed with the debug key, which is fine for sharing by hand
   but not for the Play Store.
2. Send the file (USB cable, a shared drive, a messaging app).
3. On the phone, open the file. Android asks to **allow installing unknown apps** from the app
   that opened it (Files, Chrome, …): allow it, install, then you can switch it off again.
4. Open the app. It asks for **Usage access**: in the settings page that opens, find the app and
   turn **Permit usage access** on. This is what lets the phone measure its own rhythm; the raw
   usage data never leaves the phone.
5. In the app, open the **Privacy** tab and pair: server address
   `https://<your address>` (no trailing path), the person's username and password (their
   account was created on the dashboard with the enrollment code), and a device name.
   The password is used once and not stored; the phone keeps only its device token.
6. Choose a sharing level. With *Nothing*, the server refuses and stores nothing.

---

## 10. Free-tier limits and when the laptop is off

**Free tiers:**

- Tailscale Personal: free for personal, non-commercial use; Funnel bandwidth limits are not
  published.
- Cloudflare free plan: tunnels are free; one rate-limiting rule; Access is free for a small
  number of users.
- Cloudflare quick tunnels: for testing, with no uptime promise, and the address changes every run.

**When the laptop is off, asleep or the server is stopped:**

- The dashboard does not load and phones cannot reach the server.
- Phones keep each day's summary in their outbox and show the sync status as offline (or a
  server error while the tunnel is up but the server is not). Nothing is lost: the next sync
  after the laptop is back sends every waiting day.
- A day that arrives later than `SHADOW_RETENTION_DAYS` is still accepted, then removed at the
  next clean-up (on startup and at most every 6 hours), like any other old day.
- The login lockout and rate-limit counters are kept in memory, so they reset when the server
  restarts.
