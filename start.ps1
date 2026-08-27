# AlphaSplit local startup (Windows PowerShell)
Set-Location $PSScriptRoot

Write-Host "Starting AlphaSplit API at http://127.0.0.1:8000"
python -m engine.api.main --host 127.0.0.1 --port 8000
