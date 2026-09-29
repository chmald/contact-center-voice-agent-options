# 00 — Reproduce this demo

Single-page orchestrator for standing up all three browser voice-agent examples from a clean clone.

> **Time budget.** First-time stand-up for all three examples: **about 75-110 minutes**, mostly Azure deployment and model-capacity validation. Subsequent rebuild in the same tenant: **about 25 minutes** if providers, quota, and env names are already known.

---

## What you end up with

![Deployment and regions](./assets/diagrams/04-deployment-and-regions.png)

```
Browser with microphone
        |
        |  WSS /ws
        v
+----------------------------+       +-----------------------------------+       +-----------------------------------+
| Container App              |       | Container App                     |       | Container App                     |
| examples\voice-live-api    |       | examples\realtime-api             |       | examples\foundry-voice-agent     |
| shared client + core       |       | shared client + core              |       | shared client + core              |
+-------------+--------------+       +---------------+-------------------+       +---------------+-------------------+
              |                                      |                                           |
              | Entra bearer token                   | Entra bearer token                        | Entra bearer token
              v                                      v                                           v
+----------------------------+       +-----------------------------------+       +-----------------------------------+
| Voice Live API             |       | Azure OpenAI Realtime API GA      |       | Voice Live agent mode             |
| managed model              |       | model deployment                  |       | Foundry voice agent (preview)     |
| same Azure region          |       | same Azure region                 |       | same Azure region                 |
+----------------------------+       +-----------------------------------+       +-----------------------------------+
```

Use `centralus`, `eastus2`, or `swedencentral` for the cleanest same-region comparison; re-check that the region supports both Agent Service voice agents and Voice Live before using the preview voice-agent example.

> **Phone calls, RAG, or one shared AI endpoint?** This page stands up each example standalone (each with its own Foundry resource). To run all three on a single endpoint in one subscription, with ACS/Twilio phone numbers and an Azure AI Search knowledge index, follow [07 — Telephony and the shared AI endpoint](07-telephony-and-shared-endpoint.md) instead of Parts B–C.

---

## Prerequisites checklist

Full detail is in [02-prerequisites.md](./02-prerequisites.md).

- [ ] Azure CLI installed and signed into the intended tenant only after explicit tenant selection.
- [ ] `azd` 1.30+ installed.
- [ ] Bicep 0.43+ available through Azure CLI.
- [ ] Python 3.12+ available.
- [ ] PowerShell 7 available for `scripts\run-local.ps1`.
- [ ] Modern browser with microphone permissions.
- [ ] Subscription permission: Contributor plus User Access Administrator, or Owner.
- [ ] Resource providers registered: `Microsoft.App`, `Microsoft.CognitiveServices`, `Microsoft.ContainerRegistry`, `Microsoft.OperationalInsights`, `Microsoft.ManagedIdentity`.
- [ ] Realtime quota checked in the target region before deploying `examples\realtime-api`.
- [ ] Deployer will receive Foundry User on the Foundry resource before the voice-agent postprovision hook creates an agent version.

---

## Part A — Tools and tenant auth

### A1. Verify local tools

```powershell
az version
azd version
az bicep version
python --version
$PSVersionTable.PSVersion
```

### A2. Authenticate to the intended tenant and subscription

```powershell
$TenantId = "<tenant-id>"
$SubscriptionId = "<subscription-id>"

az login --tenant $TenantId
az account set --subscription $SubscriptionId
az account show --query "{tenant:tenantId, subscription:id, name:name, user:user.name}" -o table
azd auth login --tenant-id $TenantId
```

**Checkpoint A**

- [ ] `az account show` returns the intended tenant and subscription.
- [ ] `azd auth login --tenant-id` completed for the same tenant.
- [ ] No command depended on ambient login state.

---

## Part B — Deploy the Voice Live example

```powershell
cd <repo-root>\examples\voice-live-api
azd env new <voice-live-env-name>
azd env set AZURE_TENANT_ID $TenantId
azd env set AZURE_SUBSCRIPTION_ID $SubscriptionId
azd env set AZURE_LOCATION centralus
azd up
azd env get-values
```

The default model is `gpt-realtime-mini`. To try the preview `gpt-realtime-2.1-mini` path for a same-model bake-off later:

```powershell
azd env set VOICE_LIVE_MODEL gpt-realtime-2.1-mini
azd provision
```

**Checkpoint B**

- [ ] `azd up` completes.
- [ ] `SERVICE_WEB_URI` is present in `azd env get-values`.
- [ ] Browser opens the app and `/api/info` shows `Voice Live API`.
- [ ] Foundry resource has local auth disabled and the managed identity has Cognitive Services User plus Foundry User.

---

## Part C — Deploy the Realtime example

### C1. Pre-flight quota check

```powershell
$Region = "centralus"
az cognitiveservices usage list -l $Region -o table
```

Confirm available quota for the realtime Global Standard deployment before proceeding. If quota is not visible or insufficient, request more through https://aka.ms/oai/stuquotarequest.

### C2. Deploy

```powershell
cd <repo-root>\examples\realtime-api
azd env new <realtime-env-name>
azd env set AZURE_TENANT_ID $TenantId
azd env set AZURE_SUBSCRIPTION_ID $SubscriptionId
azd env set AZURE_LOCATION $Region
azd up
azd env get-values
```

The default model is `gpt-realtime-2.1-mini` version `2026-07-07`, deployment name `gpt-realtime-2.1-mini`, and `REALTIME_DEPLOYMENT_CAPACITY=10` (RPM capacity units; the `preprovision` hook checks it against available quota).

**Checkpoint C**

- [ ] Quota check completed before deployment.
- [ ] `azd up` completes.
- [ ] `SERVICE_WEB_URI` is present in `azd env get-values`.
- [ ] Browser opens the app and `/api/info` shows `Realtime API`.
- [ ] A model deployment exists on the Foundry resource.

---

## Part D — Deploy the Foundry voice agent example (preview)

```powershell
cd <repo-root>\examples\foundry-voice-agent
azd env new <voice-agent-env-name>
azd env set AZURE_TENANT_ID $TenantId
azd env set AZURE_SUBSCRIPTION_ID $SubscriptionId
azd env set AZURE_LOCATION $Region
azd up
azd env get-values
```

`azd up` provisions the app stack plus a Foundry `AIServices` account with project management enabled and a `voice-agents` project. The `postprovision` hook then runs `scripts\create-voice-agent.py` to create a versioned voice agent from `config\agent-profile.json`; the deploying user needs **Foundry User** for that step. After profile edits, run `azd hooks run postprovision` to publish a new agent version.

**Checkpoint D**

- [ ] `azd up` completes, including the `postprovision` hook.
- [ ] `SERVICE_WEB_URI`, `VOICE_AGENT_ENDPOINT`, `VOICE_AGENT_PROJECT`, and `VOICE_AGENT_NAME` are present in `azd env get-values`.
- [ ] Browser opens the app and `/api/info` shows the Foundry voice agent example.
- [ ] A Foundry project contains a voice agent version created from `config\agent-profile.json`.

---

## Part E — Smoke test all three apps

Run these checks against each `SERVICE_WEB_URI`: Voice Live, Realtime API, and Foundry voice agent.

### D1. Browser voice turn

1. Open the app.
2. Select **Start** and allow microphone access.
3. Speak a short greeting.
4. Confirm assistant audio plays back.

### D2. Text turn

Type a short non-tool question such as:

```text
Give me a one-sentence greeting.
```

### D3. Tool turn

Open `config\sample-data.json`, choose one sample record ID, and ask for its status through the browser text box. This confirms the server-side tool path without hardcoding a record value in the docs.

**Checkpoint E**

- [ ] Voice input returns audio output.
- [ ] Text input returns a spoken or transcript response.
- [ ] Tool turn produces a `tool_call` entry in the UI.
- [ ] Metrics update after each completed turn.

---

## Part F — Run the load probe

From the repo root, run the 1, 4, 10, and 20 session sweep against each app:

```powershell
cd <repo-root>
.\.venv\Scripts\python .\loadtest\concurrency_probe.py --url wss://<voice-live-host>/ws --sessions 1,4,10,20 --turns-file .\loadtest\prompts.example.json --out .\loadtest\results-voice-live.json
.\.venv\Scripts\python .\loadtest\concurrency_probe.py --url wss://<realtime-host>/ws --sessions 1,4,10,20 --turns-file .\loadtest\prompts.example.json --out .\loadtest\results-realtime.json
.\.venv\Scripts\python .\loadtest\concurrency_probe.py --url wss://<voice-agent-host>/ws --sessions 1,4,10,20 --turns-file .\loadtest\prompts.example.json --out .\loadtest\results-voice-agent.json
```

**Checkpoint F**

- [ ] All three probes complete.
- [ ] `ok`, `busy`, and `errors` are recorded separately.
- [ ] p50/p90 TTFA, response time, tokens per turn, and aggregate TPM are captured.
- [ ] Any `busy` count is interpreted against `MAX_CONCURRENT_SESSIONS`.

---

## Part G — Same-model bake-off

Default mode compares each option's recommended default. For an apples-to-apples model run, use `gpt-realtime-2.1-mini` across Voice Live, Realtime, and the Foundry voice agent when region support and Realtime quota allow it:

```powershell
# Voice Live uses the same managed model string.
cd <repo-root>\examples\voice-live-api
azd env set VOICE_LIVE_MODEL gpt-realtime-2.1-mini
azd provision

# Realtime creates or updates its deployment to the same model.
cd <repo-root>\examples\realtime-api
azd env set AZURE_OPENAI_REALTIME_MODEL gpt-realtime-2.1-mini
azd env set AZURE_OPENAI_REALTIME_DEPLOYMENT gpt-realtime-2.1-mini
azd up

# The voice agent stores the managed model on the Foundry agent definition.
cd <repo-root>\examples\foundry-voice-agent
azd env set VOICE_AGENT_MODEL gpt-realtime-2.1-mini
azd provision
azd hooks run postprovision
```

Then repeat Part E and Part F. If Voice Live or voice-agent regional availability blocks `gpt-realtime-2.1-mini`, compare on `gpt-realtime-mini` instead and document the model choice with the results.

**Checkpoint G**

- [ ] All three apps report the intended model in `/api/info`.
- [ ] The same prompts were used for all probes.
- [ ] Results record API, model, region, deployment capacity, and `MAX_CONCURRENT_SESSIONS`.

---

## Part H — Tear down

Run teardown from each example directory:

```powershell
cd <repo-root>\examples\voice-live-api
azd down --purge

cd <repo-root>\examples\realtime-api
azd down --purge

cd <repo-root>\examples\foundry-voice-agent
azd down --purge
```

`--purge` matters because deleted Foundry resources can retain names and quota while soft-deleted.

**Checkpoint H**

- [ ] All resource groups are deleted.
- [ ] Foundry resources are purged.
- [ ] No populated `.env.local`, `.azure\`, or `demo-ids.local.json` file is committed.

---

## Single-page checklist

| Part | What | Done |
|---|---|---|
| A | Verify tools and authenticate to the intended tenant/subscription. | [ ] |
| B | Deploy Voice Live example. | [ ] |
| C | Check Realtime quota and deploy Realtime example. | [ ] |
| D | Deploy Foundry voice agent preview and create the agent version through postprovision. | [ ] |
| E | Smoke test browser, text turn, and tool turn on all three. | [ ] |
| F | Run 1, 4, 10, and 20 session load probes on all three. | [ ] |
| G | Repeat with the same model when quota and region support allow it. | [ ] |
| H | Tear down all environments with `azd down --purge`. | [ ] |

---

*Last updated: 2026-09-25*
