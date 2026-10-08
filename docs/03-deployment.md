[README](../README.md) › [docs index](./00-reproduce-this-demo.md) › 03 Deployment

# 03 — Deployment

<p>
  <img src="./assets/icons/container-apps.svg" width="40" alt="Azure Container Apps">&nbsp;
  <img src="./assets/icons/container-registry.svg" width="40" alt="Azure Container Registry">&nbsp;
  <img src="./assets/icons/foundry.svg" width="40" alt="Microsoft Foundry">&nbsp;
  <img src="./assets/icons/ai-search.svg" width="40" alt="Azure AI Search">&nbsp;
  <img src="./assets/icons/communication-services.svg" width="40" alt="Azure Communication Services">
</p>

<p>
  <img src="./assets/badges/version.svg" alt="Version v1.4.2">
  <img src="./assets/badges/azd-up.svg" alt="azd up">
  <img src="./assets/badges/default.svg" alt="Shared deploy-all is the default path">
  <img src="./assets/badges/manual-path.svg" alt="Manual alternative: 03b">
  <img src="./assets/badges/public-preview.svg" alt="Foundry voice agent: Public preview">
</p>

Recommended deployment: **`scripts\demo.ps1` provisions one shared Foundry resource, Search, and all three apps**, with optional phone-provider setup and scoped teardown. The three examples deploy side by side to Azure Container Apps and differ only in the upstream API they call:

- `examples\voice-live-api\` → Azure AI Voice Live API.
- `examples\realtime-api\` → Azure OpenAI GPT Realtime API GA.
- `examples\foundry-voice-agent\` → Foundry voice agent public preview (served by Voice Live agent mode).

## At a glance

| | Step | Gate |
|---|---|---|
| <img src="./assets/icons/entra-id.svg" width="28" alt="Authenticate"> | **1.** Authenticate `az` and `azd` to an explicit tenant and subscription | ☐ `az account show` matches the target |
| <img src="./assets/icons/powershell.svg" width="28" alt="Install"> | **2.** Install dependencies in `.venv` | ☐ `requirements-agent.txt` installed |
| <img src="./assets/icons/dev-console.svg" width="28" alt="Dry run"> | **3.** `demo.ps1 -Action Up ... -WhatIf` (offline dry run) | ☐ Order and targets are as intended |
| <img src="./assets/icons/container-apps.svg" width="28" alt="Deploy"> | **4.** `demo.ps1 -Action Up` | ☐ Three browser URLs printed; `/healthz` and `/api/info` pass |
| <img src="./assets/icons/communication-services.svg" width="28" alt="Phones"> | **5.** Phone handoff (optional) | ☐ Provider and PBX configuration completed by you |
| <img src="./assets/icons/resource-group.svg" width="28" alt="Teardown"> | **6.** `demo.ps1 -Action Down` | ☐ Four owned resource groups removed |

> [!WARNING]
> **Tenant-explicit `az` / `azd` authentication is mandatory.** The active `az` and `azd` accounts silently drift across tenants and subscriptions; a bare `az login` or `azd up` can provision into the wrong place. Always sign in with `az login --tenant`, `az account set --subscription`, `az account show`, and `azd auth login --tenant-id` (the wrapper does this for you from `-TenantId` / `-SubscriptionId`).

> [!NOTE]
> **No-IaC alternative.** If the environment cannot run `azd` or Bicep, use [03b-manual-deployment.md](./03b-manual-deployment.md). It creates the same resource shape with Azure Portal and imperative Azure CLI commands.

> [!TIP]
> **Windows paths.** Commands below assume PowerShell on Windows. Keep backslash paths.

---

## Recommended shared deploy-all

![Deployment and regions](./assets/diagrams/04-deployment-and-regions.png)

<sub>Editable source: [`assets/diagrams/04-deployment-and-regions.drawio`](./assets/diagrams/04-deployment-and-regions.drawio) - regenerate with `python scripts/export_diagrams.py docs/assets`.</sub>

**Diagram scope:** the image matches this recommended shared path. The platform creates the Foundry resource/project/realtime deployment and owns the realtime quota pre-flight (`platform/hooks/preprovision.ps1`); the Realtime app's hook skips that check when `SHARED_FOUNDRY_NAME` is set. Each app keeps its own app tier and admission counter. Shared is **one Foundry resource, not one literal URL or quota pool**. Search is always included by the wrapper; telephony is opt-in, with ACS created only if selected. **Do not deploy `knowledge\` separately.** The standalone phases later in this guide remain an alternative, not extra shared-deployment steps.

### Prepare the local environment

Install the tools, permissions, providers, and quota prerequisites in [02](02-prerequisites.md), including **PowerShell 7 and Python 3.12+**. Shared mode also uses `Microsoft.Search`; ACS setup uses `Microsoft.Communication` and `Microsoft.EventGrid`. From the repo root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r scripts\requirements-agent.txt
```

The wrapper chooses `.venv/Scripts/python.exe` or `.venv/bin/python`, falling back to `python`. On non-Windows hosts install with `.venv/bin/python -m pip install -r scripts/requirements-agent.txt`. Install before actual `Up`: `azure-identity` supports Search loading and `azure-ai-projects` supports the voice-agent postprovision hook. The offline preview does not install anything.

### Preview and deploy, including phone setup

```powershell
$Demo = @{
  DemoName = "voice-demo"
  TenantId = "<tenant-guid>"
  SubscriptionId = "<subscription-guid>"
}

./scripts/demo.ps1 -Action Up @Demo -Location centralus -AppLocation eastus2 -RealtimeCapacity 10 -Telephony 'acs,twilio,asterisk' -WhatIf
./scripts/demo.ps1 -Action Up @Demo -Location centralus -AppLocation eastus2 -RealtimeCapacity 10 -Telephony 'acs,twilio,asterisk'
```

Select only the providers you intend to configure; omitting `-Telephony` gives a browser-only deployment with Search. This wrapper is scoped to a **first-time shared deployment with the existing model defaults**, not adoption of an existing manually deployed platform or a model-migration workflow.

| Parameter | Default / contract |
|---|---|
| `-Action` | `Up`, `Phones`, or `Down`. |
| `-DemoName` | Required. 3–20 lowercase letters/digits/hyphens, starting with a letter and ending alphanumeric. Example: `voice-demo`. |
| `-TenantId`, `-SubscriptionId` | Required explicit target GUIDs for all actions. |
| `-Location` | `Up`: `centralus` <img src="./assets/badges/default.svg" alt="Default">; allowed AI regions: `centralus`, `eastus2`, `swedencentral`. |
| `-AppLocation` | `Up`: same as AI region when omitted. Example override: `eastus2`, applied to all three app tiers. |
| `-RealtimeCapacity` | Initial deployment: `10` capacity units; existing model defaults are retained. |
| `-Telephony` | `Up`: none by default; comma-separated selection such as `'acs,twilio,asterisk'`. |
| `-PhoneTarget` | `foundry-voice-agent`; alternatives: `voice-live-api`, `realtime-api`. Selects the ACS incoming-call target, not all three simultaneously. |
| `-AcsPhoneNumber` | Optional E.164 number already acquired on this demo's ACS resource. Without it, ACS incoming-call routing is skipped. |
| `-OverflowNumber` | `Up`: optional E.164 fallback for ACS/Twilio. Asterisk uses external dialplan fallback. |
| `-SkipLogin` | Skip interactive `az`/`azd` login; still check `az` tenant/subscription context. |
| `-WhatIf` | **Offline** order/target preview, with no CLI calls, cloud access, or file changes. It is **not ARM what-if**. |
| `-Force` | `Down`: explicitly skip interactive confirmation for unattended teardown. |
| `-Purge` | `Down`: separate irreversible opt-in to `azd --purge`; does not guarantee Cognitive Services account purging. |

Actual `Up` performs these stages:

1. Authenticate both `az` and `azd` **tenant-explicitly**, select/check the requested subscription, unless sign-in is skipped. Context is checked even with `-SkipLogin`.
2. Create the owned platform environment and provision Foundry, the realtime deployment, the agent project, **Search always**, and **ACS only when `acs` is selected**. Load the **40 synthetic articles**; the 30 request records stay in local `sample-data.json`.
3. Create and wire each named app environment using the existing shared-platform helper. Run an **ARM preview then `azd up` sequentially** for Voice Live → Realtime → voice agent. The voice-agent postprovision hook creates an agent version.
4. Generate selected phone configs/routes, check `/healthz` and `/api/info` for the expected backend and provider configuration, and print **three browser URLs**. These checks do not establish upstream connectivity or real-call success; continue with [Phase 5](#phase-5--smoke-test) and [phone testing](07-telephony-and-shared-endpoint.md#test-plan).

### Ownership, retries, and cost

| Project | Environment | Owned resource group |
|---|---|---|
| `platform\` | `<DemoName>-platform` | `rg-<DemoName>-platform` |
| `examples\voice-live-api\` | `<DemoName>-vl` | `rg-<DemoName>-vl` |
| `examples\realtime-api\` | `<DemoName>-rt` | `rg-<DemoName>-rt` |
| `examples\foundry-voice-agent\` | `<DemoName>-agent` | `rg-<DemoName>-agent` |

The wrapper records **nonsecret context and ownership** in gitignored `.azure/demos/<DemoName>.json`, alongside each project's `.azure/<env>/.env`. Env files can contain secrets; never commit them. It refuses to adopt pre-existing environments/resource groups and refuses tenant, location, or provider drift on a rerun. Naming settings are immutable: do not rename the owned environments/resources or repurpose their manifest.

If a stage fails, fix the cause and rerun **the same Up arguments**. Existing env values are used for resume, not overwritten with fresh default model settings. There is **no automatic rollback**: already successful stages remain deployed and **continue to cost money**. Inspect and repair only the intended environment; the wrapper is not a relocation or provider-migration command.

### Complete phone setup without redeploying

- **Twilio:** missing auth tokens are **securely prompted**, never passed as command-line literals; existing secrets are kept. All three **HTTP POST** voice webhooks are printed. Configure the Twilio number/SIP Domain in Twilio Console yourself and choose **one app per number**.
- **Asterisk:** all three configs are generated under `examples/<example>/.azure/<env>/asterisk/`: extensions **7001 / 7002 / 7003** for Voice Live / Realtime / voice agent. Installing the PBX/provider and copying/merging these secret-bearing configs are manual steps.
- **ACS:** provisioning does not buy a number. Acquire one separately on the demo's ACS resource (**paid step**), then run:

```powershell
./scripts/demo.ps1 -Action Phones @Demo -PhoneTarget foundry-voice-agent -AcsPhoneNumber '+<E164-number>'
```

`Phones` reads providers from the manifest and reruns phone routing/config generation **without `azd up`**; no need to redeclare regions or providers. It creates/updates the stable **`incoming-demo`** Event Grid subscription on this demo's ACS resource, targeting `-PhoneTarget`. One ACS number routes to one app. Old manual Event Grid subscriptions are **not automatically removed**; check for duplicate number filters before testing. Detailed external handoff: [07 — Phone setup](07-telephony-and-shared-endpoint.md#recommended-wrapper-phone-setup).

### Shared teardown

```powershell
./scripts/demo.ps1 -Action Down @Demo -WhatIf
./scripts/demo.ps1 -Action Down @Demo
```

`Down` uses the same demo name/tenant/subscription, with no need to repeat region/provider arguments. It displays the **four scoped resource groups**, requests confirmation, then deletes **agent → Realtime → Voice Live → platform**. Add `-Force` only to opt into unattended confirmation; `-Purge` is a distinct opt-in for irreversible `azd --purge` behavior, **not a guarantee of Cognitive Services purging**. `-WhatIf` changes nothing and does not call ARM.

The wrapper keeps local manifest/env files for retries/audit; use a **new DemoName after full teardown**. It never removes `knowledge\` or unrelated environments. External Twilio/PBX configuration, phone numbers, and billing remain operator cleanup tasks. Use [Phase 8](#phase-8--tear-down) only for independently deployed standalone examples.

---

## Standalone alternative — phase overview

Follow Phases 0–4 **instead of** shared deploy-all when each example should own a separate Foundry resource/project. Install the local dependencies above before running the voice-agent hook. The optional add-ons below apply to this manual path; shared users already have Search and their selected phone providers.

| Phase | What you do | Typical time | Validation at end |
|---|---|---:|---|
| 0 | Authenticate `az` and `azd` to the intended tenant and subscription | 2-5 min | `az account show` matches the target |
| 1 | Pick a shared region and check provider registration, quota, and capacity | 5-10 min | Region is viable before provisioning |
| 2 | Deploy `examples\voice-live-api` with `azd up` | 10-15 min | App URL, Foundry resource, and Voice Live endpoint exist |
| 3 | Deploy `examples\realtime-api` with `azd up` | 10-15 min | App URL, Foundry resource, and model deployment exist |
| 4 | Deploy `examples\foundry-voice-agent` with `azd up` | 10-15 min | App URL, Foundry project, and voice agent version exist |
| opt | Optional add-ons: knowledge base, Asterisk/Twilio/ACS phone channels, app region | 5-20 min | `/api/info` shows `knowledge` and `telephony`; `probe-asterisk.py` gets audio |
| 5 | Smoke test all three deployed apps | 10 min | Browser, tool call, health, info, and metrics work |
| 6 | Run any example locally against deployed resources | 5-10 min | Local `uvicorn` app connects with your Azure identity |
| 7 | Change model, voice, capacity, agent profile, or concurrency and redeploy | 5-15 min | New values appear in `/api/info`, deployment list, or a new agent version |
| 8 | Tear down the selected standalone environments | 5-10 min | Owned resource groups removed; soft-deleted resources reviewed separately |

---

## What azd reads and writes

`azd` reads each example's `infra\main.parameters.json`, maps environment values to Bicep parameters, then writes deployment outputs to `.azure\<env>\.env`. Use `azd env get-values` to inspect or export those values, taking care not to share secrets. The contracts below also support manual standalone deployment; in shared mode, resource/project/deployment ownership stays with `platform\` and the wrapper supplies the shared values.

### Voice Live API IaC contract

| azd env value | Bicep parameter | Default from `main.parameters.json` | Used for |
|---|---|---|---|
| `AZURE_ENV_NAME` | `environmentName` | azd environment name | Resource group `rg-<env>` and resource-name suffix |
| `AZURE_LOCATION` | `location` | set by operator | Azure region |
| `AZURE_APP_LOCATION` | `appLocation` | empty (= `AZURE_LOCATION`) | Optional region for Container Apps, ACR, Log Analytics, and the app identity when Container Apps is constrained in the AI region; see [07](07-telephony-and-shared-endpoint.md#container-apps-in-a-different-region-than-the-ai-endpoint) |
| `AZURE_PRINCIPAL_ID` | `principalId` | set by azd when available | Optional deployer RBAC for local runs |
| `AZURE_PRINCIPAL_TYPE` | `principalType` | `User` | Principal type for deployer RBAC |
| `VOICE_LIVE_MODEL` | `voiceLiveModel` | `gpt-realtime-mini` | Managed Voice Live model |
| `VOICE_LIVE_VOICE` | `voiceLiveVoice` | `en-US-Ava:DragonHDLatestNeural` | Voice Live voice |
| `MAX_CONCURRENT_SESSIONS` | `maxConcurrentSessions` | `20` | Per-replica admission cap |
| `SERVICE_WEB_RESOURCE_EXISTS` | `webExists` | `false` | Preserve current image on re-provision |

| Voice Live output | Source | Notes |
|---|---|---|
| `AZURE_LOCATION` | `main.bicep` | Deployment region |
| `AZURE_TENANT_ID` | `main.bicep` | Tenant used by the deployment |
| `AZURE_RESOURCE_GROUP` | `main.bicep` | `rg-<env>` |
| `AZURE_CONTAINER_REGISTRY_ENDPOINT` | `resources.bicep` | ACR login server |
| `AZURE_CONTAINER_REGISTRY_NAME` | `resources.bicep` | ACR name |
| `SERVICE_WEB_NAME` | `resources.bicep` | Container App name |
| `SERVICE_WEB_URI` | `resources.bicep` | Public HTTPS URL |
| `VOICE_LIVE_ENDPOINT` | `resources.bicep` | `https://<foundry>.services.ai.azure.com` |
| `VOICE_LIVE_MODEL` | `main.bicep` | Active Voice Live model |
| `VOICE_LIVE_VOICE` | `main.bicep` | Active Voice Live voice |
| `VOICE_LIVE_API_VERSION` | `main.bicep` | `2026-07-15` |
| `FOUNDRY_RESOURCE_NAME` | `resources.bicep` | AIServices account name |

Container App environment variables set by Bicep are exactly: `VOICE_LIVE_ENDPOINT`, `VOICE_LIVE_API_VERSION`, `VOICE_LIVE_MODEL`, `VOICE_LIVE_VOICE`, `AZURE_CLIENT_ID`, `MAX_CONCURRENT_SESSIONS`, and `LOG_LEVEL`.

### Realtime API IaC contract

| azd env value | Bicep parameter | Default from `main.parameters.json` | Used for |
|---|---|---|---|
| `AZURE_ENV_NAME` | `environmentName` | azd environment name | Resource group `rg-<env>` and resource-name suffix |
| `AZURE_LOCATION` | `location` | set by operator | Azure region |
| `AZURE_APP_LOCATION` | `appLocation` | empty (= `AZURE_LOCATION`) | Optional region for Container Apps, ACR, Log Analytics, and the app identity when Container Apps is constrained in the AI region; see [07](07-telephony-and-shared-endpoint.md#container-apps-in-a-different-region-than-the-ai-endpoint) |
| `AZURE_PRINCIPAL_ID` | `principalId` | set by azd when available | Optional deployer RBAC for local runs |
| `AZURE_PRINCIPAL_TYPE` | `principalType` | `User` | Principal type for deployer RBAC |
| `AZURE_OPENAI_REALTIME_MODEL` | `realtimeModel` | `gpt-realtime-2.1-mini` | Model name deployed to Azure OpenAI |
| `AZURE_OPENAI_REALTIME_MODEL_VERSION` | `realtimeModelVersion` | empty | Optional override; Bicep defaults per model |
| `AZURE_OPENAI_REALTIME_DEPLOYMENT` | `realtimeDeploymentName` | empty | Optional deployment name; defaults to model name |
| `REALTIME_DEPLOYMENT_CAPACITY` | `realtimeDeploymentCapacity` | `10` | GlobalStandard capacity units; `gpt-realtime-2.1-mini` = 10K TPM + 20 RPM per unit (10 = 100K TPM). Checked by the `preprovision` hook |
| `REALTIME_VERSION_UPGRADE_OPTION` | `versionUpgradeOption` | `OnceCurrentVersionExpired` | Deployment version-upgrade policy |
| `REALTIME_VOICE` | `realtimeVoice` | `marin` | Realtime output voice |
| `MAX_CONCURRENT_SESSIONS` | `maxConcurrentSessions` | `20` | Per-replica admission cap |
| `SERVICE_WEB_RESOURCE_EXISTS` | `webExists` | `false` | Preserve current image on re-provision |

| Realtime output | Source | Notes |
|---|---|---|
| `AZURE_LOCATION` | `main.bicep` | Deployment region |
| `AZURE_TENANT_ID` | `main.bicep` | Tenant used by the deployment |
| `AZURE_RESOURCE_GROUP` | `main.bicep` | `rg-<env>` |
| `AZURE_CONTAINER_REGISTRY_ENDPOINT` | `resources.bicep` | ACR login server |
| `AZURE_CONTAINER_REGISTRY_NAME` | `resources.bicep` | ACR name |
| `SERVICE_WEB_NAME` | `resources.bicep` | Container App name |
| `SERVICE_WEB_URI` | `resources.bicep` | Public HTTPS URL |
| `AZURE_OPENAI_ENDPOINT` | `resources.bicep` | `https://<foundry>.openai.azure.com` |
| `AZURE_OPENAI_REALTIME_DEPLOYMENT` | `resources.bicep` | Deployment name used in the GA <img src="./assets/badges/ga.svg" alt="GA"> `model=` query |
| `AZURE_OPENAI_REALTIME_MODEL` | `main.bicep` | Active model label |
| `AZURE_OPENAI_REALTIME_MODEL_VERSION` | `resources.bicep` | Resolved model version |
| `REALTIME_VOICE` | `main.bicep` | Active Realtime voice |
| `FOUNDRY_RESOURCE_NAME` | `resources.bicep` | AIServices account name |

Container App environment variables set by Bicep are exactly: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_REALTIME_DEPLOYMENT`, `AZURE_OPENAI_REALTIME_MODEL`, `REALTIME_VOICE`, `AZURE_CLIENT_ID`, `MAX_CONCURRENT_SESSIONS`, and `LOG_LEVEL`.

### Foundry voice agent IaC contract

| azd env value | Bicep parameter | Default from `main.parameters.json` | Used for |
|---|---|---|---|
| `AZURE_ENV_NAME` | `environmentName` | azd environment name | Resource group `rg-<env>` and resource-name suffix |
| `AZURE_LOCATION` | `location` | set by operator | AI region for Foundry, Voice Live, and the Foundry project |
| `AZURE_APP_LOCATION` | `appLocation` | empty (= `AZURE_LOCATION`) | Optional app tier region for Container Apps, ACR, Log Analytics, and identity |
| `VOICE_AGENT_MODEL` | `voiceAgentModel` | `gpt-realtime-2.1-mini` | Managed model stored on the voice agent; no Azure OpenAI deployment |
| `VOICE_AGENT_VOICE` | `voiceAgentVoice` | `en-US-Ava:DragonHDLatestNeural` | Voice stored on the agent |
| `VOICE_AGENT_NAME` | `voiceAgentName` | `voice-agent-demo` | Agent name used in the Voice Live agent-mode URL |
| `VOICE_AGENT_PROJECT_NAME` | `voiceAgentProjectName` | `voice-agents` | Standalone Foundry project name |
| `SHARED_FOUNDRY_PROJECT` | `sharedFoundryProjectName` | empty | Shared platform project that holds the agent |
| `MAX_CONCURRENT_SESSIONS` | `maxConcurrentSessions` | `20` | Per-replica admission cap |
| `SERVICE_WEB_RESOURCE_EXISTS` | `webExists` | `false` | Preserve current image on re-provision |

| Voice-agent output | Source | Notes |
|---|---|---|
| `VOICE_AGENT_ENDPOINT` | `resources.bicep` | `https://<foundry>.services.ai.azure.com` |
| `VOICE_AGENT_PROJECT` | `resources.bicep` | Project name used as `agent-project-name` |
| `VOICE_AGENT_PROJECT_ENDPOINT` | `resources.bicep` | Used by `scripts\create-voice-agent.py` |
| `VOICE_AGENT_NAME` | `main.bicep` | Agent name |
| `VOICE_AGENT_MODEL` | `main.bicep` | Active managed model stored on the agent |
| `VOICE_AGENT_VOICE` | `main.bicep` | Active voice stored on the agent |
| `VOICE_AGENT_API_VERSION` | `main.bicep` | `2026-07-15` |

Container App environment variables set by Bicep are exactly: `VOICE_AGENT_ENDPOINT`, `VOICE_AGENT_PROJECT`, `VOICE_AGENT_NAME`, `VOICE_AGENT_API_VERSION`, `VOICE_AGENT_MODEL`, `VOICE_AGENT_VOICE`, `AZURE_CLIENT_ID`, `MAX_CONCURRENT_SESSIONS`, and `LOG_LEVEL`, plus shared search/telephony values when enabled. The `postprovision` hook creates or versions the agent from `config\agent-profile.json`; re-run `azd hooks run postprovision` after profile edits.

---

## Phase 0 — Authenticate to the right tenant

**Standalone/manual path only.** Shared deploy-all handles this authentication gate itself; do not create a second set of environments by repeating Phases 0–4 after `Up`.

> [!WARNING]
> **Do this first every time.** Never run a bare `az login` or trust ambient `azd` state before token acquisition or resource writes; the active tenant and subscription can differ from the one you intend.

Set target values:

```powershell
$TenantId = "<TENANT_ID>"
$SubscriptionId = "<SUBSCRIPTION_ID>"
```

Sign in and pin the subscription:

```powershell
az login --tenant $TenantId
# If no browser is available:
# az login --tenant $TenantId --use-device-code

az account set --subscription $SubscriptionId
az account show --query "{tenant:tenantId, subscription:id, subName:name, user:user.name}" -o table

azd auth login --tenant-id $TenantId
```

### Phase 0 validation

- [ ] `az account show` returns the intended tenant ID.
- [ ] `az account show` returns the intended subscription ID.
- [ ] `azd auth login --tenant-id <TENANT_ID>` completed for the same tenant.
- [ ] No deployment command has run before this validation passed.

---

## Phase 1 — Pick a region and check quota/availability

Use one region for all examples when you want a fair side-by-side. The Tier-1 side-by-side regions are:

| Tier | Regions | Why |
|---|---|---|
| Tier 1 | `centralus`, `eastus2`, `swedencentral` | Confirmed for Voice Live `gpt-realtime-mini` and Realtime API Global Standard realtime models |
| Also viable for Voice Live-only | `westus2` | Confirmed for Voice Live but not the strongest default for a side-by-side |

Set a shared region:

```powershell
$Location = "centralus"
```

Register providers if this subscription is new to these services:

```powershell
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.ContainerRegistry
az provider register --namespace Microsoft.CognitiveServices
az provider register --namespace Microsoft.ManagedIdentity
az provider register --namespace Microsoft.OperationalInsights

az provider show --namespace Microsoft.App --query registrationState -o tsv
az provider show --namespace Microsoft.CognitiveServices --query registrationState -o tsv
```

Check Cognitive Services usage and quota in the target region:

```powershell
az cognitiveservices usage list -l $Location -o table
```

What to look for:

- For **Realtime API**, confirm the subscription has available Global Standard realtime quota before deploying the model. Realtime quota is tracked at subscription level for the relevant pool; moving regions can fix capacity placement, but it does not create more subscription quota.
- For **Voice Live**, remember the service is managed model mode with no customer model deployment, but the resource still has service limits: 100 new connections per minute, 120,000 TPM, and 60-minute sessions at the default S0 limit.
- For any option, if the target model is not available or capacity is exhausted in the region, switch to another Tier-1 region before provisioning.

### Phase 1 validation

- [ ] `Microsoft.App`, `Microsoft.ContainerRegistry`, `Microsoft.CognitiveServices`, `Microsoft.ManagedIdentity`, and `Microsoft.OperationalInsights` are registered or registering.
- [ ] `$Location` is one of `centralus`, `eastus2`, or `swedencentral` for side-by-side deployment.
- [ ] `az cognitiveservices usage list -l $Location -o table` has been reviewed for quota and capacity risk.
- [ ] Any required quota request is filed before a demo or production build.

---

## Phase 2 — Deploy the Voice Live example

Voice Live creates no model deployment. The app connects to the managed Voice Live model through an AIServices account.

```powershell
cd <repo-root>\examples\voice-live-api

azd env new vl-<name>
azd env set AZURE_TENANT_ID $TenantId
azd env set AZURE_SUBSCRIPTION_ID $SubscriptionId
azd env set AZURE_LOCATION $Location

# Optional preview model. Default is gpt-realtime-mini.
azd env set VOICE_LIVE_MODEL gpt-realtime-2.1-mini

azd env get-values
azd up
```

What gets created:

- Resource group `rg-<azd-env-name>`.
- Log Analytics workspace.
- Azure Container Apps environment.
- Azure Container Registry Basic with admin user disabled.
- User-assigned managed identity.
- `AcrPull` assignment from the identity to ACR.
- AIServices Foundry account with custom subdomain and local auth disabled.
- Cognitive Services User and Foundry User assignments for the Container App identity, plus the deploying principal when `AZURE_PRINCIPAL_ID` is present.
- Azure Container App with external ingress on port 8000, one replica, `/healthz` probes, and the Voice Live environment variables listed above.

Expected duration: about 10-15 minutes, dominated by provider readiness and ACR remote build. A local Docker daemon is not required because `azure.yaml` uses `docker.remoteBuild: true`.

Capture the outputs:

```powershell
azd env get-values
```

### Phase 2 validation

- [ ] `azd up` completed without an infrastructure or deployment error.
- [ ] `azd env get-values` includes `SERVICE_WEB_URI`.
- [ ] `azd env get-values` includes `VOICE_LIVE_ENDPOINT`.
- [ ] `azd env get-values` includes `FOUNDRY_RESOURCE_NAME`.
- [ ] `azd env get-values` reports `VOICE_LIVE_MODEL` as the intended value.

---

## Phase 3 — Deploy the Realtime API example

The Realtime API example creates and sizes an Azure OpenAI realtime model deployment. The default is `gpt-realtime-2.1-mini` version `2026-07-07`; `gpt-realtime-mini` uses version `2025-12-15` unless you override `AZURE_OPENAI_REALTIME_MODEL_VERSION`.

```powershell
cd <repo-root>\examples\realtime-api

azd env new rt-<name>
azd env set AZURE_TENANT_ID $TenantId
azd env set AZURE_SUBSCRIPTION_ID $SubscriptionId
azd env set AZURE_LOCATION $Location
azd env set AZURE_OPENAI_REALTIME_MODEL gpt-realtime-2.1-mini
azd env set REALTIME_DEPLOYMENT_CAPACITY 10

azd env get-values
azd up
```

Optional overrides:

```powershell
azd env set AZURE_OPENAI_REALTIME_DEPLOYMENT <deployment-name>
azd env set AZURE_OPENAI_REALTIME_MODEL_VERSION <model-version>
azd env set REALTIME_VOICE marin
azd env set MAX_CONCURRENT_SESSIONS 20
```

What gets created:

- Same base resources as the Voice Live example: resource group, Log Analytics, Container Apps environment, ACR Basic with admin disabled, user-assigned managed identity, `AcrPull`, AIServices account, and one Container App.
- Azure OpenAI realtime model deployment under the AIServices account:
  - `sku.name`: `GlobalStandard`.
  - `sku.capacity`: `REALTIME_DEPLOYMENT_CAPACITY`.
  - `model.format`: `OpenAI`.
  - `model.name`: `AZURE_OPENAI_REALTIME_MODEL`.
  - `model.version`: resolved from Bicep defaults or `AZURE_OPENAI_REALTIME_MODEL_VERSION`.
  - `raiPolicyName`: `Microsoft.DefaultV2`.
  - `versionUpgradeOption`: `REALTIME_VERSION_UPGRADE_OPTION`.
- Cognitive Services OpenAI User assignments for the Container App identity, plus the deploying principal when `AZURE_PRINCIPAL_ID` is present.

Check the deployment afterwards:

```powershell
$Rg = azd env get-value AZURE_RESOURCE_GROUP
$Foundry = azd env get-value FOUNDRY_RESOURCE_NAME

az cognitiveservices account deployment list -n $Foundry -g $Rg -o table
```

Expected duration: about 10-15 minutes when quota and regional capacity are already available. `InsufficientQuota` or capacity errors happen during the model deployment step, not during image build.

### Phase 3 validation

- [ ] `azd up` completed without `InsufficientQuota` or model availability errors.
- [ ] `azd env get-values` includes `SERVICE_WEB_URI`.
- [ ] `azd env get-values` includes `AZURE_OPENAI_ENDPOINT`.
- [ ] `azd env get-values` includes `AZURE_OPENAI_REALTIME_DEPLOYMENT`.
- [ ] `az cognitiveservices account deployment list -n $Foundry -g $Rg -o table` shows the intended model deployment.

---

## Phase 4 — Deploy the Foundry voice agent example (preview)

```powershell
cd <repo-root>\examples\foundry-voice-agent

azd env new va-<name>
azd env set AZURE_TENANT_ID $TenantId
azd env set AZURE_SUBSCRIPTION_ID $SubscriptionId
azd env set AZURE_LOCATION $Location
azd up
```

What gets created:

- Same base resources as the other examples: resource group, Log Analytics, Container Apps environment, ACR Basic, user-assigned managed identity, `AcrPull`, and one Container App.
- AIServices Foundry account with `disableLocalAuth: true`, `allowProjectManagement: true`, and a system-assigned identity.
- Foundry project `voice-agents` in standalone mode.
- Cognitive Services User and Foundry User assignments for the app identity, plus Foundry User for the deploying principal when `AZURE_PRINCIPAL_ID` is present.
- A voice agent version created by `examples\foundry-voice-agent\hooks\postprovision.ps1`, which runs `scripts\create-voice-agent.py --project-endpoint ...`.

Validation:

```powershell
azd env get-values
$ServiceWebUri = azd env get-value SERVICE_WEB_URI
curl.exe "$ServiceWebUri/healthz"
curl.exe "$ServiceWebUri/api/info"
```

### Phase 4 validation

- [ ] `azd up` completed and the postprovision hook did not fail.
- [ ] `VOICE_AGENT_ENDPOINT`, `VOICE_AGENT_PROJECT`, and `VOICE_AGENT_NAME` are present.
- [ ] `/api/info` reports the Foundry voice agent example.
- [ ] Re-running `azd hooks run postprovision` after profile edits creates a new agent version.

---

## Optional add-ons: knowledge base and phone channels

**Standalone/manual alternative only.** Independently deployed examples use the browser and local knowledge file by default. Shared `demo.ps1 Up` already deploys Search, loads the articles, and enables the selected phone channels: **do not deploy `knowledge\` again**. Use `demo.ps1 -Action Phones` for the shared routing/config handoff. For standalone examples, add any of these before (or after) `azd up`; each is a few `azd env` values plus a re-deploy.

| Add-on | What you run | Extra settings it creates | Details |
|---|---|---|---|
| Azure AI Search knowledge base (synthetic, 40 articles) | `cd knowledge; azd up`, then `./scripts/use-knowledge-base.ps1 -Example <x> -KnowledgeEnv <kb-env>` | `SHARED_RESOURCE_GROUP`, `AZURE_SEARCH_SERVICE_NAME`, `AZURE_SEARCH_INDEX`, `AZURE_SEARCH_SEMANTIC_CONFIG` | [10](10-knowledge-base.md) |
| **Asterisk** over WSS (`chan_websocket`) | `./scripts/enable-telephony.ps1 -Example <x> -Providers asterisk` | `TELEPHONY_PROVIDERS`, `TELEPHONY_WEBHOOK_SECRET`, `ASTERISK_WEBSOCKET_SECRET` (generated) | below, [07 §7](07-telephony-and-shared-endpoint.md#7-connect-asterisk-directly-over-wss-no-twilio) |
| Twilio number or SIP Domain | `./scripts/enable-telephony.ps1 -Example <x> -Providers twilio` with an existing token, or a masked interactive token variable as in [07](07-telephony-and-shared-endpoint.md#4-point-each-app-at-the-platform-and-deploy) | `TELEPHONY_PROVIDERS`, `TELEPHONY_WEBHOOK_SECRET` (generated), `TWILIO_AUTH_TOKEN` (yours) | [07 §6](07-telephony-and-shared-endpoint.md#6-route-twilio-numbers-and-pbx-calls) |
| Azure Communication Services number | Shared platform: `./scripts/use-shared-platform.ps1 -Example <x> -PlatformEnv <p> -Telephony acs` | `TELEPHONY_PROVIDERS`, `TELEPHONY_WEBHOOK_SECRET`, `ACS_EVENTGRID_SECRET` (generated), `ACS_RESOURCE_NAME` | [07 §5](07-telephony-and-shared-endpoint.md#5-route-acs-numbers-event-grid) |
| Container Apps in another region | `azd env set AZURE_APP_LOCATION <region>` | — | [07](07-telephony-and-shared-endpoint.md#container-apps-in-a-different-region-than-the-ai-endpoint) |

Channels can be combined: `-Providers asterisk,twilio`. Browser sessions and every phone channel share
one admission cap (`MAX_CONCURRENT_SESSIONS`) **within each app**, not across the three apps.

### Deploy with the Asterisk channel

Requirements on the Asterisk side: Asterisk **20.16+, 21.11+, 22.6+ or 23** (the WebSocket channel driver
`chan_websocket` and `res_websocket_client`), outbound HTTPS/WSS (TCP 443) to `*.azurecontainerapps.io`,
and a CA bundle that trusts public certificates. JSON control messages (`f(json)`) need 20.18+/22.8+/23.2+.

```powershell
# 1. Generate and store the settings (idempotent; keeps existing secrets)
./scripts/enable-telephony.ps1 -Example foundry-voice-agent -Providers asterisk

# 2. Deploy (new settings become Container Apps secrets)
cd examples\foundry-voice-agent
azd up

# 3. Write ready-to-copy Asterisk config with the real URL and password
cd ..\..
./scripts/enable-telephony.ps1 -Example foundry-voice-agent -WriteAsteriskConfig   # [-AsteriskExtension 7001]

# 4. Verify the endpoint before touching Asterisk
cd examples\foundry-voice-agent
$env:ASTERISK_WEBSOCKET_SECRET = azd env get-value ASTERISK_WEBSOCKET_SECRET
python ..\..\scripts\probe-asterisk.py --url "$((azd env get-value SERVICE_WEB_URI) -replace '^https','wss')/telephony/asterisk/media"
```

Step 3 writes two files under `examples\<x>\.azure\<env>\asterisk\` (gitignored; `websocket_client.conf`
contains the password):

- `websocket_client.conf`: append to `/etc/asterisk/websocket_client.conf`, then `asterisk -rx "module reload res_websocket_client.so"`.
- `extensions.conf`: add the extension to the context your phones dial from, then `asterisk -rx "dialplan reload"`.

**What the extra settings are and how they are generated**

| Setting | Purpose | Generated by | Where it lives |
|---|---|---|---|
| `TELEPHONY_PROVIDERS` | Turns on the routes (`asterisk` mounts `/telephony/asterisk/media`) | `enable-telephony.ps1` | azd env → Container App env var |
| `TELEPHONY_WEBHOOK_SECRET` | Signs per-call tokens (required whenever any channel is on; ≥16 chars) | `enable-telephony.ps1` (32 random bytes, URL-safe base64) | azd env → Container Apps **secret** |
| `ASTERISK_WEBSOCKET_SECRET` | Password Asterisk sends (HTTP Basic, `username` is ignored) or `?secret=`; ≥16 chars | `enable-telephony.ps1` (32 random bytes, URL-safe base64) | azd env → Container Apps **secret**; copied into Asterisk `websocket_client.conf` |

To generate a value yourself instead (same strength, no `;` or quotes, safe in Asterisk `.conf` files):

```powershell
# PowerShell
[Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).TrimEnd('=').Replace('+','-').Replace('/','_')
```

```bash
# Python (any OS) or OpenSSL on the Asterisk host
python -c "import secrets; print(secrets.token_urlsafe(32))"
openssl rand -base64 32 | tr '+/' '-_' | tr -d '='
```

Then `azd env set ASTERISK_WEBSOCKET_SECRET <value>` (and `TELEPHONY_WEBHOOK_SECRET`) and `azd provision`.

**After every `azd down` + `azd up`** the Container Apps hostname changes: re-run `-WriteAsteriskConfig` and update Asterisk, or calls fail before reaching the app.

**Rotate** with `./scripts/enable-telephony.ps1 -Example <x> -Providers asterisk -RotateSecrets`, `azd provision`,
then `-WriteAsteriskConfig` again and update Asterisk (calls fail with HTTP 403 until the password matches).
**Turn off** all phone channels with `-Disable` and `azd provision`.

### Optional add-ons validation

- [ ] `GET /api/info` lists the enabled channels in `telephony` and the backend in `knowledge`.
- [ ] `scripts\probe-asterisk.py` reports `connected (subprotocol=media)`, `START_MEDIA_BUFFERING`, and agent audio.
- [ ] A wrong secret is rejected (HTTP 403).
- [ ] Secrets appear only in `.azure\<env>\.env`, Container Apps secrets, and Asterisk's `websocket_client.conf` — never in Bicep outputs or committed files.

---

## Phase 5 — Smoke test

Run these checks for each example from that example's folder.

```powershell
$ServiceWebUri = azd env get-value SERVICE_WEB_URI

curl.exe "$ServiceWebUri/healthz"
curl.exe "$ServiceWebUri/api/info"
```

Expected results:

- `/healthz` returns `{"status":"ok"}`.
- `/api/info` returns the API name, model, voice, active sessions, and max sessions.

These GETs validate the app and its reported configuration, **not upstream audio or real phone calls**. For shared deployment, select the matching `<DemoName>-vl`, `-rt`, or `-agent` environment before reading its URL; also check Search and phone providers in `/api/info`.

Open the browser:

```powershell
Start-Process $ServiceWebUri
```

In the browser:

1. Select **Start**.
2. Allow microphone access.
3. Speak a short request and confirm audio returns.
4. Type `What's the status of request SR-1001?` and send it.
5. Confirm the **Tools** panel shows `lookup_request_status` and the result contains the fictional Contoso service desk record.
6. Confirm the **Metrics** panel updates Last TTFA, Last response, token counts, session turns, total tokens, tokens per minute, and p50/p90 TTFA.

### Phase 5 validation

- [ ] `/healthz` returns `status: ok` for Voice Live.
- [ ] `/api/info` reports `Voice Live API` for Voice Live.
- [ ] `/healthz` returns `status: ok` for Realtime API.
- [ ] `/api/info` reports `Realtime API` for Realtime.
- [ ] `/healthz` returns `status: ok` for the Foundry voice agent.
- [ ] `/api/info` reports the Foundry voice agent example.
- [ ] Browser microphone prompt appears and is accepted.
- [ ] Spoken turn returns audio.
- [ ] Typed SR-1001 turn exercises `lookup_request_status`.
- [ ] Metrics panel updates after at least one complete turn.

---

## Phase 6 — Local run against deployed resources

Local runs use the Azure identity from your local `az` login. The Bicep grants the deploying principal the required roles only when `AZURE_PRINCIPAL_ID` is populated, and RBAC can take a few minutes to propagate.

Voice Live:

```powershell
cd <repo-root>\examples\voice-live-api
azd env get-values > .env.local
..\..\scripts\run-local.ps1 -Example voice-live-api
```

Realtime API:

```powershell
cd <repo-root>\examples\realtime-api
azd env get-values > .env.local
..\..\scripts\run-local.ps1 -Example realtime-api
```

Foundry voice agent:

```powershell
cd <repo-root>\examples\foundry-voice-agent
azd env get-values > .env.local
..\..\scripts\run-local.ps1 -Example foundry-voice-agent
```

Open `http://127.0.0.1:8000` after `uvicorn` starts.

If local upstream calls return 401 or 403 immediately after provisioning, wait 5-10 minutes and retry. If they still fail, confirm your deploying principal was assigned roles on the Foundry account.

### Phase 6 validation

- [ ] `.env.local` exists in the selected example folder and came from `azd env get-values`.
- [ ] `..\..\scripts\run-local.ps1 -Example voice-live-api` starts `uvicorn` for Voice Live.
- [ ] `..\..\scripts\run-local.ps1 -Example realtime-api` starts `uvicorn` for Realtime API.
- [ ] `http://127.0.0.1:8000/healthz` returns `status: ok`.
- [ ] Browser smoke test works locally after RBAC propagation.

---

## Phase 7 — Change model, voice, capacity, or concurrency and redeploy

These are advanced manual operations, beyond the wrapper's first-time default-model scope. In **shared mode**, the realtime model and capacity belong to the **platform environment**, not the Realtime app environment shown below; update the platform and rewire affected apps. Never change wrapper-owned naming, tenant, location, or provider settings to resume a failed run.

Use `azd provision` when you change a Bicep parameter or Container App environment value. Use `azd deploy` when only application code, static assets, or Python files changed. Use `azd up` when you want both in sequence.

Voice Live examples:

```powershell
cd <repo-root>\examples\voice-live-api

azd env set VOICE_LIVE_MODEL gpt-realtime-mini
azd env set VOICE_LIVE_VOICE en-US-Ava:DragonHDLatestNeural
azd env set MAX_CONCURRENT_SESSIONS 20

azd provision
```

Realtime API examples:

```powershell
cd <repo-root>\examples\realtime-api

azd env set AZURE_OPENAI_REALTIME_MODEL gpt-realtime-2.1-mini
azd env set REALTIME_DEPLOYMENT_CAPACITY 10
azd env set REALTIME_VOICE marin
azd env set MAX_CONCURRENT_SESSIONS 20

azd provision
```

Foundry voice agent examples:

```powershell
cd <repo-root>\examples\foundry-voice-agent

azd env set VOICE_AGENT_MODEL gpt-realtime-2.1-mini
azd env set VOICE_AGENT_VOICE en-US-Ava:DragonHDLatestNeural
azd env set MAX_CONCURRENT_SESSIONS 20

azd provision
azd hooks run postprovision   # publish profile/model/voice changes as a new agent version
```

After a code-only change:

```powershell
azd deploy
```

After both infra settings and code changed:

```powershell
azd provision
azd deploy
```

Validation commands:

```powershell
$ServiceWebUri = azd env get-value SERVICE_WEB_URI
curl.exe "$ServiceWebUri/api/info"

$Rg = azd env get-value AZURE_RESOURCE_GROUP
$Foundry = azd env get-value FOUNDRY_RESOURCE_NAME
az cognitiveservices account deployment list -n $Foundry -g $Rg -o table
```

### Phase 7 validation

- [ ] Model and voice changes appear in `/api/info`.
- [ ] Realtime model deployment changes appear in `az cognitiveservices account deployment list`.
- [ ] `MAX_CONCURRENT_SESSIONS` changes are reflected in `/api/info`.
- [ ] `azd deploy` was run after any application code or static asset change.

---

## Phase 8 — Tear down

**Standalone alternative only.** Shared deployments use [the wrapper's scoped teardown](#shared-teardown), which also removes the platform last. For independently deployed examples, select the intended environment in each folder before deletion:

```powershell
cd <repo-root>\examples\voice-live-api
azd env select <voice-live-env-name>
azd down

cd <repo-root>\examples\realtime-api
azd env select <realtime-env-name>
azd down

cd <repo-root>\examples\foundry-voice-agent
azd env select <voice-agent-env-name>
azd down
```

Add `--purge` only as an explicit, irreversible opt-in. Do not assume it guarantees Cognitive Services account purging; review retained soft-deleted accounts separately. If you also created a standalone `knowledge\` environment, select and tear down that specific environment yourself. External phone-provider/PBX settings, phone numbers, and billing also need operator cleanup.

If you need to inspect or purge a leftover account manually:

```powershell
az cognitiveservices account list-deleted -o table
az cognitiveservices account purge --name <account-name> --resource-group <deleted-resource-group> --location <region>
```

### Phase 8 validation

- [ ] `azd down` completed for each intended standalone environment; any purge was explicitly requested.
- [ ] The resource group no longer appears in the portal or `az group list`.
- [ ] `az cognitiveservices account list-deleted -o table` does not show a leftover account name you plan to reuse.

---

## Post-deployment checklist

> [!NOTE]
> Tick every box before a live walkthrough; the smoke test proves the app, not upstream audio or real calls.

- [ ] Voice Live, Realtime API, and Foundry voice agent were deployed to the same Tier-1 region for side-by-side testing.
- [ ] Browser smoke test passed for all deployed examples.
- [ ] Local run passed for at least one example.
- [ ] Load test plan in [04-testing.md](./04-testing.md) is ready before any live walkthrough.
- [ ] Troubleshooting runbook in [05-troubleshooting.md](./05-troubleshooting.md) is available during the demo.
- [ ] Teardown command and purge behavior are understood before creating throwaway environments.

**Next:** prefer the portal/CLI route? See [03b — Manual deployment](./03b-manual-deployment.md); otherwise continue with [04 — Testing](./04-testing.md).

---

*Last updated: 2026-10-02*
