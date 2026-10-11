param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venvRoot = Join-Path $PSScriptRoot ".venv"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
$requirements = Join-Path $PSScriptRoot "requirements-lock.txt"
$stampPath = Join-Path $venvRoot ".alphasplit-requirements.sha256"

function Get-BasePython {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        & py -3.11 -c "import sys; assert sys.version_info[:2] == (3, 11)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return @{ Command = "py"; Prefix = @("-3.11") }
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        & python -c "import sys; assert sys.version_info >= (3, 10); assert sys.maxsize > 2**32" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return @{ Command = "python"; Prefix = @() }
        }
    }

    throw "No compatible 64-bit Python was found. Install Python 3.11 (64-bit) and enable Add Python to PATH."
}

if (-not (Test-Path -LiteralPath $requirements)) {
    throw "Missing dependency lock file: $requirements"
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "[1/3] Creating the project virtual environment (.venv)..." -ForegroundColor Cyan
    $basePython = Get-BasePython
    & $basePython.Command @($basePython.Prefix) -m venv $venvRoot
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython)) {
        throw "Failed to create the virtual environment."
    }
}
else {
    Write-Host "[1/3] Found the project virtual environment (.venv)." -ForegroundColor DarkCyan
}

$expectedHash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash.ToLowerInvariant()
$installedHash = if (Test-Path -LiteralPath $stampPath) {
    (Get-Content -LiteralPath $stampPath -Raw).Trim().ToLowerInvariant()
} else {
    ""
}

if ($Force -or $installedHash -ne $expectedHash) {
    Write-Host "[2/3] Installing locked dependencies. The first run requires internet access and may take 1-5 minutes..." -ForegroundColor Cyan
    & $venvPython -m pip install --disable-pip-version-check -r $requirements
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed. Check the network or proxy settings, then run the launcher again."
    }
    [System.IO.File]::WriteAllText($stampPath, $expectedHash, [System.Text.UTF8Encoding]::new($false))
}
else {
    Write-Host "[2/3] Dependencies are unchanged; installation skipped." -ForegroundColor DarkCyan
}

Write-Host "[3/3] Validating the runtime environment..." -ForegroundColor Cyan
& $venvPython -c "import fastapi, uvicorn, pandas, numpy, pydantic; print('Environment validation passed.')"
if ($LASTEXITCODE -ne 0) {
    throw "Environment validation failed. Run .\install.ps1 -Force to reinstall dependencies."
}

Write-Output $venvPython
