# PowerShell script to launch Transit Planner demo backend on Windows

$ErrorActionPreference = "Stop"

Write-Host "Initializing Transit Planner Demo Database..." -ForegroundColor Cyan
& ".\.venv\Scripts\python.exe" -m backend.app.cli init --mode demo

Write-Host "Starting Transit Planner Backend on http://127.0.0.1:8000..." -ForegroundColor Green
& ".\.venv\Scripts\python.exe" -m backend.app.cli serve --host 127.0.0.1 --port 8000 --mode demo
