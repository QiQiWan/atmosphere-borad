@echo off
setlocal enabledelayedexpansion
cd /d %~dp0

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  set PYTHON_CMD=py -3
) else (
  set PYTHON_CMD=python
)

where node >nul 2>nul
if not %ERRORLEVEL%==0 (
  echo Node.js is required. Recommended version: Node 18 or later.
  pause
  exit /b 1
)

if not exist .venv (
  %PYTHON_CMD% -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt

start "atmosphere-backend" cmd /k "cd /d %~dp0backend && ..\.venv\Scripts\python.exe app.py"

if not exist node_modules (
  where pnpm >nul 2>nul
  if !ERRORLEVEL!==0 (
    pnpm install
  ) else (
    npm install
  )
)

where pnpm >nul 2>nul
if %ERRORLEVEL%==0 (
  pnpm dev
) else (
  npm run dev
)
