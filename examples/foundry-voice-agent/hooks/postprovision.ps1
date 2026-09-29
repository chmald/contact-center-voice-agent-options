# azd hook paths must stay inside the project folder, so this wrapper calls the shared repo script.
# Creates a new version of the Foundry voice agent from config/agent-profile.json.
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$python = if (Test-Path (Join-Path $root ".venv\Scripts\python.exe")) { Join-Path $root ".venv\Scripts\python.exe" } else { "python" }

& $python -c "import azure.ai.projects, azure.identity" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing agent tooling (scripts/requirements-agent.txt)..."
    & $python -m pip install -q -r (Join-Path $root "scripts\requirements-agent.txt")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

& $python (Join-Path $root "scripts\create-voice-agent.py")
exit $LASTEXITCODE
