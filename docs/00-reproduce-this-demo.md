# 00 — Reproduce this demo: one shared resource, three ways to connect

Recommended path: deploy **one shared Foundry resource and three app instances**, with a Search-backed knowledge base and optional ACS, Twilio, and Asterisk phone channels, from a clean clone. Use `scripts\demo.ps1` for deployment and teardown; the per-example standalone procedure remains an explicit alternative below.

> **Time budget.** Allow roughly **75–110 minutes** for first-time deployment and validation; capacity, provider registration, phone-number acquisition, and external PBX/provider setup can add time. The wrapper does not remove those prerequisites.

---

## What you end up with

![Shared platform plus three app tiers, with AI and app regions independently selected](./assets/diagrams/04-deployment-and-regions.png)

**Diagram scope: the recommended shared deployment.** `platform\` owns one Foundry resource, a realtime model deployment, a voice-agent project, separate Azure AI Search, and ACS only when selected. Three Container Apps keep their own ACR, Log Analytics, managed identity, and admission counter. Shared means one Foundry resource with **distinct API hosts/routes**, not one WebSocket URL or one quota pool. Voice Live and the voice agent share Voice Live limits; Realtime uses deployment quota.

Use `centralus`, `eastus2`, or `swedencentral` for the cleanest same-region comparison; re-check that the region supports both Agent Service voice agents and Voice Live before using the preview voice-agent example.

The wrapper always loads **40 articles** into the platform's Search index. The **30 request records** remain local for `record_lookup`. **Do not deploy `knowledge\` separately in shared mode.** For independent Foundry resources, use the standalone Parts A–D2 instead of the shared steps below.

---

## Prerequisites checklist

Full detail is in [02-prerequisites.md](./02-prerequisites.md).

- [ ] Azure CLI installed and signed into the intended tenant only after explicit tenant selection.
- [ ] `azd` 1.30+ installed.
- [ ] Bicep 0.43+ available through Azure CLI.
- [ ] Python 3.12+ available.
- [ ] PowerShell 7 available for `scripts\demo.ps1` and the helper scripts.
- [ ] Modern browser with microphone permissions.
- [ ] Subscription permission: Contributor plus User Access Administrator, or Owner.
- [ ] Resource providers registered: `Microsoft.App`, `Microsoft.CognitiveServices`, `Microsoft.ContainerRegistry`, `Microsoft.OperationalInsights`, `Microsoft.ManagedIdentity`, `Microsoft.Search`; also `Microsoft.Communication` and `Microsoft.EventGrid` when using ACS.
- [ ] Realtime quota checked in the target region; the platform owns the pre-flight in shared mode.
- [ ] Deployer will receive Foundry User on the Foundry resource before the voice-agent postprovision hook creates an agent version.

---

## Recommended shared path — deploy all three and set up phones

### S1. Install local dependencies before Up

From the repo root, with Python **3.12+**:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r scripts\requirements-agent.txt
```

The wrapper selects `.venv/Scripts/python.exe`, then `.venv/bin/python`, otherwise `python`. On non-Windows hosts use `.venv/bin/python -m pip install -r scripts/requirements-agent.txt`. `azure-identity` is needed to load Search; `azure-ai-projects` is needed to create the agent. This setup is separate from the offline preview and is not performed by `-WhatIf`.

### S2. Preview, then deploy

```powershell
$Demo = @{
        DemoName = "voice-demo"
        TenantId = "<tenant-guid>"
        SubscriptionId = "<subscription-guid>"
}

./scripts/demo.ps1 -Action Up @Demo -Location centralus -AppLocation eastus2 -RealtimeCapacity 10 -Telephony 'acs,twilio,asterisk' -WhatIf
./scripts/demo.ps1 -Action Up @Demo -Location centralus -AppLocation eastus2 -RealtimeCapacity 10 -Telephony 'acs,twilio,asterisk'
```

Choose only the phone providers you need; omitting `-Telephony` enables none. `-Location` defaults to `centralus` and allows `centralus`, `eastus2`, or `swedencentral`. Omit `-AppLocation` to use the AI region; the example explicitly uses `eastus2` for the app tier. Realtime capacity defaults to `10`; this first-time path retains the repo's existing model defaults.

`-WhatIf` is an **offline order/target preview**, not ARM what-if: it makes no CLI calls, cloud calls, or file changes. Actual `Up`:

1. Authenticates `az` and `azd` with the explicit tenant and checks subscription/tenant context. `-SkipLogin` skips sign-in, **not** the `az` context check.
2. Creates the named platform environment, provisions Foundry + realtime deployment + project + **Search always**, and ACS only if `acs` was selected; loads 40 articles.
3. Creates the three named app environments, wires each with the existing shared-platform helper, runs an **ARM preview then `azd up` sequentially** for Voice Live, Realtime, and the voice agent. The voice-agent postprovision hook creates an agent version.
4. Configures selected phones, checks `/healthz` and `/api/info` for backend/provider configuration, and prints **three app URLs**. These HTTP checks do **not** test upstream audio or real calls.

| Project | Named environment | Owned resource group |
|---|---|---|
| `platform\` | `<DemoName>-platform` | `rg-<DemoName>-platform` |
| `examples\voice-live-api\` | `<DemoName>-vl` | `rg-<DemoName>-vl` |
| `examples\realtime-api\` | `<DemoName>-rt` | `rg-<DemoName>-rt` |
| `examples\foundry-voice-agent\` | `<DemoName>-agent` | `rg-<DemoName>-agent` |

**Ownership and resume.** `DemoName` must be 3–20 lowercase letters/digits/hyphens, start with a letter, and end alphanumeric. The gitignored, nonsecret `.azure/demos/<DemoName>.json` records context/ownership; each project also keeps its `.azure/<env>/.env` (which can contain secrets). The wrapper refuses to adopt pre-existing environments/resource groups and refuses tenant/location/provider drift on rerun. Resume with the **same Up arguments** after fixing a failure; existing env values are used, but naming settings are immutable. **No automatic rollback:** completed stages persist and cost money until you tear them down. Full parameter contract: [03 — Deployment](03-deployment.md#recommended-shared-deploy-all).

### S3. Complete the phone-provider handoff

- **Asterisk:** `Up -Telephony asterisk` (or the combined selection above) writes configs for all three apps under `examples/<example>/.azure/<env>/asterisk/`, using extensions **7001** (Voice Live), **7002** (Realtime), **7003** (voice agent). Install/configure the external PBX and copy/merge the generated files yourself; they contain secrets.
- **Twilio:** missing auth tokens are **securely prompted**, not command-line arguments; existing secrets are kept. The wrapper prints all three **HTTP POST** webhooks. Configure the Twilio number or SIP Domain yourself in Twilio Console; one number has one app target at a time.
- **ACS:** acquire a number separately on the provisioned ACS resource (**paid step**). Routing is skipped until `-AcsPhoneNumber` is supplied. Then run:

```powershell
./scripts/demo.ps1 -Action Phones @Demo -PhoneTarget foundry-voice-agent -AcsPhoneNumber '+<E164-number>'
```

`Phones` inherits providers from the manifest and reruns routing/config generation without `azd up`; omit Up-only region/provider/capacity/overflow options. `-PhoneTarget` defaults to `foundry-voice-agent`, alternatively `voice-live-api` or `realtime-api`. The stable Event Grid subscription **`incoming-demo`** belongs to this demo's ACS resource and targets that app: **one number, one app**. Older manually created subscriptions are not automatically deleted; inspect duplicate number filters before calling. An optional `-OverflowNumber +E164` on **Up** sets the ACS/Twilio fallback; Asterisk fallback belongs in your dialplan. See [07 — Phone setup and testing](07-telephony-and-shared-endpoint.md#recommended-wrapper-phone-setup).

**Shared checkpoint**

- [ ] Four owned environments, one shared Foundry resource, and three app URLs are recorded.
- [ ] `/api/info` reports the intended backend, `knowledge: azure-ai-search:knowledge`, and selected phone providers on all three apps.
- [ ] Provider/PBX setup is completed manually; real phone calls and browser turns are tested in Part E.
- [ ] Skip standalone Parts A–D2; proceed to Part E. Use the **shared** teardown in Part H.

---

## Standalone alternative — Parts A–D2

These steps create separate Foundry resources. **Do not run them after shared deploy-all.** Install the local dependencies from S1 first; use fresh standalone environment names.

## Part A — Tools and tenant auth (standalone)

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

## Part B — Deploy the Voice Live example (standalone)

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

## Part C — Deploy the Realtime example (standalone)

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

The default model is `gpt-realtime-2.1-mini` version `2026-07-07`, deployment name `gpt-realtime-2.1-mini`, and `REALTIME_DEPLOYMENT_CAPACITY=10` (capacity units (for `gpt-realtime-2.1-mini`, 1 unit = 10,000 TPM + 20 RPM, so the default 10 = 100K TPM / 200 RPM; the portal shows the same value as TPM); the `preprovision` hook checks it against available quota).

**Checkpoint C**

- [ ] Quota check completed before deployment.
- [ ] `azd up` completes.
- [ ] `SERVICE_WEB_URI` is present in `azd env get-values`.
- [ ] Browser opens the app and `/api/info` shows `Realtime API`.
- [ ] A model deployment exists on the Foundry resource.

---

## Part D — Deploy the Foundry voice agent example (standalone, preview)

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

## Part D2 — Standalone only: optional knowledge base and phone channels

Shared deployment already provides Search and selected phone channels; **skip this entire part** on that path. For standalone examples, skip it if using local knowledge/browser only. Details and every setting: [03 — Optional add-ons](03-deployment.md#optional-add-ons-knowledge-base-and-phone-channels). Authenticate and create/configure the separate knowledge environment as described in [10 — Knowledge base](10-knowledge-base.md) before its `azd up`.

```powershell
# Knowledge base (Azure AI Search + 40 synthetic articles), then point an example at it
cd knowledge; azd up; cd ..
./scripts/use-knowledge-base.ps1 -Example foundry-voice-agent -KnowledgeEnv <kb-env>

# Asterisk over WSS: generate TELEPHONY_WEBHOOK_SECRET + ASTERISK_WEBSOCKET_SECRET, deploy, write Asterisk config
./scripts/enable-telephony.ps1 -Example foundry-voice-agent -Providers asterisk
cd examples\foundry-voice-agent; azd up; cd ..\..
./scripts/enable-telephony.ps1 -Example foundry-voice-agent -WriteAsteriskConfig
```

Checkpoint:

- [ ] `/api/info` shows `knowledge: azure-ai-search:knowledge` (if the knowledge base was added).
- [ ] `/api/info` shows `telephony: ["asterisk"]` and `scripts\probe-asterisk.py` gets agent audio back.

---

## Part E — Smoke test all three apps

Run these checks against each `SERVICE_WEB_URI`: Voice Live, Realtime API, and Foundry voice agent.

### E1. Browser voice turn

1. Open the app.
2. Select **Start** and allow microphone access.
3. Speak a short greeting.
4. Confirm assistant audio plays back.

### E2. Text turn

Type a short non-tool question such as:

```text
Give me a one-sentence greeting.
```

### E3. Tool turn

Open `config\sample-data.json`, choose one sample record ID, and ask for its status through the browser text box. This confirms the server-side tool path without hardcoding a record value in the docs.

**Checkpoint E**

- [ ] If phone channels were enabled, a real call exercises audio, RAG, barge-in, and overflow on each target; follow [07 — Test plan](07-telephony-and-shared-endpoint.md#test-plan). GET health/info alone is not an upstream or phone test.
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

This is an advanced manual operation beyond the wrapper's first-time default-model path. The commands below are for **standalone** environments. In shared mode, the realtime model/deployment/capacity belongs to `platform\`; change it there and rewire the apps rather than trying to create a deployment in the Realtime app environment. Keep the wrapper's naming, tenant, location, and provider settings immutable.

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

### Shared deployment (recommended path)

From the repo root, use the same demo name, tenant, and subscription; no need to repeat regions/providers:

```powershell
./scripts/demo.ps1 -Action Down @Demo -WhatIf
./scripts/demo.ps1 -Action Down @Demo
```

`Down` displays the **four scoped resource groups** and asks for confirmation, then deletes **agent → Realtime → Voice Live → platform**. `-Force` explicitly opts into unattended confirmation. `-Purge` is a **separate, irreversible opt-in** that passes `--purge` to `azd`; it does not guarantee every soft-deleted Cognitive Services account is purged. The offline `-WhatIf` preview deletes or changes nothing.

Local manifest/env files are retained for retries and audit; after full teardown, use a **new DemoName**. The wrapper never removes `knowledge\` or unrelated environments. Clean up external Twilio/PBX settings, phone numbers, and ongoing provider billing yourself.

### Standalone alternative only

Select the intended standalone environment in each example directory before teardown:

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

Only add `--purge` if you deliberately want irreversible purge behavior. Check soft-deleted Cognitive Services accounts separately rather than assuming `azd` purged them. If you separately deployed `knowledge\`, select and tear down that specific environment yourself.

**Checkpoint H**

- [ ] Only the intended demo resource groups are deleted.
- [ ] Any retained soft-deleted resources and external phone/provider billing are reviewed.
- [ ] Shared local ownership/env state is retained for retries/audit, with a new name planned for the next full build.
- [ ] No populated `.env.local`, `.azure\`, or `demo-ids.local.json` file is committed.

---

## Single-page checklist

| Part | What | Done |
|---|---|---|
| S1–S2 | Recommended: install dependencies, preview, then deploy platform/Search + all three apps with explicit tenant/subscription. | [ ] |
| S3 | Complete selected phone-provider/PBX setup; acquire ACS number separately and run `Phones` if needed. | [ ] |
| A–D2 | **Alternative only:** standalone deployments and optional separate knowledge/phone setup, instead of S2–S3. | [ ] |
| E | Smoke test browser, text turn, and tool turn on all three. | [ ] |
| F | Run 1, 4, 10, and 20 session load probes on all three. | [ ] |
| G | Repeat with the same model when quota and region support allow it. | [ ] |
| H | Shared: scoped `Down`; standalone: selected per-example teardown. Purge is a separate opt-in; clean up external phone billing. | [ ] |

---

*Last updated: 2026-09-30 (local documentation revision)*
