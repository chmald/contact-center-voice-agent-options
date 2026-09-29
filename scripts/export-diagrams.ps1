<#
.SYNOPSIS
  Export each page of the architecture .drawio to PNG for the README and docs.

.DESCRIPTION
  Requires draw.io Desktop (winget install JGraph.Draw). Regenerate the .drawio first with
  `python scripts/build-diagrams.py` when the architecture changes.
#>
param(
    [string]$DrawIo = "C:\Program Files\draw.io\draw.io.exe"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Source = Join-Path $Root "docs\assets\voice-live-vs-realtime-api-architecture.drawio"
$OutDir = Join-Path $Root "docs\assets\diagrams"
if (-not (Test-Path $DrawIo)) { throw "draw.io Desktop not found at $DrawIo (winget install JGraph.Draw)." }
New-Item -ItemType Directory -Force $OutDir | Out-Null

$pages = @(
    @{ Index = 1; Name = "01-solution-architecture.png" },
    @{ Index = 2; Name = "02-three-ways-to-connect.png" },
    @{ Index = 3; Name = "03-phone-call-flow.png" },
    @{ Index = 4; Name = "04-deployment-and-regions.png" }
)
foreach ($page in $pages) {
    $out = Join-Path $OutDir $page.Name
    # draw.io 27+ numbers pages from 1; Start-Process -Wait because the desktop app returns immediately otherwise.
    $exportArgs = @("--export", "--format", "png", "--scale", "2", "--border", "20", "--page-index", "$($page.Index)", "--output", "`"$out`"", "`"$Source`"")
    $process = Start-Process -FilePath $DrawIo -ArgumentList $exportArgs -Wait -PassThru -NoNewWindow
    if ($process.ExitCode -ne 0) { throw "draw.io exited with $($process.ExitCode) for page $($page.Index)." }
    if (-not (Test-Path $out)) { throw "Export failed for page $($page.Index)." }
    Write-Host "Exported $($page.Name)"
}
