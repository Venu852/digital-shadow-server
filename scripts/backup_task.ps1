# Registers a daily Windows scheduled task that backs up the database at 03:00.
# Run once:   powershell -ExecutionPolicy Bypass -File F:\digital-shadow-server\scripts\backup_task.ps1
# The task calls this script again with -Run, which loads .env.ps1 and runs scripts\backup.py.
# Remove it:  Unregister-ScheduledTask -TaskName 'Digital Shadow backup'
param([switch]$Run, [string]$At = '03:00')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent

if ($Run) {
    $envFile = Join-Path $root '.env.ps1'
    if (Test-Path $envFile) { . $envFile }
    & (Join-Path $root '.venv\Scripts\python.exe') (Join-Path $root 'scripts\backup.py')
    exit $LASTEXITCODE
}

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Run" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $At
# Runs a missed backup as soon as the laptop is on again
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'Digital Shadow backup' -Action $action -Trigger $trigger `
    -Settings $settings -Description 'Daily copy of the Digital Shadow database' -Force | Out-Null
Write-Host "Registered 'Digital Shadow backup' (daily at $At). Test it now with:"
Write-Host "  Start-ScheduledTask -TaskName 'Digital Shadow backup'"
