<#
.SYNOPSIS
  Route phone calls to a deployed example: ACS number -> Event Grid, and print the Twilio webhook URL.

.DESCRIPTION
  Run after `azd up` in the example folder (the app must be live so Event Grid's webhook
  validation handshake succeeds).
  - ACS: creates/updates an Event Grid subscription on the shared ACS resource that sends
    Microsoft.Communication.IncomingCall for -PhoneNumber to this app only. Give each app its
    own ACS number (or re-run with another -Example to move one number between apps).
  - Twilio: prints the Voice webhook URL to paste on a Twilio number or on a Twilio SIP Domain
    (the route a PBX such as FreePBX uses to reach the agent over a SIP trunk).

  Verifies the active az account matches the example's azd tenant/subscription first and
  never proceeds on a mismatch.

.EXAMPLE
  ./scripts/configure-telephony.ps1 -Example realtime-api -PhoneNumber +15555550100
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("voice-live-api", "realtime-api", "foundry-voice-agent")]
    [string]$Example,

    [string]$ExampleEnv = "",

    [ValidatePattern('^\+[1-9]\d{6,14}$')]
    [string]$PhoneNumber = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ExampleDir = Join-Path $Root "examples\$Example"

Push-Location $ExampleDir
try {
    $azdArgs = @("env", "get-values")
    if ($ExampleEnv) { $azdArgs += @("--environment", $ExampleEnv) }
    $raw = & azd @azdArgs
    if ($LASTEXITCODE -ne 0) { throw "azd env get-values failed in $ExampleDir" }
} finally { Pop-Location }

$envValues = @{}
foreach ($line in $raw) {
    if ($line -match '^([A-Za-z0-9_]+)="?(.*?)"?$') { $envValues[$Matches[1]] = $Matches[2] }
}
foreach ($required in "AZURE_TENANT_ID", "AZURE_SUBSCRIPTION_ID", "SERVICE_WEB_URI", "TELEPHONY_PROVIDERS", "TELEPHONY_WEBHOOK_SECRET") {
    if (-not $envValues[$required]) { throw "$required is not set for examples\$Example - run use-shared-platform.ps1 with -Telephony and azd up first." }
}
$providers = $envValues["TELEPHONY_PROVIDERS"].Split(",") | ForEach-Object { $_.Trim().ToLowerInvariant() }
$baseUrl = $envValues["SERVICE_WEB_URI"].TrimEnd("/")

# Multi-tenant auth gate: never act on the ambient az account without checking it.
$active = az account show --query "{tenant:tenantId, subscription:id}" -o json | ConvertFrom-Json
if ($active.tenant -ne $envValues["AZURE_TENANT_ID"] -or $active.subscription -ne $envValues["AZURE_SUBSCRIPTION_ID"]) {
    Write-Host "Active az account is tenant $($active.tenant) / subscription $($active.subscription)."
    Write-Host "Expected tenant $($envValues['AZURE_TENANT_ID']) / subscription $($envValues['AZURE_SUBSCRIPTION_ID']). Fix with:"
    Write-Host "  az login --tenant $($envValues['AZURE_TENANT_ID'])"
    Write-Host "  az account set --subscription $($envValues['AZURE_SUBSCRIPTION_ID'])"
    exit 1
}

$health = Invoke-WebRequest -Uri "$baseUrl/api/info" -UseBasicParsing
$info = $health.Content | ConvertFrom-Json
Write-Host "App is live: $($info.api) / $($info.model); telephony=$($info.telephony -join ','); knowledge=$($info.knowledge)"

if ($providers -contains "acs") {
    if (-not $PhoneNumber) { throw "Pass -PhoneNumber (the ACS number, E.164) to route ACS calls to this app." }
    if (-not $envValues["ACS_RESOURCE_NAME"] -or -not $envValues["SHARED_RESOURCE_GROUP"]) { throw "ACS_RESOURCE_NAME / SHARED_RESOURCE_GROUP missing." }
    if (-not $envValues["ACS_EVENTGRID_SECRET"]) { throw "ACS_EVENTGRID_SECRET missing - re-run use-shared-platform.ps1 -Telephony acs and azd up." }
    $acsId = az resource show --name $envValues["ACS_RESOURCE_NAME"] --resource-group $envValues["SHARED_RESOURCE_GROUP"] --resource-type "Microsoft.Communication/communicationServices" --subscription $envValues["AZURE_SUBSCRIPTION_ID"] --query id -o tsv
    if (-not $acsId) { throw "ACS resource not found." }
    $subscriptionName = ("incoming-" + $Example).ToLowerInvariant()
    $endpoint = "$baseUrl/telephony/acs/events?secret=$($envValues['ACS_EVENTGRID_SECRET'])"
    az eventgrid event-subscription create `
        --name $subscriptionName `
        --source-resource-id $acsId `
        --endpoint-type webhook `
        --endpoint $endpoint `
        --included-event-types Microsoft.Communication.IncomingCall `
        --advanced-filter data.to.PhoneNumber.Value StringIn $PhoneNumber `
        --event-delivery-schema eventgridschema `
        --max-delivery-attempts 2 `
        --event-ttl 1 `
        --output none
    if ($LASTEXITCODE -ne 0) { throw "Event Grid subscription failed (is the app deployed with TELEPHONY_PROVIDERS including acs?)." }
    Write-Host "ACS: calls to $PhoneNumber now ring examples\$Example (Event Grid subscription '$subscriptionName')."
    Write-Host "     If another app's subscription also matches $PhoneNumber, delete it: az eventgrid event-subscription delete --name incoming-<other-example> --source-resource-id <acs-id>"
}

if ($providers -contains "twilio") {
    Write-Host ""
    Write-Host "Twilio: set this as the Voice webhook (HTTP POST) on a Twilio number or Twilio SIP Domain:"
    Write-Host "  $baseUrl/telephony/twilio/voice"
    Write-Host "FreePBX/Asterisk: add an outbound route (or custom destination) that sends the chosen"
    Write-Host "extension/IVR option over the Twilio trunk to sip:<agent>@<your-domain>.sip.twilio.com;"
    Write-Host "the SIP Domain above then hands the call to the agent. See docs/07-telephony-and-shared-endpoint.md."
}
