# azd hook paths must stay inside the project folder, so this wrapper calls the shared repo script.
# Creates a new version of the Foundry voice agent from config/agent-profile.json.
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$python = "python"
foreach ($candidate in @(".venv/Scripts/python.exe", ".venv/bin/python")) {
    if (Test-Path (Join-Path $root $candidate)) { $python = Join-Path $root $candidate; break }
}

& $python -c "import azure.ai.projects, azure.identity" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing agent tooling (scripts/requirements-agent.txt)..."
    & $python -m pip install -q -r (Join-Path $root "scripts\requirements-agent.txt")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

& $python (Join-Path $root "scripts\create-voice-agent.py")
exit $LASTEXITCODE
