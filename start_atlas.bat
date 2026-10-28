@echo off
REM ATLAS-X Development Server Launcher (Batch version)
REM Starts FastAPI backend on port 8000 and Vite frontend on port 5173

set REPO_ROOT=%~dp0
set BACKEND_PORT=8000
set FRONTEND_PORT=5173

echo =========================================
echo   ATLAS-X Development Server Launcher
echo =========================================
echo Repository: %REPO_ROOT%
echo Backend port: %BACKEND_PORT%
echo Frontend port: %FRONTEND_PORT%
echo.

REM Check if ports are in use
netstat -ano | findstr ":%BACKEND_PORT% " | findstr "LISTENING" >nul
if not errorlevel 1 (
    echo WARNING: Port %BACKEND_PORT% is already in use.
    echo Please stop the existing process or use the PowerShell script with -KillExisting.
    exit /b 1
)

netstat -ano | findstr ":%FRONTEND_PORT% " | findstr "LISTENING" >nul
if not errorlevel 1 (
    echo WARNING: Port %FRONTEND_PORT% is already in use.
    echo Please stop the existing process or use the PowerShell script with -KillExisting.
    exit /b 1
)

echo Starting FastAPI backend on http://127.0.0.1:%BACKEND_PORT%...
start "ATLAS-X Backend" cmd /k "cd /d %REPO_ROOT% && python -m uvicorn api:app --host 127.0.0.1 --port %BACKEND_PORT%"

echo Starting Vite frontend on http://localhost:%FRONTEND_PORT%...
start "ATLAS-X Frontend" cmd /k "cd /d %REPO_ROOT%\frontend && npm run dev"

echo.
echo Waiting for servers to start...
timeout /t 8 >nul

echo.
echo Verifying backend health...
powershell -Command "try { $r = iwr -Uri 'http://127.0.0.1:%BACKEND_PORT%/health' -UseBasicParsing -TimeoutSec 10; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if errorlevel 1 (
    echo WARNING: Could not verify backend health. Check the backend window for errors.
) else (
    echo Backend is healthy.
)

echo Verifying frontend...
powershell -Command "try { $r = iwr -Uri 'http://localhost:%FRONTEND_PORT%' -UseBasicParsing -TimeoutSec 10; if ($r.StatusCode -eq 200 -and $r.Content -match 'ATLAS-X') { exit 0 } else { exit 1 } } catch { exit 1 }"
if errorlevel 1 (
    echo WARNING: Could not verify frontend. Check the frontend window for errors.
) else (
    echo Frontend is healthy.
)

echo.
echo =========================================
echo   ATLAS-X is running!
echo =========================================
echo Frontend: http://localhost:%FRONTEND_PORT%
echo   Dashboard: http://localhost:%FRONTEND_PORT%/dashboard
echo Backend API: http://127.0.0.1:%BACKEND_PORT%
echo   Health: http://127.0.0.1:%BACKEND_PORT%/health
echo   API Docs: http://127.0.0.1:%BACKEND_PORT%/docs
echo.
echo Two console windows have been opened for the servers.
echo Close them to stop the servers.
echo.
pause
