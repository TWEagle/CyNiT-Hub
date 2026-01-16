Set-Location $PSScriptRoot\..

# Start tray runner in huidige venv (als die al bestaat), anders maakt preflight hem aan.
.\venv\Scripts\python.exe .\scripts\tray_runner.py
