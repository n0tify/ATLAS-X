$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot
$p = Start-Process python -ArgumentList '-m uvicorn api:app --host 127.0.0.1 --port 8000 --log-level debug' -PassThru -WindowStyle Normal
Write-Host "Started process ID: $($p.Id)"
Start-Sleep 5
try {
$response = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -Method GET
Write-Host "SUCCESS: $($response.Content)"
} catch {
Write-Error $_.Exception.Message
}
if (Get-Process -Id $p.Id -ErrorAction SilentlyContinue) {
Stop-Process -Id $p.Id
Write-Host 'Stopped process'
} else {
Write-Host 'Process already terminated'
}
