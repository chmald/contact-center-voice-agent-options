#Requires -Version 7.0
<#
.SYNOPSIS
  Create, configure phones for, or remove one shared-resource, three-app demo.
.DESCRIPTION
  Reuses the existing azd/Bicep projects and helpers. Up includes Azure AI Search;
  phone adapters are opt-in. WhatIf is entirely offline. Local ownership state is
  retained in .azure/demos/<name>.json; never adopts unrelated environments/groups.
  Down requires confirmation (or Force). Purge is a separate, irreversible opt-in.
  External phone purchases, Twilio Console routing, and PBX installation are manual.
.EXAMPLE
  ./scripts/demo.ps1 -Action Up -DemoName voice-demo -TenantId <guid> -SubscriptionId <guid> -Telephony asterisk
.EXAMPLE
  ./scripts/demo.ps1 -Action Down -DemoName voice-demo -TenantId <guid> -SubscriptionId <guid> -WhatIf
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][ValidateSet('Up', 'Phones', 'Down')][string]$Action,
    [Parameter(Mandatory)][ValidatePattern('^[a-z][a-z0-9-]{1,18}[a-z0-9]$')][string]$DemoName,
    [Parameter(Mandatory)][guid]$TenantId,
    [Parameter(Mandatory)][guid]$SubscriptionId,
    [ValidateSet('centralus', 'eastus2', 'swedencentral')][string]$Location = 'centralus',
    [ValidatePattern('^[a-z0-9]*$')][string]$AppLocation = '',
    [ValidateRange(1, 10000)][int]$RealtimeCapacity = 10,
    [ValidatePattern('^(acs|twilio|asterisk)(,(acs|twilio|asterisk))*$|^$')][string]$Telephony = '',
    [ValidateSet('voice-live-api', 'realtime-api', 'foundry-voice-agent')][string]$PhoneTarget = 'foundry-voice-agent',
    [ValidatePattern('^\+[1-9]\d{6,14}$|^$')][string]$AcsPhoneNumber = '',
    [ValidatePattern('^\+[1-9]\d{6,14}$|^$')][string]$OverflowNumber = '',
    [switch]$SkipLogin,
    [switch]$Force,
    [switch]$Purge
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$Root = Split-Path -Parent $PSScriptRoot
$StatePath = Join-Path $Root ".azure/demos/$DemoName.json"
$Projects = @(
    @{ Name = 'platform'; Env = "$DemoName-platform"; Dir = 'platform' },
    @{ Name = 'voice-live-api'; Env = "$DemoName-vl"; Dir = 'examples/voice-live-api'; Api = 'Voice Live API' },
    @{ Name = 'realtime-api'; Env = "$DemoName-rt"; Dir = 'examples/realtime-api'; Api = 'Realtime API' },
    @{ Name = 'foundry-voice-agent'; Env = "$DemoName-agent"; Dir = 'examples/foundry-voice-agent'; Api = 'Foundry voice agent' }
)
$Providers = @($Telephony.Split(',', [StringSplitOptions]::RemoveEmptyEntries) | Sort-Object -Unique)
if (-not $AppLocation) { $AppLocation = $Location }
if ($Purge -and $Action -ne 'Down') { throw '-Purge is valid only with -Action Down.' }
if ($Action -ne 'Up') {
    foreach ($option in @('Location', 'AppLocation', 'RealtimeCapacity', 'Telephony', 'OverflowNumber')) {
        if ($PSBoundParameters.ContainsKey($option)) { throw "-$option applies only to Up; $Action uses the saved demo configuration." }
    }
}

# This branch deliberately precedes CLI discovery, authentication, state writes and secrets.
Write-Host "$Action demo '$DemoName' in tenant $TenantId / subscription $SubscriptionId"
$Projects | ForEach-Object { Write-Host "  $($_.Dir): environment $($_.Env), resource group rg-$($_.Env)" }
if ($WhatIfPreference) {
    if ($Action -eq 'Up') {
        Write-Host "Offline plan: authenticate; validate ownership; platform preview + provision (Search + optional ACS); load knowledge; wire/preview/up each app; health/info; phone configuration; print URLs."
        Write-Host "AI region=$Location; app region=$AppLocation; capacity=$RealtimeCapacity; phones=$Telephony. Azure costs apply when executed."
    } elseif ($Action -eq 'Phones') {
        Write-Host "Offline plan: validate saved demo; regenerate Asterisk configs / print Twilio URLs; optionally route ACS to $PhoneTarget. No number purchases."
    } else {
        Write-Host "Offline plan: validate saved ownership; confirm; azd down agent -> rt -> vl -> platform. Purge=$Purge. Keep local state; external phone billing is not removed."
    }
    return
}

function Invoke-Tool([string]$File, [string[]]$Arguments, [switch]$Capture) {
    if ($Capture) { $result = & $File @Arguments } else { & $File @Arguments | Out-Host }
    if ($LASTEXITCODE -ne 0) { throw "$File failed (exit $LASTEXITCODE). Stop here; inspect the preceding error before retrying." }
    if ($Capture) { return $result }
}

function Invoke-Azd($Project, [string[]]$Arguments, [switch]$Capture) {
    Push-Location (Join-Path $Root $Project.Dir)
    try {
        Invoke-Tool 'azd' ($Arguments + @('--environment', $Project.Env)) -Capture:$Capture
    } finally { Pop-Location }
}

function Read-Values($Project) {
    $values = @{}
    $raw = Invoke-Azd $Project @('env', 'get-values') -Capture
    foreach ($line in $raw) {
        if ($line -match '^([A-Za-z0-9_]+)="?(.*?)"?$') { $values[$Matches[1]] = $Matches[2] }
    }
    return $values
}

function Set-Value($Project, [string]$Name, [string]$Value) {
    $null = Invoke-Azd $Project @('env', 'set', $Name, $Value) -Capture
}

function Save-State {
    $folder = Split-Path -Parent $StatePath
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$StatePath.tmp" -Encoding utf8NoBOM
    Move-Item -LiteralPath "$StatePath.tmp" -Destination $StatePath -Force
}

function Group-Exists($Project) {
    $value = Invoke-Tool 'az' @('group', 'exists', '--name', "rg-$($Project.Env)", '--subscription', "$SubscriptionId", '-o', 'tsv') -Capture
    if ("$value" -notin @('true', 'false')) { throw 'Could not determine resource-group existence safely.' }
    return "$value" -eq 'true'
}

function Assert-Environment($Project, $Values, [switch]$AllowMissingTenant) {
    foreach ($pair in @{
        AZURE_ENV_NAME = $Project.Env; AZURE_TENANT_ID = "$TenantId"; AZURE_SUBSCRIPTION_ID = "$SubscriptionId"
        AZURE_LOCATION = $State.Location
    }.GetEnumerator()) {
        if ($AllowMissingTenant -and $pair.Key -eq 'AZURE_TENANT_ID' -and -not $Values[$pair.Key]) { continue }
        if ($Values[$pair.Key] -ne $pair.Value) { throw "$($Project.Env): $($pair.Key) does not match this demo. Refusing to change or delete it." }
    }
    foreach ($key in @('AZURE_RESOURCE_GROUP', 'RESOURCE_GROUP')) {
        if ($Values[$key] -and $Values[$key] -ne "rg-$($Project.Env)") { throw "$($Project.Env): unexpected resource-group override $key." }
    }
    if ($Values['SHARED_RESOURCE_GROUP'] -and $Values['SHARED_RESOURCE_GROUP'] -ne "rg-$DemoName-platform") {
        throw "$($Project.Env): shared platform reference points outside this demo."
    }
    if ($Project.Name -ne 'platform' -and $Values['AZURE_APP_LOCATION'] -and $Values['AZURE_APP_LOCATION'] -ne $State.AppLocation) {
        throw "$($Project.Env): app region changed; use a new demo name to relocate resources."
    }
}

function Assert-TagScope($Project) {
    # azd can discover groups by environment tag; reject a wider scope than our manifest.
    $raw = Invoke-Tool 'az' @('group', 'list', '--tag', "azd-env-name=$($Project.Env)", '--subscription', "$SubscriptionId", '--query', '[].name', '-o', 'json') -Capture
    if (-not $raw) { throw 'Could not verify the azd environment resource-group scope.' }
    $tagged = @((($raw -join "`n") | ConvertFrom-Json))
    foreach ($name in $tagged) {
        if ($name -and $name -ne "rg-$($Project.Env)") { throw "$($Project.Env): another group carries this azd environment tag. Refusing a broader deployment/deletion scope." }
    }
}

function Show-Apps {
    foreach ($project in $Projects[1..3]) {
        if ($State.Projects[$project.Env].Url) { Write-Host "$($project.Name): $($State.Projects[$project.Env].Url)" }
    }
}

function Configure-Phones {
    if ($State.Providers.Count -eq 0) {
        if ($AcsPhoneNumber) { throw 'ACS is not enabled for this demo.' }
        Write-Host 'Browser-only demo. Use a new demo name to choose a different provider set.'
        return
    }
    $extension = 7001
    foreach ($project in $Projects[1..3]) {
        $values = Read-Values $project
        if (-not $values['SERVICE_WEB_URI']) { throw "$($project.Env) is not deployed; resume Up before configuring phones." }
        if ($State.Providers -contains 'asterisk') {
            & (Join-Path $PSScriptRoot 'enable-telephony.ps1') -Example $project.Name -ExampleEnv $project.Env -WriteAsteriskConfig -AsteriskExtension "$extension"
            if ($LASTEXITCODE -ne 0) { throw 'Asterisk configuration failed.' }
        }
        if ($State.Providers -contains 'twilio') {
            Write-Host "Twilio HTTP POST webhook ($($project.Name)): $($values['SERVICE_WEB_URI'].TrimEnd('/'))/telephony/twilio/voice"
        }
        $extension++
    }
    if ($State.Providers -contains 'acs') {
        if ($AcsPhoneNumber) {
            $target = $Projects | Where-Object Name -eq $PhoneTarget
            & (Join-Path $PSScriptRoot 'configure-telephony.ps1') -Example $PhoneTarget -ExampleEnv $target.Env -PhoneNumber $AcsPhoneNumber -EventSubscriptionName 'incoming-demo'
            if ($LASTEXITCODE -ne 0) { throw 'ACS routing failed.' }
        } else {
            Write-Host 'ACS is ready for a number or Direct Routing. Acquire/configure it separately, then run -Action Phones -AcsPhoneNumber <E.164> -PhoneTarget <example>.'
        }
    }
    Write-Host 'Copy Asterisk files to your PBX and select one Twilio webhook per number/SIP Domain. These external steps are not automated.'
}

# Load the ownership record before any login or change. It contains no secrets.
$State = $null
if (Test-Path -LiteralPath $StatePath) {
    $State = Get-Content -Raw -LiteralPath $StatePath | ConvertFrom-Json -AsHashtable
    if ($State.Schema -ne 1 -or $State.DemoName -ne $DemoName -or $State.TenantId -ne "$TenantId" -or $State.SubscriptionId -ne "$SubscriptionId") {
        throw 'Saved demo identity/context does not match. Refusing to proceed.'
    }
    if ($State.Status -eq 'Removed' -and $Action -ne 'Down') { throw 'This demo was removed. Use a new DemoName for a fresh deployment.' }
    foreach ($project in $Projects) {
        if (-not $State.Projects.Contains($project.Env)) { throw 'Incomplete ownership record; manual review required.' }
    }
    if ($Action -eq 'Up') {
        if ($State.Location -ne $Location -or $State.AppLocation -ne $AppLocation -or $State.Capacity -ne $RealtimeCapacity -or
            ($State.Providers -join ',') -ne ($Providers -join ',') -or $State.OverflowNumber -ne $OverflowNumber) {
            throw 'Resume with the original region/capacity/phone/overflow options, or use a new DemoName. Settings are not silently replaced.'
        }
    }
} elseif ($Action -ne 'Up') {
    throw 'No local ownership record for this demo. Refusing to configure or delete untracked resources.'
}
if ($AcsPhoneNumber -and (($Action -eq 'Up' -and $Providers -notcontains 'acs') -or ($Action -eq 'Phones' -and $State.Providers -notcontains 'acs'))) {
    throw '-AcsPhoneNumber requires the acs provider.'
}
foreach ($tool in @('az', 'azd')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is required on PATH. See docs/02-prerequisites.md." }
}

$Python = 'python'
if ($Action -eq 'Up') {
    foreach ($candidate in @('.venv/Scripts/python.exe', '.venv/bin/python')) {
        if (Test-Path (Join-Path $Root $candidate)) { $Python = Join-Path $Root $candidate; break }
    }
    # Validate dependencies before provisioning anything; never install packages silently.
    Invoke-Tool $Python @('-c', "import sys; assert sys.version_info >= (3,12), 'Python 3.12+ required'; import azure.identity, azure.ai.projects")
}
if (-not $SkipLogin) {
    Invoke-Tool 'az' @('login', '--tenant', "$TenantId", '--output', 'none')
    Invoke-Tool 'az' @('account', 'set', '--subscription', "$SubscriptionId")
    Invoke-Tool 'azd' @('auth', 'login', '--tenant-id', "$TenantId")
}
$account = (Invoke-Tool 'az' @('account', 'show', '--query', '{tenant:tenantId,subscription:id}', '-o', 'json') -Capture) -join "`n" | ConvertFrom-Json
if ($account.tenant -ne "$TenantId" -or $account.subscription -ne "$SubscriptionId") { throw 'Active Azure context does not match the requested tenant/subscription.' }

# Validate every target before changing even the first one.
foreach ($project in $Projects) {
    $local = Test-Path (Join-Path $Root "$($project.Dir)/.azure/$($project.Env)/.env")
    $exists = Group-Exists $project
    Assert-TagScope $project
    if (-not $State) {
        if ($local -or $exists) { throw "$($project.Env) already exists but is not owned by this wrapper. Choose a new DemoName." }
        continue
    }
    $phase = $State.Projects[$project.Env].Phase
    if ($phase -eq 'Planned' -and ($local -or $exists)) { throw "$($project.Env) appeared outside this workflow. Manual review required." }
    if ($exists -and $phase -notin @('Provisioning', 'Deployed', 'Removing', 'Removed')) { throw "$($project.Env): unexpected resource group before provisioning." }
    if ($local) { Assert-Environment $project (Read-Values $project) -AllowMissingTenant:($phase -eq 'Initializing' -and -not $exists) }
    elseif ($exists) { throw "$($project.Env): local azd environment missing. Recover it before operating on the resource group." }
    if ($exists) {
        $tag = Invoke-Tool 'az' @('group', 'show', '--name', "rg-$($project.Env)", '--subscription', "$SubscriptionId", '--query', 'tags."azd-env-name"', '-o', 'tsv') -Capture
        if ("$tag" -ne $project.Env) { throw "$($project.Env): resource-group ownership tag mismatch." }
    }
}

if (-not $PSCmdlet.ShouldProcess("demo $DemoName (four named environments)", $Action)) { return }
if ($Action -eq 'Down') {
    if (-not $Force -and -not $PSCmdlet.ShouldContinue("Delete the four groups listed above? Purge=$Purge. External numbers, Twilio billing and PBX configuration remain.", 'Remove shared voice demo')) { return }
    foreach ($project in @($Projects[3], $Projects[2], $Projects[1], $Projects[0])) {
        Assert-TagScope $project
        if (-not (Group-Exists $project)) {
            $State.Projects[$project.Env].Phase = 'Removed'; Save-State; continue
        }
        $State.Projects[$project.Env].Phase = 'Removing'; Save-State
        $down = @('down', '--force', '--no-prompt')
        if ($Purge) { $down += '--purge' }
        Invoke-Azd $project $down
        if (Group-Exists $project) { throw "$($project.Env): resource group still exists; platform deletion will not continue." }
        $State.Projects[$project.Env].Phase = 'Removed'; Save-State
    }
    $State.Status = 'Removed'; Save-State
    Write-Host 'Demo groups removed. Local ownership/env files retained. Check soft-deleted Foundry resources before reusing names; azd purge support varies by resource.'
    Write-Host 'Remove external Twilio webhooks/PBX entries and review phone-number billing separately.'
    return
}
if ($Action -eq 'Phones') { Configure-Phones; Show-Apps; return }

if (-not $State) {
    $State = @{
        Schema = 1; DemoName = $DemoName; TenantId = "$TenantId"; SubscriptionId = "$SubscriptionId"
        Location = $Location; AppLocation = $AppLocation; Capacity = $RealtimeCapacity
        Providers = @($Providers); OverflowNumber = $OverflowNumber; Status = 'InProgress'; Projects = @{}
    }
    foreach ($project in $Projects) { $State.Projects[$project.Env] = @{ Phase = 'Planned'; Url = '' } }
    Save-State
}
try {
    foreach ($project in $Projects) {
        if (-not (Test-Path (Join-Path $Root "$($project.Dir)/.azure/$($project.Env)/.env"))) {
            $State.Projects[$project.Env].Phase = 'Initializing'; Save-State
            Push-Location (Join-Path $Root $project.Dir)
            try {
                Invoke-Tool 'azd' @('env', 'new', $project.Env, '--subscription', "$SubscriptionId", '--location', $Location, '--no-prompt')
            } finally { Pop-Location }
        }
        if ($State.Projects[$project.Env].Phase -eq 'Initializing') {
            # Retry a failed tenant write without recreating/adopting an environment.
            Set-Value $project 'AZURE_TENANT_ID' "$TenantId"
            $State.Projects[$project.Env].Phase = 'Initialized'; Save-State
        }
    }
    $platform = $Projects[0]
    Set-Value $platform 'DEPLOY_SEARCH' 'true'
    Set-Value $platform 'DEPLOY_COMMUNICATION_SERVICES' "$($Providers -contains 'acs')".ToLowerInvariant()
    Set-Value $platform 'REALTIME_DEPLOYMENT_CAPACITY' "$RealtimeCapacity"
    Write-Host 'Platform: preview, then provision (existing hook checks realtime quota).'
    Invoke-Azd $platform @('provision', '--preview', '--no-prompt')
    $State.Projects[$platform.Env].Phase = 'Provisioning'; Save-State
    Invoke-Azd $platform @('provision', '--no-prompt')
    $State.Projects[$platform.Env].Phase = 'Deployed'; Save-State
    $platformValues = Read-Values $platform
    foreach ($required in @('SHARED_FOUNDRY_NAME', 'SHARED_FOUNDRY_PROJECT', 'AZURE_SEARCH_ENDPOINT', 'AZURE_SEARCH_SERVICE_NAME')) {
        if (-not $platformValues[$required]) { throw "Platform output $required is missing." }
    }
    Assert-Environment $platform $platformValues
    Invoke-Tool $Python @((Join-Path $PSScriptRoot 'load-knowledge-index.py'), '--endpoint', $platformValues['AZURE_SEARCH_ENDPOINT'], '--index', 'knowledge')

    foreach ($project in $Projects[1..3]) {
        $current = Read-Values $project
        $token = ''
        if ($Providers -contains 'twilio' -and -not $current['TWILIO_AUTH_TOKEN']) {
            $secureToken = Read-Host "Twilio Auth Token for $($project.Name) (not logged; stored in its ignored azd env)" -AsSecureString
            $token = [System.Net.NetworkCredential]::new('', $secureToken).Password
            if (-not $token) { throw 'A Twilio token is required when enabling twilio.' }
        }
        try {
            & (Join-Path $PSScriptRoot 'use-shared-platform.ps1') -Example $project.Name -ExampleEnv $project.Env -PlatformEnv $platform.Env -AppLocation $AppLocation -Telephony $Providers -TwilioAuthToken $token -OverflowNumber $OverflowNumber
            if ($LASTEXITCODE -ne 0) { throw 'Shared-platform wiring failed.' }
        } finally { $token = ''; if ($secureToken) { $secureToken.Dispose(); $secureToken = $null } }
        Set-Value $project 'AZURE_SEARCH_INDEX' 'knowledge'
        Set-Value $project 'AZURE_SEARCH_SEMANTIC_CONFIG' 'default'
        $wired = Read-Values $project
        Assert-Environment $project $wired
        if ($wired['SHARED_FOUNDRY_NAME'] -ne $platformValues['SHARED_FOUNDRY_NAME'] -or $wired['AZURE_SEARCH_SERVICE_NAME'] -ne $platformValues['AZURE_SEARCH_SERVICE_NAME']) {
            throw "$($project.Env) was not wired to this platform."
        }
        Write-Host "$($project.Name): preview, then build/provision/deploy."
        Invoke-Azd $project @('provision', '--preview', '--no-prompt')
        $State.Projects[$project.Env].Phase = 'Provisioning'; Save-State
        Invoke-Azd $project @('up', '--no-prompt')
        $values = Read-Values $project
        $url = $values['SERVICE_WEB_URI']
        if (-not $url -or $url -notmatch '^https://') { throw "$($project.Env): no HTTPS app URL was returned." }
        $State.Projects[$project.Env].Url = $url
        $State.Projects[$project.Env].Phase = 'Deployed'; Save-State
        $health = Invoke-RestMethod -Uri "$($url.TrimEnd('/'))/healthz" -TimeoutSec 60
        $info = Invoke-RestMethod -Uri "$($url.TrimEnd('/'))/api/info" -TimeoutSec 60
        if ($health.status -ne 'ok' -or $info.api -notlike "$($project.Api)*" -or $info.knowledge -ne 'azure-ai-search:knowledge' -or
            (@($info.telephony | Sort-Object) -join ',') -ne ($Providers -join ',')) {
            throw "$($project.Env): health/info configuration check failed. Inspect the app before resuming."
        }
        Write-Host "Healthy: $($project.Name) - $url"
    }
    Configure-Phones
    $State.Status = 'Ready'; Save-State
    Show-Apps
    Write-Host 'HTTP checks do not open an upstream voice session. Complete browser mic/tool and real-phone smoke tests in docs/00-reproduce-this-demo.md.'
} catch {
    Write-Warning 'Stopped without automatic rollback. Successful resources still incur costs. Fix the error and rerun Up with the same options, or run Down for this demo.'
    Show-Apps
    throw
}