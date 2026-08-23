# AlphaSplit local startup (Windows PowerShell)
Set-Location $PSScriptRoot

Write-Host "Installing dependencies..."
pip install fastapi uvicorn pydantic flask "pandas>=1.5.0,<3.0" "numpy>=1.23.0"

Write-Host "Starting AlphaSplit API at http://127.0.0.1:8000"
python -m engine.api.main --host 127.0.0.1 --port 8000
