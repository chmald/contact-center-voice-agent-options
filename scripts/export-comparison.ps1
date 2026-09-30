<#
.SYNOPSIS
  Export the self-contained comparison HTML to a one-page PDF using headless Edge.

.DESCRIPTION
  Uses a temporary browser profile, leaving existing browser sessions untouched.
  Removes link targets from the print copy so the distributed PDF cannot embed
  machine-specific file URLs. The original HTML retains its navigation links.
#>
param(
    [string]$Edge = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Source = Join-Path $Root "docs\assets\comparison-one-pager.html"
$Destination = Join-Path $Root "docs\assets\comparison-one-pager.pdf"
if (-not (Test-Path $Edge)) { throw "Microsoft Edge not found at $Edge. Supply -Edge with its executable path." }

$TempDir = Join-Path ([IO.Path]::GetTempPath()) ("voice-comparison-export-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $TempDir | Out-Null
try {
    $PrintSource = Join-Path $TempDir "comparison.html"
    $PrintOutput = Join-Path $TempDir "comparison.pdf"
    $Profile = Join-Path $TempDir "profile"
    $html = [IO.File]::ReadAllText($Source)
    # All styles are inline; only navigation targets differ in the print copy.
    $html = [regex]::Replace($html, '(?i)\s+href\s*=\s*(?:"[^"]*"|''[^'']*'')', '')
    [IO.File]::WriteAllText($PrintSource, $html, [Text.UTF8Encoding]::new($false))
    $url = ([uri]$PrintSource).AbsoluteUri
    $exportArgs = @(
        "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
        "--no-pdf-header-footer", "--user-data-dir=`"$Profile`"",
        "--print-to-pdf=`"$PrintOutput`"", "`"$url`""
    )
    $process = Start-Process -FilePath $Edge -ArgumentList $exportArgs -Wait -PassThru -NoNewWindow
    if ($process.ExitCode -ne 0) { throw "Edge PDF export failed with exit code $($process.ExitCode)." }
    if (-not (Test-Path $PrintOutput)) { throw "Edge did not create the comparison PDF." }
    $pdf = [Text.Encoding]::Latin1.GetString([IO.File]::ReadAllBytes($PrintOutput))
    # Edge emits uncompressed page dictionaries, so this also catches print overflow.
    $pages = [regex]::Matches($pdf, '/Type\s*/Page\b').Count
    if (-not $pdf.StartsWith('%PDF-') -or $pages -ne 1) {
        throw "Expected a one-page PDF; found $pages pages. Check the HTML print layout."
    }
    if ($pdf -match 'file:///') { throw "PDF contains a local file URL; refusing to publish it." }
    Copy-Item -LiteralPath $PrintOutput -Destination $Destination -Force
    Write-Host "Exported docs/assets/comparison-one-pager.pdf (1 page; no local file URLs)"
}
finally {
    Remove-Item -LiteralPath $TempDir -Recurse -Force -ErrorAction SilentlyContinue
}