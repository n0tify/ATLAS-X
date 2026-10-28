$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot
python -m uvicorn api:app --host 127.0.0.1 --port 8000
