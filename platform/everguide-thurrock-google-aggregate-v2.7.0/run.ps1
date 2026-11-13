$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not $env:GOOGLE_MAPS_API_KEY) {
    Write-Host "Set GOOGLE_MAPS_API_KEY in this PowerShell session first." -ForegroundColor Yellow
    Write-Host '$env:GOOGLE_MAPS_API_KEY = "YOUR_KEY"'
    exit 1
}

$Python = "py"
& $Python -3.12 --version *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.12 is required. Install it or adjust run.ps1 to your Python launcher."
}

if (-not (Test-Path ".venv")) {
    & $Python -3.12 -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe .\scripts\run_comparison.py
if ($LASTEXITCODE -ne 0) { throw "Comparison failed with exit code $LASTEXITCODE" }
