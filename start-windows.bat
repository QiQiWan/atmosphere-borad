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

if not defined BACKEND_PORT set BACKEND_PORT=52000
for /f "usebackq tokens=1,* delims==" %%A in (`findstr /R "^BACKEND_PORT=" .env 2^>nul`) do set BACKEND_PORT=%%B
for /f "usebackq tokens=1,* delims==" %%A in (`findstr /R "^BACKEND_PORT=" backend\.env 2^>nul`) do set BACKEND_PORT=%%B
if "%SKIP_KILL_BACKEND_PORT%"=="" set SKIP_KILL_BACKEND_PORT=false
if /I not "%SKIP_KILL_BACKEND_PORT%"=="true" (
  echo Checking stale backend processes on port %BACKEND_PORT%...
  for /f "tokens=5" %%P in ('netstat -ano -p tcp ^| findstr /C:":%BACKEND_PORT%" ^| findstr /C:"LISTENING"') do (
    if not "%%P"=="0" (
      echo Stopping stale process on port %BACKEND_PORT%: PID %%P
      taskkill /F /PID %%P >nul 2>nul
    )
  )
)


call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt

echo Running pre-start server database cache checker...
.\.venv\Scripts\python.exe backend\cache_checker.py
if not %ERRORLEVEL%==0 (
  echo Cache checker failed in strict mode. Backend will not be started.
  pause
  exit /b 1
)

start "atmosphere-backend" cmd /k "cd /d %~dp0backend && ..\.venv\Scripts\python.exe app.py"

echo Waiting for backend http://127.0.0.1:%BACKEND_PORT%/api/borad/health ...
for /l %%i in (1,1,30) do (
  powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:%BACKEND_PORT%/api/borad/health' -TimeoutSec 2; $j = $r.Content | ConvertFrom-Json; if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500 -and $j.version -eq '1.7.7') { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>nul
  if !ERRORLEVEL!==0 goto backend_ready
  timeout /t 1 /nobreak >nul
)
echo Backend v1.7.7 health check did not respond in 30 seconds. Frontend will still start; check backend window for errors.
:backend_ready

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
