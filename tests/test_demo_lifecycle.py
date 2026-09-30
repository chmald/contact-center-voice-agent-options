"""Execute lifecycle orchestration against fake CLIs, never an Azure account."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


PWSH = shutil.which("pwsh")
pytestmark = pytest.mark.skipif(not PWSH, reason="PowerShell 7 is required for lifecycle simulation")

HARNESS = r'''
param([string]$Root, [string]$Case)
$ErrorActionPreference = 'Stop'
$global:Calls = [System.Collections.Generic.List[object]]::new()
$global:Values = @{}
$global:Groups = @{}
$global:Failure = ''
$global:BadContext = $false
$global:BadTag = $false
$global:BadHealth = $false
$global:FailTenantWrite = $false
$global:LASTEXITCODE = 0
$Tenant = '00000000-0000-0000-0000-000000000001'
$Subscription = '00000000-0000-0000-0000-000000000002'
function Flag($Items, $Name) {
    $i = [array]::IndexOf($Items, $Name)
    if ($i -ge 0) { return $Items[$i + 1] }
    return ''
}
function global:az {
    $a = @($args)
    $global:Calls.Add(@{ Tool='az'; Args=$a })
    $global:LASTEXITCODE = 0
    if ($a[0] -eq 'account' -and $a[1] -eq 'show') {
        return @{ tenant=$(if ($global:BadContext) {'wrong'} else {$Tenant}); subscription=$Subscription } | ConvertTo-Json
    }
    if ($a[0] -eq 'group') {
        if ($a[1] -eq 'list') {
            $envName = (Flag $a '--tag').Split('=', 2)[1]
            $names = @($global:Groups.Keys | Where-Object { $global:Groups[$_] -eq $envName })
            return ConvertTo-Json -InputObject $names -Compress
        }
        $name = Flag $a '--name'
        if ($a[1] -eq 'exists') { return "$($global:Groups.ContainsKey($name))".ToLowerInvariant() }
        if ($a[1] -eq 'show') { return $(if ($global:BadTag) {'unrelated'} else {$global:Groups[$name]}) }
    }
    if ($a[0] -eq 'provider') { return 'Central US' }
    if ($a[0] -eq 'login' -or ($a[0] -eq 'account' -and $a[1] -eq 'set')) { return }
    throw "Unexpected az call: $a"
}
function global:azd {
    $a = @($args)
    $global:Calls.Add(@{ Tool='azd'; Args=$a; Dir=(Get-Location).Path })
    $global:LASTEXITCODE = 0
    if ($a[0] -eq 'auth') { return }
    $name = Flag $a '--environment'
    if ($a[0] -eq 'env') {
        if ($a[1] -eq 'new') {
            $name = $a[2]
            $global:Values[$name] = @{
                AZURE_ENV_NAME=$name; AZURE_SUBSCRIPTION_ID=(Flag $a '--subscription'); AZURE_LOCATION=(Flag $a '--location')
            }
            $dir = Join-Path $PWD ".azure/$name"
            New-Item -ItemType Directory -Force $dir | Out-Null
            Set-Content (Join-Path $dir '.env') '# simulated environment; no credentials'
            return
        }
        if (-not $global:Values.ContainsKey($name)) { throw "Missing environment: $name" }
        if ($a[1] -eq 'set') {
            if ($global:FailTenantWrite -and $a[2] -eq 'AZURE_TENANT_ID') { $global:FailTenantWrite=$false; $global:LASTEXITCODE=9; return }
            $global:Values[$name][$a[2]] = $a[3]; return
        }
        if ($a[1] -eq 'get-value') { return $global:Values[$name][$a[2]] }
        if ($a[1] -eq 'get-values') {
            foreach ($entry in $global:Values[$name].GetEnumerator()) { '{0}="{1}"' -f $entry.Key, $entry.Value }
            return
        }
    }
    if ($a[0] -eq 'provision' -or $a[0] -eq 'up') {
        if ($a -contains '--preview') { return }
        if ($global:Failure -eq $name) { $global:LASTEXITCODE = 7; return }
        $v = $global:Values[$name]
        $global:Groups["rg-$name"] = $name
        if ($name -like '*-platform') {
            $v.SHARED_RESOURCE_GROUP = "rg-$name"
            $v.SHARED_FOUNDRY_NAME = 'ais-mock'
            $v.SHARED_FOUNDRY_PROJECT = 'voice-agents'
            $v.AZURE_SEARCH_ENDPOINT = 'https://search.example.test'
            $v.AZURE_SEARCH_SERVICE_NAME = 'search-mock'
            $v.AZURE_OPENAI_REALTIME_MODEL = 'gpt-realtime-2.1-mini'
            $v.AZURE_OPENAI_REALTIME_DEPLOYMENT = 'gpt-realtime-2.1-mini'
        } else {
            $v.AZURE_RESOURCE_GROUP = "rg-$name"
            $v.SERVICE_WEB_URI = "https://$name.example.test"
        }
        return
    }
    if ($a[0] -eq 'down') {
        if ($global:Failure -eq $name) { $global:LASTEXITCODE = 8; return }
        $global:Groups.Remove("rg-$name")
        return
    }
    throw "Unexpected azd call: $a"
}
function global:python {
    $global:Calls.Add(@{ Tool='python'; Args=@($args) })
    $global:LASTEXITCODE = 0
}
function global:Read-Host {
    param([string]$Prompt, [switch]$AsSecureString)
    $global:Calls.Add(@{ Tool='secure-prompt'; Secure=[bool]$AsSecureString })
    return ConvertTo-SecureString 'synthetic-test-only-token' -AsPlainText -Force
}
function global:Invoke-RestMethod {
    param([string]$Uri, [int]$TimeoutSec)
    $global:Calls.Add(@{ Tool='http'; Uri=$Uri })
    if ($Uri.EndsWith('/healthz')) { return @{status='ok'} }
    $name = ([uri]$Uri).Host.Split('.')[0]
    $api = if ($name.EndsWith('-vl')) {'Voice Live API'} elseif ($name.EndsWith('-rt')) {'Realtime API'} else {'Foundry Voice Agent (preview)'}
    return @{api=$api; knowledge=$(if($global:BadHealth){'local'}else{'azure-ai-search:knowledge'}); telephony=@($global:Values[$name].TELEPHONY_PROVIDERS.Split(',', [StringSplitOptions]::RemoveEmptyEntries))}
}

Set-Location $Root
$script = Join-Path $Root 'scripts/demo.ps1'
$common = @{ DemoName='test-demo'; TenantId=$Tenant; SubscriptionId=$Subscription; SkipLogin=($Case -ne 'auth') }
$phone = if ($Case -in @('phones','twilio','real-helpers')) { @{Telephony=$(if($Case -eq 'twilio'){'twilio'}elseif($Case -eq 'real-helpers'){'asterisk'}else{'acs,asterisk'}); AcsPhoneNumber=$(if($Case -eq 'phones'){'+15555550100'}else{''})} } else { @{} }
$caught = ''
try {
    if ($Case -eq 'whatif') { & $script -Action Up @common -WhatIf; & $script -Action Down @common -WhatIf }
    elseif ($Case -eq 'untracked-down') { & $script -Action Down @common -Force }
    else {
        if ($Case -eq 'collision') { $global:Groups['rg-test-demo-rt']='unrelated' }
        if ($Case -eq 'context') { $global:BadContext=$true }
        if ($Case -in @('partial','resume')) { $global:Failure='test-demo-rt' }
        if ($Case -eq 'init-resume') { $global:FailTenantWrite=$true }
        if ($Case -eq 'health') { $global:BadHealth=$true }
        try { & $script -Action Up @common @phone } catch {
            if ($Case -notin @('resume','init-resume')) { throw }
            $global:Failure=''
            & $script -Action Up @common @phone
        }
        if ($Case -eq 'drift') { & $script -Action Up @common -Location eastus2 }
        if ($Case -eq 'environment-drift') { $global:Values['test-demo-vl'].AZURE_SUBSCRIPTION_ID='unrelated'; & $script -Action Down @common -Force }
        if ($Case -eq 'tag') { $global:BadTag=$true; & $script -Action Down @common -Force }
        if ($Case -eq 'tag-collision') { $global:Groups['rg-unrelated']='test-demo-rt'; & $script -Action Down @common -Force }
        if ($Case -eq 'phones') { & $script -Action Phones @common -AcsPhoneNumber '+15555550100' -PhoneTarget realtime-api }
        if ($Case -in @('down','down-failure','purge')) {
            if ($Case -eq 'down-failure') { $global:Failure='test-demo-rt' }
            & $script -Action Down @common -Force -Purge:($Case -eq 'purge')
        }
    }
} catch { $caught=$_.Exception.Message }
$statePath=Join-Path $Root '.azure/demos/test-demo.json'
$state = if (Test-Path $statePath) { Get-Content -Raw $statePath | ConvertFrom-Json -AsHashtable } else { $null }
$summary=@{ Error=$caught; Calls=@($global:Calls.ToArray()); State=$state; Groups=@($global:Groups.Keys) }
Write-Output ('RESULT:' + ($summary | ConvertTo-Json -Depth 12 -Compress))
'''

WIRE_HELPER = r'''
param($Example, $ExampleEnv, $PlatformEnv, $AppLocation, [string[]]$Telephony, $TwilioAuthToken, $OverflowNumber)
$global:Calls.Add(@{Tool='wire'; Example=$Example; Env=$ExampleEnv; Platform=$PlatformEnv})
$v=$global:Values[$ExampleEnv]
$p=$global:Values[$PlatformEnv]
$v.SHARED_RESOURCE_GROUP=$p.SHARED_RESOURCE_GROUP
$v.SHARED_FOUNDRY_NAME=$p.SHARED_FOUNDRY_NAME
$v.AZURE_SEARCH_SERVICE_NAME=$p.AZURE_SEARCH_SERVICE_NAME
$v.AZURE_APP_LOCATION=$AppLocation
$v.TELEPHONY_PROVIDERS=$Telephony -join ','
if ($TwilioAuthToken) { $v.TWILIO_AUTH_TOKEN=$TwilioAuthToken }
$global:LASTEXITCODE=0
'''

PHONE_HELPER = r'''
param($Example, $ExampleEnv, $PhoneNumber, $EventSubscriptionName, [switch]$WriteAsteriskConfig, $AsteriskExtension)
$global:Calls.Add(@{Tool='phone'; Example=$Example; Env=$ExampleEnv; Route=$EventSubscriptionName; Extension=$AsteriskExtension})
$global:LASTEXITCODE=0
'''


def simulate(repo_root: Path, tmp_path: Path, case: str):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(repo_root / "scripts/demo.ps1", scripts / "demo.ps1")
    (scripts / "use-shared-platform.ps1").write_text(WIRE_HELPER, encoding="utf-8")
    for filename in ("configure-telephony.ps1", "enable-telephony.ps1"):
        (scripts / filename).write_text(PHONE_HELPER, encoding="utf-8")
    if case == "real-helpers":
        for filename in ("use-shared-platform.ps1", "enable-telephony.ps1"):
            shutil.copyfile(repo_root / "scripts" / filename, scripts / filename)
    for project in ("platform", "examples/voice-live-api", "examples/realtime-api", "examples/foundry-voice-agent"):
        (tmp_path / project).mkdir(parents=True)
    harness = tmp_path / "harness.ps1"
    harness.write_text(HARNESS, encoding="utf-8")
    result = subprocess.run(
        [PWSH, "-NoProfile", "-File", str(harness), "-Root", str(tmp_path), "-Case", case],
        text=True, capture_output=True, timeout=60, encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [line for line in result.stdout.splitlines() if line.startswith("RESULT:")]
    assert lines, result.stdout + result.stderr
    assert "synthetic-test-only-token" not in result.stdout + result.stderr
    return json.loads(lines[-1][7:])


def operations(result, verb):
    return [call for call in result["Calls"] if call["Tool"] == "azd" and call["Args"][0] == verb]


@pytest.mark.parametrize("case", ["up", "auth", "resume", "init-resume", "phones", "twilio", "real-helpers"])
def test_shared_up_and_resume(repo_root, tmp_path, case):
    result = simulate(repo_root, tmp_path, case)
    assert not result["Error"], result["Error"]
    assert result["State"]["Status"] == "Ready"
    assert len(result["Groups"]) == 4
    assert len(operations(result, "env")) > 0
    assert [call["Args"][call["Args"].index("--environment") + 1] for call in operations(result, "up")][-3:] == [
        "test-demo-vl", "test-demo-rt", "test-demo-agent"
    ]
    assert not operations(result, "down")
    for call in operations(result, "up") + operations(result, "provision"):
        assert "--environment" in call["Args"]
    if case == "phones":
        routes = [call for call in result["Calls"] if call["Tool"] == "phone" and call["Route"]]
        assert [route["Example"] for route in routes] == ["foundry-voice-agent", "realtime-api"]
        assert {route["Route"] for route in routes} == {"incoming-demo"}
        extensions = [call["Extension"] for call in result["Calls"] if call["Tool"] == "phone" and call["Extension"]]
        assert extensions == ["7001", "7002", "7003"] * 2
    if case == "twilio":
        assert all(call["Secure"] for call in result["Calls"] if call["Tool"] == "secure-prompt")
    if case == "real-helpers":
        configs = list((tmp_path / "examples").glob("*/.azure/*/asterisk/websocket_client.conf"))
        assert len(configs) == 3
        assert all("/telephony/asterisk/media" in path.read_text() for path in configs)


def test_whatif_is_completely_offline(repo_root, tmp_path):
    result = simulate(repo_root, tmp_path, "whatif")
    assert not result["Error"]
    assert result["Calls"] == []
    assert result["State"] is None
    assert not (tmp_path / ".azure").exists()


@pytest.mark.parametrize("case", ["untracked-down", "collision", "context", "drift", "environment-drift", "tag", "tag-collision"])
def test_refuses_unsafe_context_or_ownership(repo_root, tmp_path, case):
    result = simulate(repo_root, tmp_path, case)
    assert result["Error"]
    assert not operations(result, "down")
    if case in {"untracked-down", "collision", "context"}:
        assert not operations(result, "provision")
        assert result["State"] is None


@pytest.mark.parametrize("case", ["partial", "health"])
def test_failure_preserves_resources_without_rollback(repo_root, tmp_path, case):
    result = simulate(repo_root, tmp_path, case)
    assert result["Error"]
    assert result["State"]["Status"] == "InProgress"
    assert result["Groups"]
    assert not operations(result, "down")


@pytest.mark.parametrize("case", ["down", "purge", "down-failure"])
def test_teardown_order_and_explicit_purge(repo_root, tmp_path, case):
    result = simulate(repo_root, tmp_path, case)
    calls = operations(result, "down")
    names = [call["Args"][call["Args"].index("--environment") + 1] for call in calls]
    if case == "down-failure":
        assert result["Error"]
        assert names == ["test-demo-agent", "test-demo-rt"]
        assert "rg-test-demo-platform" in result["Groups"]
    else:
        assert not result["Error"], result["Error"]
        assert names == ["test-demo-agent", "test-demo-rt", "test-demo-vl", "test-demo-platform"]
        assert result["State"]["Status"] == "Removed"
        assert result["Groups"] == []
    assert all(("--purge" in call["Args"]) == (case == "purge") for call in calls)