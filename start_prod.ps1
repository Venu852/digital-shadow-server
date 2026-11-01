# Starts the production server with the settings from .env.ps1 (never committed).
# Usage: powershell -ExecutionPolicy Bypass -File F:\digital-shadow-server\start_prod.ps1
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$envFile = Join-Path $root '.env.ps1'
if (-not (Test-Path $envFile)) {
    Write-Error "Missing $envFile. Copy .env.ps1.example to .env.ps1 and fill it in."
    exit 1
}
. $envFile

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Error "Missing $python. Create the venv first (see CLAUDE.md)."
    exit 1
}
Set-Location $root
& $python (Join-Path $root 'run_prod.py')
