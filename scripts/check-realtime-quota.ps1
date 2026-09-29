<#
.SYNOPSIS
  Pre-provision check: will the realtime Global Standard deployment fit the subscription's quota?

.DESCRIPTION
  Runs as the azd `preprovision` hook for examples/realtime-api (standalone mode) and platform/.
  Realtime quota is counted in capacity units. The `az cognitiveservices usage list` row is labelled
  "Requests Per Minute - <model> - GlobalStandard" but its limit/usage are units; the deployment's sku.capacity
  consumes them. Each unit maps to TPM + RPM per the model's SKU (gpt-realtime-2.1-mini: 10,000 TPM + 20 RPM).
  Fails before ARM preflight with the exact value to set, instead of an InsufficientQuota error.

  Reads the azd environment variables azd exports to hooks. Can also be run by hand:
    ./scripts/check-realtime-quota.ps1 -Location centralus -SubscriptionId <id> -Model gpt-realtime-2.1-mini -Capacity 10 [-ResourceGroup <rg> -FoundryName <ais-...>]
#>
param(
    [string]$Location = $env:AZURE_LOCATION,
    [string]$SubscriptionId = $env:AZURE_SUBSCRIPTION_ID,
    [string]$Model = $(if ($env:AZURE_OPENAI_REALTIME_MODEL) { $env:AZURE_OPENAI_REALTIME_MODEL } else { "gpt-realtime-2.1-mini" }),
    [int]$Capacity = $(if ($env:REALTIME_DEPLOYMENT_CAPACITY) { [int]$env:REALTIME_DEPLOYMENT_CAPACITY } else { 10 }),
    # Set when run from platform/, which owns the shared deployment (its env also has SHARED_FOUNDRY_NAME).
    [switch]$Platform,
    # Existing deployment to add back on re-provision (azd sets these from the environment).
    [string]$ResourceGroup = "",
    [string]$FoundryName = ""
)

$ErrorActionPreference = "Stop"

if ($env:SHARED_FOUNDRY_NAME -and -not $Platform) {
    Write-Host "Shared mode: the platform/ project owns the realtime deployment; skipping quota check."
    exit 0
}
if (-not $Location -or -not $SubscriptionId) {
    Write-Host "AZURE_LOCATION / AZURE_SUBSCRIPTION_ID not set yet; skipping realtime quota check."
    exit 0
}

$quotaName = "OpenAI.GlobalStandard.$Model"
$usage = az cognitiveservices usage list -l $Location --subscription $SubscriptionId -o json 2>$null | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $usage) {
    Write-Warning "Could not read Cognitive Services usage for $Location; skipping realtime quota check."
    exit 0
}
$row = $usage | Where-Object { $_.name.value -eq $quotaName } | Select-Object -First 1
if (-not $row) {
    Write-Error "No '$quotaName' quota row in $Location for subscription $SubscriptionId. The model may not be offered there; pick another region or model."
    exit 1
}

# Re-provisioning an existing deployment: its current capacity is already counted as used.
$existing = 0
$deploymentName = if ($env:AZURE_OPENAI_REALTIME_DEPLOYMENT) { $env:AZURE_OPENAI_REALTIME_DEPLOYMENT } else { $Model }
$account = if ($FoundryName) { $FoundryName } elseif ($Platform) { $env:SHARED_FOUNDRY_NAME } else { $env:FOUNDRY_RESOURCE_NAME }
$resourceGroup = if ($ResourceGroup) { $ResourceGroup } elseif ($Platform) { $env:SHARED_RESOURCE_GROUP } else { $env:AZURE_RESOURCE_GROUP }
if ($account -and $resourceGroup) {
    $current = az cognitiveservices account deployment show --name $account --resource-group $resourceGroup `
        --deployment-name $deploymentName --subscription $SubscriptionId --query "sku.capacity" -o tsv 2>$null
    if ($LASTEXITCODE -eq 0 -and $current) { $existing = [int]$current }
}

$available = [int]$row.limit - [int]$row.currentValue + $existing

# Translate capacity units into the TPM/RPM the portal shows (per-unit rates vary by model version).
$perUnitTokens = $null; $perUnitRequests = $null
$version = $env:AZURE_OPENAI_REALTIME_MODEL_VERSION
$catalog = az cognitiveservices model list -l $Location --subscription $SubscriptionId -o json 2>$null | ConvertFrom-Json
if ($LASTEXITCODE -eq 0 -and $catalog) {
    $entry = $catalog | Where-Object { $_.model.name -eq $Model -and (-not $version -or $_.model.version -eq $version) } | Select-Object -Last 1
    $sku = $entry.model.skus | Where-Object { $_.name -eq "GlobalStandard" } | Select-Object -First 1
    $counts = @($sku.rateLimits | ForEach-Object { [double]$_.count })
    if ($counts.Count -ge 2) {
        # The catalog omits the limit keys; tokens are always the larger per-unit value.
        $perUnitTokens = ($counts | Measure-Object -Maximum).Maximum
        $perUnitRequests = ($counts | Measure-Object -Minimum).Minimum
    }
}
function Format-Units([int]$units) {
    if ($script:perUnitTokens) { return "{0} units (~{1:N0} TPM / {2:N0} RPM)" -f $units, ($units * $script:perUnitTokens), ($units * $script:perUnitRequests) }
    return "$units units"
}

Write-Host ("Realtime quota for {0} (GlobalStandard) in {1}: limit {2}, used {3}, available {4}; requested {5}." -f `
    $Model, $Location, (Format-Units ([int]$row.limit)), $row.currentValue, (Format-Units $available), (Format-Units $Capacity))
Write-Host "  (The usage row is labelled '$($row.name.localizedValue)' but counts capacity units; the portal shows the same deployment as TPM.)"

if ($Capacity -gt $available) {
    Write-Host ""
    Write-Host "REALTIME_DEPLOYMENT_CAPACITY=$Capacity exceeds the available $available units." -ForegroundColor Red
    if ($available -gt 0) {
        Write-Host "  Fix now:   azd env set REALTIME_DEPLOYMENT_CAPACITY $available"
    }
    Write-Host "  Or raise:  https://aka.ms/oai/stuquotarequest  (quota: $($row.name.localizedValue))"
    Write-Host "  Note: realtime Global Standard quota is pooled per subscription + model version; other deployments of $Model in this subscription count against it."
    exit 1
}
exit 0
