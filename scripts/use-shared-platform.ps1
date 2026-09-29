<#
.SYNOPSIS
  Point one example app at the shared platform (single AI endpoint, knowledge index, ACS).

.DESCRIPTION
  Reads the outputs of the platform/ azd environment and writes them into the example's
  azd environment, enables the requested phone channels, and generates a
  TELEPHONY_WEBHOOK_SECRET if one is not already set. Run `azd up` in the example
  folder afterwards. Nothing is deployed by this script.

.EXAMPLE
  ./scripts/use-shared-platform.ps1 -Example realtime-api -PlatformEnv voice-shared -Telephony acs,twilio
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("voice-live-api", "realtime-api", "foundry-voice-agent")]
    [string]$Example,

    [Parameter(Mandatory = $true)]
    [string]$PlatformEnv,

    [string]$ExampleEnv = "",

    [ValidateSet("acs", "twilio")]
    [string[]]$Telephony = @(),

    [string]$TwilioAuthToken = "",

    [string]$OverflowNumber = "",

    # Region for Container Apps/ACR/Log Analytics when ACA capacity is constrained in the AI region.
    [string]$AppLocation = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$PlatformDir = Join-Path $Root "platform"
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

function New-UrlSafeSecret {
    $bytes = [System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
    return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

$platform = Get-AzdValues $PlatformDir $PlatformEnv
foreach ($required in "SHARED_RESOURCE_GROUP", "SHARED_FOUNDRY_NAME", "AZURE_TENANT_ID", "AZURE_SUBSCRIPTION_ID", "AZURE_LOCATION") {
    if (-not $platform[$required]) { throw "Platform env '$PlatformEnv' has no $required - run 'azd provision' in platform/ first." }
}

$current = Get-AzdValues $ExampleDir $ExampleEnv

# Same tenant, subscription, and region as the platform: one subscription, one quota pool.
Set-AzdValue "AZURE_TENANT_ID" $platform["AZURE_TENANT_ID"]
Set-AzdValue "AZURE_SUBSCRIPTION_ID" $platform["AZURE_SUBSCRIPTION_ID"]
Set-AzdValue "AZURE_LOCATION" $platform["AZURE_LOCATION"]
Set-AzdValue "SHARED_RESOURCE_GROUP" $platform["SHARED_RESOURCE_GROUP"]
Set-AzdValue "SHARED_FOUNDRY_NAME" $platform["SHARED_FOUNDRY_NAME"]

if ($AppLocation) {
    $acaRegions = az provider show --namespace Microsoft.App --subscription $platform["AZURE_SUBSCRIPTION_ID"] --query "resourceTypes[?resourceType=='managedEnvironments'].locations[]" -o tsv
    $normalized = $acaRegions | ForEach-Object { $_.ToLowerInvariant().Replace(" ", "") }
    if ($LASTEXITCODE -eq 0 -and $normalized -and ($normalized -notcontains $AppLocation.ToLowerInvariant())) {
        throw "Container Apps managed environments are not offered in '$AppLocation' for this subscription."
    }
    Set-AzdValue "AZURE_APP_LOCATION" $AppLocation
    Write-Host "Container Apps, ACR, and Log Analytics will deploy to $AppLocation; the AI endpoint stays in $($platform['AZURE_LOCATION'])."
}

if ($Example -eq "foundry-voice-agent") {
    if (-not $platform["SHARED_FOUNDRY_PROJECT"]) { throw "Platform env has no SHARED_FOUNDRY_PROJECT - re-run 'azd provision' in platform/ (v1.2 adds the voice-agent project)." }
    Set-AzdValue "SHARED_FOUNDRY_PROJECT" $platform["SHARED_FOUNDRY_PROJECT"]
}

if ($Example -eq "realtime-api") {
    Set-AzdValue "AZURE_OPENAI_REALTIME_MODEL" $platform["AZURE_OPENAI_REALTIME_MODEL"]
    Set-AzdValue "AZURE_OPENAI_REALTIME_DEPLOYMENT" $platform["AZURE_OPENAI_REALTIME_DEPLOYMENT"]
}

if ($platform["AZURE_SEARCH_SERVICE_NAME"]) {
    Set-AzdValue "AZURE_SEARCH_SERVICE_NAME" $platform["AZURE_SEARCH_SERVICE_NAME"]
}

if ($Telephony.Count -gt 0) {
    if ($Telephony -contains "acs") {
        if (-not $platform["ACS_RESOURCE_NAME"]) { throw "Platform has no ACS resource (DEPLOY_COMMUNICATION_SERVICES=false)." }
        Set-AzdValue "ACS_RESOURCE_NAME" $platform["ACS_RESOURCE_NAME"]
        if (-not $current["ACS_EVENTGRID_SECRET"]) {
            # Separate from TELEPHONY_WEBHOOK_SECRET: this one is embedded in the Event Grid endpoint URL.
            Set-AzdValue "ACS_EVENTGRID_SECRET" (New-UrlSafeSecret)
            Write-Host "Generated ACS_EVENTGRID_SECRET (stored only in the local azd env)."
        }
    }
    if ($Telephony -contains "twilio") {
        if (-not $TwilioAuthToken -and -not $current["TWILIO_AUTH_TOKEN"]) {
            throw "Pass -TwilioAuthToken (Twilio Console > Account > API keys & tokens > Auth token) to enable twilio."
        }
        if ($TwilioAuthToken) { Set-AzdValue "TWILIO_AUTH_TOKEN" $TwilioAuthToken }
    }
    Set-AzdValue "TELEPHONY_PROVIDERS" ($Telephony -join ",")
    if (-not $current["TELEPHONY_WEBHOOK_SECRET"]) {
        Set-AzdValue "TELEPHONY_WEBHOOK_SECRET" (New-UrlSafeSecret)
        Write-Host "Generated TELEPHONY_WEBHOOK_SECRET (call-token signing key; stored only in the local azd env)."
    }
    if ($OverflowNumber) { Set-AzdValue "TELEPHONY_OVERFLOW_NUMBER" $OverflowNumber }
}

Write-Host ""
Write-Host "examples\$Example now targets shared resource group $($platform['SHARED_RESOURCE_GROUP']) (Foundry $($platform['SHARED_FOUNDRY_NAME'])) in $($platform['AZURE_LOCATION'])."
Write-Host "Next:"
Write-Host "  az account show --query ""{tenant:tenantId, subscription:id}"" -o table   # must match $($platform['AZURE_TENANT_ID']) / $($platform['AZURE_SUBSCRIPTION_ID'])"
Write-Host "  cd examples\$Example; azd auth login --tenant-id $($platform['AZURE_TENANT_ID']); azd up"
if ($Telephony.Count -gt 0) {
    Write-Host "  ./scripts/configure-telephony.ps1 -Example $Example   # after azd up: Event Grid route and Twilio webhook URL"
}
