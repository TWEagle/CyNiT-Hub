
# ============================================================
# run.ps1 — Start CyNiT-Hub via Waitress met gekleurde output
# - venv activeren
# - waitress-serve --call wsgi_prod:create_app
# - log naar .\logs\master-start.md
# - kleurregels: OK = groen, 4xx/warn = geel, 5xx/error = rood, setup = lichtgrijs
# - géén async event handlers (fix voor Runspace-fout in PS 5.1)
# ============================================================

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# 0) Werkmap = map van dit script
Set-Location -Path $PSScriptRoot

# 1) Virtuele omgeving activeren
Write-Host "Activating virtual environment..." -ForegroundColor Gray
$venvActivate = Join-Path -Path "." -ChildPath "venv\Scripts\Activate.ps1"
if (!(Test-Path $venvActivate)) {
    Write-Host "ERROR: venv niet gevonden op $venvActivate" -ForegroundColor Red
    Write-Host "Maak een venv aan: python -m venv venv en installeer dependencies." -ForegroundColor Yellow
    exit 1
}
. $venvActivate

# 2) Controleren of waitress-serve beschikbaar is; zo niet, installeren
Write-Host "Checking waitress availability..." -ForegroundColor Gray
$waitress = Get-Command "waitress-serve" -ErrorAction SilentlyContinue
if (-not $waitress) {
    Write-Host "Installing waitress in venv..." -ForegroundColor Yellow
    pip install waitress | Out-Null
    $waitress = Get-Command "waitress-serve" -ErrorAction SilentlyContinue
    if (-not $waitress) {
        Write-Host "ERROR: waitress-serve niet gevonden na installatie." -ForegroundColor Red
        exit 1
    }
}

# 3) Logs map & bestand
$logDir  = ".\logs"
if (!(Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir "master-start.md"

# 3a) Timestamp header
$ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
$hostAddr = "127.0.0.1"
$port     = 5000

$header = @"
---
start: $ts
host: $hostAddr
port: $port
runner: waitress-serve --call wsgi_prod:create_app
---
"@
$header | Out-File -FilePath $logFile -Encoding utf8 -Append

Write-Host "Logging to: $logFile" -ForegroundColor Gray

# 4) Command voorbereiden
$exe = $waitress.Source
$args = @("--host=$hostAddr","--port=$port","--call","wsgi_prod:create_app")

Write-Host ("Starting Waitress server on http://$($hostAddr):$($port) ...") -ForegroundColor Gray
Write-Host "(druk Ctrl+C om te stoppen)" -ForegroundColor Gray

# 5) Start server in pipeline, kleur en log per regel (zonder events/runspaces)
#    - we mergen stderr in stdout (2>&1), dan 1 pipe met ForEach-Object
& $exe @args 2>&1 | ForEach-Object {
    $line = $_
    if ($null -eq $line) { return }

    # Altijd naar logfile (zonder kleurcodes)
    Add-Content -Path $logFile -Value $line

    # Kleurlogica:
    # - ' OK' aan einde -> Groen
    # - 'Serving on http://' (Waitress startup) -> Lichtgrijs (setup)
    # - 5xx / ERROR / Traceback -> Rood
    # - 4xx / WARNING -> Geel
    # - Setup/statusregels (Activating/Checking/Logging to/Starting/druk Ctrl+C) -> Lichtgrijs
    # - Anders -> Donkergrijs
    $isOkLine = $line -match '\sOK\s*$'
    $isServing = $line -match 'Serving on http://'
    $is5xx  = $line -match '->\s*5\d\d\b' -or $line -match '\bERROR\b' -or $line -match '\bTraceback\b'
    $is4xx  = $line -match '->\s*4\d\d\b' -or $line -match '\bWARNING\b'
    $isSetup = $isServing -or
               $line -match 'Activating virtual environment' -or
               $line -match 'Checking waitress availability' -or
               $line -match '^Logging to:' -or
               $line -match '^Starting Waitress server on ' -or
               $line -match '^\(druk Ctrl\+C om te stoppen\)'

    if ($is5xx) {
        Write-Host $line -ForegroundColor Red
    }
    elseif ($is4xx) {
        Write-Host $line -ForegroundColor Yellow
    }
    elseif ($isOkLine) {
        Write-Host $line -ForegroundColor Green
    }
    elseif ($isSetup) {
        Write-Host $line -ForegroundColor Gray
    }
    else {
        Write-Host $line -ForegroundColor DarkGray
    }
}
``
