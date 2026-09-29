<#
.SYNOPSIS
  Point one standalone example at the shared knowledge base (knowledge/ azd project).

.DESCRIPTION
  Writes SHARED_RESOURCE_GROUP, AZURE_SEARCH_SERVICE_NAME, AZURE_SEARCH_INDEX and
  AZURE_SEARCH_SEMANTIC_CONFIG into the example's azd environment. On the next `azd provision`
  the example keeps its own Foundry resource (SHARED_FOUNDRY_NAME stays empty) and its
  shared-access module grants the app's managed identity Search Index Data Reader on the index.

  Examples already in shared-platform mode (SHARED_FOUNDRY_NAME set) use the platform's own
  search service instead; load the corpus there with scripts/load-knowledge-index.py.

.EXAMPLE
  ./scripts/use-knowledge-base.ps1 -Example realtime-api -KnowledgeEnv kbdemo
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("voice-live-api", "realtime-api", "foundry-voice-agent")]
    [string]$Example,

    [Parameter(Mandatory = $true)]
    [string]$KnowledgeEnv,

    [string]$ExampleEnv = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$KnowledgeDir = Join-Path $Root "knowledge"
$ExampleDir = Join-Path $Root "examples\$Example"

function Get-AzdValues([string]$Dir, [string]$EnvName) {
    Push-Location $Dir
    try {
        $azdArgs = @("env", "get-values")
        if ($EnvName) { $azdArgs += @("--environment", $EnvName) }
        $raw = & azd @azdArgs
        if ($LASTEXITCODE -ne 0) { throw "azd env get-values failed in $Dir" }
    } finally { Pop-Location }
    $values = @{}
    foreach ($line in $raw) {
        if ($line -match '^([A-Za-z0-9_]+)="?(.*?)"?$') { $values[$Matches[1]] = $Matches[2] }
    }
    return $values
}

function Set-AzdValue([string]$Name, [string]$Value) {
    Push-Location $ExampleDir
    try {
        $azdArgs = @("env", "set", $Name, $Value)
        if ($ExampleEnv) { $azdArgs += @("--environment", $ExampleEnv) }
        & azd @azdArgs | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "azd env set $Name failed" }
    } finally { Pop-Location }
}

$knowledge = Get-AzdValues $KnowledgeDir $KnowledgeEnv
foreach ($required in "KNOWLEDGE_RESOURCE_GROUP", "AZURE_SEARCH_SERVICE_NAME", "AZURE_SUBSCRIPTION_ID") {
    if (-not $knowledge[$required]) { throw "Knowledge env '$KnowledgeEnv' has no $required - run 'azd up' in knowledge/ first." }
}
$exampleValues = Get-AzdValues $ExampleDir $ExampleEnv
if ($exampleValues["SHARED_FOUNDRY_NAME"]) {
    throw "examples\$Example is in shared-platform mode (SHARED_FOUNDRY_NAME=$($exampleValues['SHARED_FOUNDRY_NAME'])); it already uses the platform's search service."
}
if ($exampleValues["AZURE_SUBSCRIPTION_ID"] -and $exampleValues["AZURE_SUBSCRIPTION_ID"] -ne $knowledge["AZURE_SUBSCRIPTION_ID"]) {
    throw "The knowledge base is in subscription $($knowledge['AZURE_SUBSCRIPTION_ID']) but examples\$Example deploys to $($exampleValues['AZURE_SUBSCRIPTION_ID']); cross-subscription role grants are not supported by the templates."
}

Set-AzdValue "SHARED_RESOURCE_GROUP" $knowledge["KNOWLEDGE_RESOURCE_GROUP"]
Set-AzdValue "AZURE_SEARCH_SERVICE_NAME" $knowledge["AZURE_SEARCH_SERVICE_NAME"]
Set-AzdValue "AZURE_SEARCH_INDEX" $(if ($knowledge["AZURE_SEARCH_INDEX"]) { $knowledge["AZURE_SEARCH_INDEX"] } else { "knowledge" })
Set-AzdValue "AZURE_SEARCH_SEMANTIC_CONFIG" $(if ($knowledge["AZURE_SEARCH_SEMANTIC_CONFIG"]) { $knowledge["AZURE_SEARCH_SEMANTIC_CONFIG"] } else { "default" })

Write-Host "examples\$Example now uses search service $($knowledge['AZURE_SEARCH_SERVICE_NAME']) (index $($knowledge['AZURE_SEARCH_INDEX']))."
Write-Host "Next: cd examples\$Example; azd provision   (grants the app identity Search Index Data Reader and sets AZURE_SEARCH_ENDPOINT)"
