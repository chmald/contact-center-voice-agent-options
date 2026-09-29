param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("voice-live-api", "realtime-api", "foundry-voice-agent")]
    [string]$Example
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ExampleDir = Join-Path $Root "examples\$Example"
$EnvFile = Join-Path $ExampleDir ".env.local"

if (Test-Path -LiteralPath $EnvFile) {
    Get-Content -LiteralPath $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
        $name, $value = $line.Split("=", 2)
        [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim(), "Process")
    }
} else {
    Write-Host "No examples\$Example\.env.local found. After provisioning, run:"
    Write-Host "  azd env get-values > examples\$Example\.env.local"
}

$env:PYTHONPATH = @(
    (Join-Path $Root "shared"),
    (Join-Path $ExampleDir "src")
) -join [IO.Path]::PathSeparator
$env:AGENT_PROFILE_PATH = Join-Path $Root "config\agent-profile.json"

python -m uvicorn main:app --app-dir (Join-Path $ExampleDir "src") --port 8000 --reload
