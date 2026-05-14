$ErrorActionPreference = "Stop"

if (!(Test-Path ".venv")) {
  python -m venv .venv
}

if (!(.\.venv\Scripts\python.exe -m pip --version 2>$null)) {
  python -m pip --python .\.venv\Scripts\python.exe install --upgrade pip
}

.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

if (!(Test-Path "frontend\node_modules")) {
  Push-Location frontend
  npm.cmd install
  Pop-Location
}

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$PWD\frontend'; npm.cmd run dev -- --host 127.0.0.1"

Write-Host "Backend:   http://127.0.0.1:8000"
Write-Host "Dashboard: http://127.0.0.1:5173"
