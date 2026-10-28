<#
.SYNOPSIS
    Start ATLAS-X development servers (backend + frontend)

.DESCRIPTION
    Starts the FastAPI backend on port 8000 and Vite frontend on port 5173.
    Uses separate console windows for each server process.

.NOTES
    Run from the ATLAS-X repository root.
    Requires: Python 3.11+, Node.js 20+, dependencies installed.
#>

param(
    [switch]$KillExisting
)

$repoRoot = $PSScriptRoot
$backendPort = 8000
$frontendPort = 5173

Write-Host "=== ATLAS-X Development Server Launcher ===" -ForegroundColor Cyan
Write-Host "Repository: $repoRoot" -ForegroundColor Gray
Write-Host "Backend port: $backendPort" -ForegroundColor Gray
Write-Host "Frontend port: $frontendPort" -ForegroundColor Gray

# Kill existing ATLAS-X processes on our ports if requested
if ($KillExisting) {
    Write-Host "`nChecking for existing processes on ports $backendPort and $frontendPort..." -ForegroundColor Yellow

    $ports = @($backendPort, $frontendPort)
    foreach ($port in $ports) {
        $connections = netstat -ano | Select-String ":$port\s"
        if ($connections) {
            foreach ($line in $connections) {
                $parts = $line -split '\s+'
                $processId = $parts[-1]
                if ($processId -ne 0) {
                    try {
                        Stop-Process -Id $processId -Force -ErrorAction Stop
                        Write-Host "  Killed process $processId on port $port" -ForegroundColor Green
                    } catch {
                        $errorMessage = $_.Exception.Message
                        $msg = "  Could not kill process $processId on port ${port}: " + $errorMessage
                        Write-Host $msg -ForegroundColor Red
                    }
                }
            }
        }
    }
}

# Check if ports are free
$ports = @($backendPort, $frontendPort)
foreach ($port in $ports) {
    $inUse = netstat -ano | Select-String ":$port\s" | Where-Object { $_ -match "LISTENING" }
    if ($inUse) {
        Write-Host "`nWARNING: Port $port is still in use:" -ForegroundColor Red
        Write-Host "  $inUse" -ForegroundColor Red
        Write-Host "  Use -KillExisting to attempt automatic cleanup, or stop manually." -ForegroundColor Yellow
        exit 1
    }
}

# Start backend in a new console window
Write-Host "`nStarting FastAPI backend on http://127.0.0.1:$backendPort..." -ForegroundColor Cyan
$backendProcess = Start-Process python -ArgumentList "-m uvicorn api:app --host 127.0.0.1 --port 8000" -WorkingDirectory $repoRoot -PassThru -WindowStyle Normal
Write-Host "  Backend process started (PID: $($backendProcess.Id))" -ForegroundColor Gray

# Start frontend in a new console window
Write-Host "`nStarting Vite frontend on http://localhost:$frontendPort..." -ForegroundColor Cyan
$frontendProcess = Start-Process npm -ArgumentList "run dev" -WorkingDirectory "$repoRoot\frontend" -PassThru -WindowStyle Normal
Write-Host "  Frontend process started (PID: $($frontendProcess.Id))" -ForegroundColor Gray

Write-Host "`nWaiting for servers to start..." -ForegroundColor Yellow
Start-Sleep 8

# Health checks
Write-Host "`nVerifying backend health..." -ForegroundColor Cyan
$backendHealthy = $false
for ($i = 0; $i -lt 15; $i++) {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$backendPort/health" -Method GET -TimeoutSec 10 -UseBasicParsing
        if ($response.StatusCode -eq 200) {
            Write-Host "  Backend healthy: $($response.Content)" -ForegroundColor Green
            $backendHealthy = $true
            break
        }
    } catch {
        Write-Host "  Attempt $($i + 1)/15: Waiting for backend..." -ForegroundColor Gray
        Start-Sleep 2
    }
}

if (-not $backendHealthy) {
    Write-Host "`nERROR: Backend health check failed!" -ForegroundColor Red
    exit 1
}

Write-Host "`nVerifying frontend..." -ForegroundColor Cyan
$frontendHealthy = $false
for ($i = 0; $i -lt 20; $i++) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:$frontendPort" -Method GET -TimeoutSec 10 -UseBasicParsing
        if ($response.StatusCode -eq 200 -and $response.Content -match "ATLAS-X") {
            Write-Host "  Frontend healthy" -ForegroundColor Green
            $frontendHealthy = $true
            break
        }
    } catch {
        Write-Host "  Attempt $($i + 1)/20: Waiting for frontend..." -ForegroundColor Gray
        Start-Sleep 2
    }
}

if (-not $frontendHealthy) {
    Write-Host "`nERROR: Frontend health check failed!" -ForegroundColor Red
    exit 1
}

Write-Host "`n=== ATLAS-X is running! ===" -ForegroundColor Green
Write-Host "Frontend: http://localhost:$frontendPort" -ForegroundColor Cyan
Write-Host "  Dashboard: http://localhost:$frontendPort/dashboard" -ForegroundColor Cyan
Write-Host "Backend API: http://127.0.0.1:$backendPort" -ForegroundColor Cyan
Write-Host "  Health: http://127.0.0.1:$backendPort/health" -ForegroundColor Cyan
Write-Host "  API Docs: http://127.0.0.1:$backendPort/docs" -ForegroundColor Cyan
Write-Host "`nProcess IDs:" -ForegroundColor Gray
Write-Host "  Backend:  PID $($backendProcess.Id)" -ForegroundColor Gray
Write-Host "  Frontend: PID $($frontendProcess.Id)" -ForegroundColor Gray
Write-Host "`nServers are running in separate console windows." -ForegroundColor Gray
Write-Host "Close those windows to stop the servers." -ForegroundColor Gray
Write-Host "`nThis window can be closed." -ForegroundColor Yellow