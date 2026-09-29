<#
.SYNOPSIS
  Turn on phone channels (acs, twilio, asterisk) for one example and generate the secrets they need.

.DESCRIPTION
  Works in standalone and shared-platform mode. Secrets are generated locally with a
  cryptographic RNG, stored only in the example's azd environment (.azure/<env>/.env,
  gitignored) and delivered to the Container App as Container Apps secrets on the next
  `azd up` / `azd provision`. They are never printed unless you ask for them.

  Per channel:
    any channel -> TELEPHONY_PROVIDERS, TELEPHONY_WEBHOOK_SECRET (signs per-call tokens)
    asterisk    -> ASTERISK_WEBSOCKET_SECRET (password in Asterisk websocket_client.conf)
    acs         -> ACS_EVENTGRID_SECRET (Event Grid URL secret); needs SHARED_RESOURCE_GROUP + ACS_RESOURCE_NAME
    twilio      -> TWILIO_AUTH_TOKEN (from the Twilio Console; pass -TwilioAuthToken)

  After `azd up`, run again with -WriteAsteriskConfig to write ready-to-copy Asterisk files
  (websocket_client.conf + extensions.conf snippet with the real app URL and password) under
  .azure/<env>/asterisk/.

.EXAMPLE
  ./scripts/enable-telephony.ps1 -Example foundry-voice-agent -Providers asterisk
  cd examples\foundry-voice-agent; azd up
  ./scripts/enable-telephony.ps1 -Example foundry-voice-agent -WriteAsteriskConfig

.EXAMPLE
  ./scripts/enable-telephony.ps1 -Example voice-live-api -Providers asterisk -RotateSecrets
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("voice-live-api", "realtime-api", "foundry-voice-agent")]
    [string]$Example,

    [ValidateSet("acs", "twilio", "asterisk")]
    [string[]]$Providers = @(),

    [string]$ExampleEnv = "",

    [string]$TwilioAuthToken = "",

    [ValidatePattern('^(\+[1-9]\d{6,14})?$')]
    [string]$OverflowNumber = "",

    # Replace existing secrets (also update Asterisk's websocket_client.conf / the Event Grid subscription afterwards).
    [switch]$RotateSecrets,

    # Remove all phone channels (browser only).
    [switch]$Disable,

    # After azd up: write Asterisk config files for this app under .azure/<env>/asterisk/.
    [switch]$WriteAsteriskConfig,

    # Asterisk dialplan extension that reaches this agent in the generated snippet.
    [string]$AsteriskExtension = "7001"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ExampleDir = Join-Path $Root "examples\$Example"

function Invoke-Azd([string[]]$AzdArgs) {
    Push-Location $ExampleDir
    try {
        if ($ExampleEnv) { $AzdArgs += @("--environment", $ExampleEnv) }
        $output = & azd @AzdArgs 2>$null
        return @{ Ok = ($LASTEXITCODE -eq 0); Output = $output }
    } finally { Pop-Location }
}
function Get-Value([string]$Name) {
    $result = Invoke-Azd @("env", "get-value", $Name)
    if ($result.Ok) { return ($result.Output | Select-Object -First 1) }
    return ""
}
function Set-Value([string]$Name, [string]$Value) {
    $result = Invoke-Azd @("env", "set", $Name, $Value)
    if (-not $result.Ok) { throw "azd env set $Name failed in examples\$Example" }
}
function New-UrlSafeSecret {
    # 32 random bytes -> 43 URL-safe characters (no ';' or quotes, safe in Asterisk .conf files and URLs).
    $bytes = [System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
    return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}
function Ensure-Secret([string]$Name) {
    if ($RotateSecrets -or -not (Get-Value $Name)) {
        Set-Value $Name (New-UrlSafeSecret)
        Write-Host "  $Name generated$(if ($RotateSecrets) { ' (rotated)' })."
    } else {
        Write-Host "  $Name already set (kept; use -RotateSecrets to replace)."
    }
}

if ($Disable) {
    Set-Value "TELEPHONY_PROVIDERS" ""
    Write-Host "Phone channels disabled for examples\$Example. Run 'azd provision' to apply. Secrets are left in the azd env."
    exit 0
}

if ($Providers.Count -gt 0) {
    $list = @($Providers | ForEach-Object { $_.ToLowerInvariant() } | Select-Object -Unique)
    Write-Host "Configuring examples\$Example for: $($list -join ', ')"
    Ensure-Secret "TELEPHONY_WEBHOOK_SECRET"
    if ($list -contains "asterisk") { Ensure-Secret "ASTERISK_WEBSOCKET_SECRET" }
    if ($list -contains "acs") {
        if (-not (Get-Value "SHARED_RESOURCE_GROUP") -or -not (Get-Value "ACS_RESOURCE_NAME")) {
            throw "ACS needs an Azure Communication Services resource: run scripts/use-shared-platform.ps1 -Telephony acs (platform/ provides ACS), or set SHARED_RESOURCE_GROUP and ACS_RESOURCE_NAME."
        }
        Ensure-Secret "ACS_EVENTGRID_SECRET"
    }
    if ($list -contains "twilio") {
        if ($TwilioAuthToken) { Set-Value "TWILIO_AUTH_TOKEN" $TwilioAuthToken; Write-Host "  TWILIO_AUTH_TOKEN set." }
        elseif (-not (Get-Value "TWILIO_AUTH_TOKEN")) { throw "Pass -TwilioAuthToken (Twilio Console > Account > API keys & tokens > Auth token)." }
    }
    if ($OverflowNumber) { Set-Value "TELEPHONY_OVERFLOW_NUMBER" $OverflowNumber }
    Set-Value "TELEPHONY_PROVIDERS" ($list -join ",")
    Write-Host ""
    Write-Host "Next: cd examples\$Example; azd up   (use 'azd provision' if the code image is already current)"
    if ($list -contains "asterisk") { Write-Host "Then: ./scripts/enable-telephony.ps1 -Example $Example -WriteAsteriskConfig" }
    if ($list -contains "acs") { Write-Host "Then: ./scripts/configure-telephony.ps1 -Example $Example -PhoneNumber +1..." }
}

if ($WriteAsteriskConfig) {
    $uri = Get-Value "SERVICE_WEB_URI"
    $secret = Get-Value "ASTERISK_WEBSOCKET_SECRET"
    $envName = if ($ExampleEnv) { $ExampleEnv } else { Get-Value "AZURE_ENV_NAME" }
    if (-not $uri) { throw "SERVICE_WEB_URI is not set - run 'azd up' in examples\$Example first." }
    if (-not $secret) { throw "ASTERISK_WEBSOCKET_SECRET is not set - run with -Providers asterisk first." }
    if ((Get-Value "TELEPHONY_PROVIDERS") -notmatch "asterisk") { Write-Warning "TELEPHONY_PROVIDERS does not include asterisk; the app will not accept Asterisk connections until you enable it and re-provision." }

    $wss = $uri -replace '^https://', 'wss://'
    $client = ($Example -replace '[^a-z0-9]', '_')
    $outDir = Join-Path $ExampleDir ".azure\$envName\asterisk"
    New-Item -ItemType Directory -Force $outDir | Out-Null
    @"
; Generated by scripts/enable-telephony.ps1 for examples\$Example ($envName). Contains a secret - do not commit.
; Append to /etc/asterisk/websocket_client.conf, then: asterisk -rx "module reload res_websocket_client.so"
[$client]
type = websocket_client
connection_type = per_call_config
uri = $wss/telephony/asterisk/media
protocols = media
username = asterisk
password = $secret
tls_enabled = yes
connection_timeout = 3000
"@ | Set-Content (Join-Path $outDir "websocket_client.conf") -Encoding ascii
    @"
; Generated by scripts/enable-telephony.ps1 for examples\$Example ($envName).
; Add to the context your phones dial from in /etc/asterisk/extensions.conf, then: asterisk -rx "dialplan reload"
exten => $AsteriskExtension,1,Dial(WebSocket/$client/c(slin24)f(json))
 same => n,Hangup()
"@ | Set-Content (Join-Path $outDir "extensions.conf") -Encoding ascii
    Write-Host "Wrote Asterisk config for $wss/telephony/asterisk/media to:"
    Write-Host "  $outDir\websocket_client.conf   (contains the password)"
    Write-Host "  $outDir\extensions.conf         (extension $AsteriskExtension)"
    Write-Host "Verify first: `$env:ASTERISK_WEBSOCKET_SECRET = azd env get-value ASTERISK_WEBSOCKET_SECRET; python scripts\probe-asterisk.py --url $wss/telephony/asterisk/media"
}

if ($Providers.Count -eq 0 -and -not $WriteAsteriskConfig) {
    Write-Host "Nothing to do. Pass -Providers acs,twilio,asterisk, -WriteAsteriskConfig, or -Disable."
}
