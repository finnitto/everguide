$ErrorActionPreference = "Stop"
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Python 3.12 is required. Install it, then rerun this script." }
}
& $Python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
& $Python scripts\query_osm.py
if ($LASTEXITCODE -ne 0) { throw "OSM query failed; see the error above." }
