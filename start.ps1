param(
    [int]$Port = 8000,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$requirements = Join-Path $PSScriptRoot "requirements-lock.txt"
$stampPath = Join-Path $PSScriptRoot ".venv\.alphasplit-requirements.sha256"
$expectedHash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash.ToLowerInvariant()
$installedHash = if (Test-Path -LiteralPath $stampPath) {
    (Get-Content -LiteralPath $stampPath -Raw).Trim().ToLowerInvariant()
} else {
    ""
}

if (-not (Test-Path -LiteralPath $venvPython) -or $installedHash -ne $expectedHash) {
    Write-Host "First run or dependency change detected. Configuring the environment..." -ForegroundColor Yellow
    & (Join-Path $PSScriptRoot "install.ps1")
}

$url = "http://127.0.0.1:$Port/"
$healthUrl = "http://127.0.0.1:$Port/api/health"
$browserJob = $null

if (-not $NoBrowser) {
    $browserJob = Start-Job -ScriptBlock {
        param($TargetUrl, $HealthUrl)
        for ($attempt = 0; $attempt -lt 90; $attempt++) {
            try {
                $response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2
                if ($response.StatusCode -eq 200) {
                    Start-Process $TargetUrl
                    return
                }
            }
            catch {
                Start-Sleep -Seconds 1
            }
        }
    } -ArgumentList $url, $healthUrl
}

Write-Host ""
Write-Host "AlphaSplit is starting at: $url" -ForegroundColor Green
Write-Host "Without an API key, the rule-based Agent is used and the complete demo remains available."
Write-Host "Keep this window open. Press Ctrl+C to stop the service." -ForegroundColor Yellow
Write-Host ""

try {
    & $venvPython -m engine.api.main --mode mock --host 127.0.0.1 --port $Port
}
finally {
    if ($browserJob) {
        Stop-Job -Job $browserJob -ErrorAction SilentlyContinue
        Remove-Job -Job $browserJob -Force -ErrorAction SilentlyContinue
    }
}
