# azd hook paths must stay inside the project folder, so this wrapper calls the shared repo loader.
# Creates/updates the 'knowledge' index and uploads config/knowledge-base.json (synthetic).
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = if (Test-Path (Join-Path $root ".venv\Scripts\python.exe")) { Join-Path $root ".venv\Scripts\python.exe" } else { "python" }

& $python -c "import azure.identity" 2>$null
if ($LASTEXITCODE -ne 0) {
    & $python -m pip install -q azure-identity==1.25.3
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$endpoint = $env:AZURE_SEARCH_ENDPOINT
if (-not $endpoint) { throw "AZURE_SEARCH_ENDPOINT is not set; did provisioning succeed?" }
$index = if ($env:AZURE_SEARCH_INDEX) { $env:AZURE_SEARCH_INDEX } else { "knowledge" }

& $python (Join-Path $root "scripts\load-knowledge-index.py") --endpoint $endpoint --index $index --recreate
exit $LASTEXITCODE
