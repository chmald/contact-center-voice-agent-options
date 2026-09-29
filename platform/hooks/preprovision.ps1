# azd hook paths must stay inside the project folder, so this wrapper calls the shared repo script.
$script = Join-Path $PSScriptRoot "..\..\scripts\check-realtime-quota.ps1"
& $script -Platform
exit $LASTEXITCODE
