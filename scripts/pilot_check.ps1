# End-to-end check of a running Digital Shadow server (25 checks).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\pilot_check.ps1 -Base https://your-server.example
# Creates a test coordinator and a test participant with random names and deletes both at the end.
# Reads SHADOW_ENROLL_CODE from .env.ps1 in the repository root unless -EnvFile is given.
param(
  [Parameter(Mandatory = $true)][string]$Base,
  [string]$EnvFile = (Join-Path (Split-Path $PSScriptRoot -Parent) '.env.ps1')
)
$h = @{ 'X-Requested-With' = 'XMLHttpRequest' }
$enroll = (Select-String -Path $EnvFile -Pattern "ENROLL_CODE\s*=\s*'([^']*)'").Matches[0].Groups[1].Value
$suffix = -join ((97..122) | Get-Random -Count 4 | ForEach-Object { [char]$_ })
$coordName = "pilot-coord-$suffix"
$userName = "pilot-user-$suffix"
$pw = 'Pilot-' + [guid]::NewGuid().ToString('N').Substring(0,12)
$script:fails = 0

function Check($name, $ok, $detail = '') {
  if ($ok) { Write-Host "PASS  $name" -ForegroundColor Green }
  else { Write-Host "FAIL  $name   $detail" -ForegroundColor Red; $script:fails++ }
}
function Call($method, $path, $body, $session, $headers) {
  $p = @{ Method = $method; Uri = "$Base$path"; UseBasicParsing = $true; Headers = $headers }
  if ($null -ne $body) { $p.Body = ($body | ConvertTo-Json -Depth 6 -Compress); $p.ContentType = 'application/json' }
  if ($session) { $p.WebSession = $session }
  try {
    $r = Invoke-WebRequest @p
    $d = $null
    if ($r.Content) { try { $d = $r.Content | ConvertFrom-Json } catch {} }
    return @{ status = [int]$r.StatusCode; data = $d }
  } catch {
    $c = 0
    if ($_.Exception.Response) { $c = [int]$_.Exception.Response.StatusCode }
    return @{ status = $c; data = $null }
  }
}

Write-Host "Pilot check against $Base"
$coordSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$indSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$scratch = New-Object Microsoft.PowerShell.Commands.WebRequestSession

$cfg = Call GET '/api/config' $null $null @{}
Check 'config says an enrollment code is required' ($cfg.status -eq 200 -and $cfg.data.enroll_required -eq $true)

$bad = Call POST '/api/register' @{ username = $coordName; password = $pw; role = 'manager'; enroll_code = 'wrong-code-123' } $scratch $h
Check 'wrong enrollment code is refused (403)' ($bad.status -eq 403) "got $($bad.status)"

$r = Call POST '/api/register' @{ username = $coordName; password = $pw; role = 'manager'; enroll_code = $enroll } $coordSession $h
Check 'coordinator account created (201)' ($r.status -eq 201) "got $($r.status)"
$r = Call POST '/api/register' @{ username = $userName; password = $pw; role = 'individual'; enroll_code = $enroll } $indSession $h
Check 'individual account created (201)' ($r.status -eq 201) "got $($r.status)"

$t = Call POST '/api/teams' @{ name = "Pilot $suffix" } $coordSession $h
Check 'group created with an invite code' ($t.status -eq 201 -and $t.data.invite_code) "got $($t.status)"
$team = $t.data

$pv = Call GET "/api/teams/preview?code=$($team.invite_code)" $null $indSession $h
Check 'join preview shows the 4-line agreement' ($pv.status -eq 200 -and @($pv.data.agreement).Count -eq 4) "got $($pv.status)"
$j0 = Call POST '/api/teams/join' @{ invite_code = $team.invite_code } $indSession $h
Check 'joining without accepting is refused (400)' ($j0.status -eq 400) "got $($j0.status)"
$j = Call POST '/api/teams/join' @{ invite_code = $team.invite_code; accept = $true } $indSession $h
Check 'individual joined the group (200)' ($j.status -eq 200) "got $($j.status)"

$sh = Call PUT '/api/me/sharing' @{ level = 'my_trend' } $indSession $h
Check 'sharing set to My drift trend' ($sh.status -eq 200 -and $sh.data.level -eq 'my_trend') "got $($sh.status)"

$pair = Call POST '/api/devices/pair' @{ username = $userName; password = $pw; device_name = 'pilot phone' } $null @{}
Check 'phone pairing returns a device token (201)' ($pair.status -eq 201 -and $pair.data.device_token) "got $($pair.status)"
$tok = @{ Authorization = "Bearer $($pair.data.device_token)" }
$me = Call GET '/api/device/me' $null $null $tok
Check 'device token works and reports the sharing level' ($me.status -eq 200 -and $me.data.sharing_level -eq 'my_trend') "got $($me.status)"

$day = (Get-Date).ToUniversalTime().AddDays(-1).ToString('yyyy-MM-dd')
$payload = @{ drift = 34; levels = @{ switching = 55; session = 40; checks = 35; screen = 30; night = 20; timing = 25 }; confidence = 76; baseline = 'established'; tz = '+05:30' }
$up = Call PUT "/api/device/days/$day" $payload $null $tok
Check 'daily summary accepted (200)' ($up.status -eq 200) "got $($up.status)"
$badPayload = $payload.Clone(); $badPayload.levels = @{ switching = 55 }
$up2 = Call PUT "/api/device/days/$day" $badPayload $null $tok
Check 'invalid summary is rejected (400)' ($up2.status -eq 400) "got $($up2.status)"

$tr = Call GET '/api/me/trend?days=14' $null $indSession $h
Check 'individual sees the uploaded day on their trend' ($tr.status -eq 200 -and @($tr.data.days).Count -ge 1) "got $($tr.status)"

$ppl = Call GET "/api/teams/$($team.id)/people" $null $coordSession $h
Check 'coordinator sees the person (My drift trend)' ($ppl.status -eq 200 -and @($ppl.data.people).Count -eq 1) "got $($ppl.status)"
$personId = @($ppl.data.people)[0].account_id
$pt = Call GET "/api/teams/$($team.id)/people/$personId/trend?days=14" $null $coordSession $h
Check 'coordinator can open the person trend (200)' ($pt.status -eq 200) "got $($pt.status)"
$log = Call GET '/api/me/access-log?limit=10' $null $indSession $h
Check 'the person sees that view in their access log' ($log.status -eq 200 -and @($log.data).Count -ge 1) "got $($log.status)"

$null = Call PUT '/api/me/sharing' @{ level = 'team_totals' } $indSession $h
$ppl2 = Call GET "/api/teams/$($team.id)/people" $null $coordSession $h
Check 'Group totals only removes the person from the people list' ($ppl2.status -eq 200 -and @($ppl2.data.people).Count -eq 0) "got $($ppl2.status)"
$pt2 = Call GET "/api/teams/$($team.id)/people/$personId/trend?days=14" $null $coordSession $h
Check 'the coordinator now gets 404 on that person' ($pt2.status -eq 404) "got $($pt2.status)"
$null = Call PUT '/api/me/sharing' @{ level = 'nothing' } $indSession $h
$up3 = Call PUT "/api/device/days/$day" $payload $null $tok
Check 'with sharing Nothing the upload is refused (403)' ($up3.status -eq 403) "got $($up3.status)"

$devs = Call GET '/api/devices' $null $indSession $h
$devId = @($devs.data)[0].id
$rv = Call DELETE "/api/devices/$devId" @{} $indSession $h
Check 'device revoked (204)' ($rv.status -eq 204) "got $($rv.status)"
$up4 = Call PUT "/api/device/days/$day" $payload $null $tok
Check 'revoked device is refused (401)' ($up4.status -eq 401) "got $($up4.status)"

$ex = Call GET '/api/me/export' $null $indSession $h
Check 'data export works and contains no hashes' ($ex.status -eq 200 -and (($ex.data | ConvertTo-Json -Depth 8) -notmatch 'password_hash|token_hash')) "got $($ex.status)"

$d1 = Call DELETE '/api/me' @{ password = $pw } $indSession $h
Check 'test individual account deleted (204)' ($d1.status -eq 204) "got $($d1.status)"
$d2 = Call DELETE '/api/me' @{ password = $pw } $coordSession $h
Check 'test coordinator and group deleted (204)' ($d2.status -eq 204) "got $($d2.status)"

if ($script:fails -eq 0) { Write-Host "`nAll 25 checks passed." -ForegroundColor Green }
else { Write-Host "`n$($script:fails) check(s) failed." -ForegroundColor Red }
Write-Host "Now look at the log: Get-Content $(Join-Path (Split-Path $PSScriptRoot -Parent) 'instance\server.log') -Tail 12"
