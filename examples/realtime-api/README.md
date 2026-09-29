# Azure OpenAI GPT Realtime API example

Server-side WebSocket bridge for the Azure OpenAI GPT Realtime API GA surface. It keeps credentials and tools on the server; for production browser audio, prefer WebRTC with `POST https://<resource>.openai.azure.com/openai/v1/realtime/client_secrets`, then `/openai/v1/realtime/calls`.

## 1. Tenant-explicit auth

Never rely on ambient Azure CLI state:

```powershell
az login --tenant <TENANT_ID>
az account set --subscription <SUBSCRIPTION_ID>
az account show --query "{tenant:tenantId, subscription:id, name:name, user:user.name}" -o table
azd auth login --tenant-id <TENANT_ID>
```

## 2. Pre-flight quota check

Use a Global Standard realtime region: `canadacentral`, `centralus`, `eastus2`, `francecentral`, `swedencentral`, or `southindia`.

```powershell
az cognitiveservices usage list -l <region> -o table
# After provisioning, inspect available model deployments:
az cognitiveservices account list-models -n <account> -g <resource-group> -o table
```

Look for the realtime model's GlobalStandard quota row. The row is named `Requests Per Minute - <model> - GlobalStandard`; `REALTIME_DEPLOYMENT_CAPACITY` (default `10`) consumes those RPM units. The `preprovision` hook runs `scripts\check-realtime-quota.ps1` and stops with the value to set if it would exceed what is available.

## 3. Deploy

```powershell
cd examples\realtime-api
azd env new <environment-name>
azd env set AZURE_TENANT_ID <TENANT_ID>
azd env set AZURE_SUBSCRIPTION_ID <SUBSCRIPTION_ID>
azd env set AZURE_LOCATION centralus
# Optional:
azd env set AZURE_OPENAI_REALTIME_MODEL gpt-realtime-mini
azd env set REALTIME_DEPLOYMENT_CAPACITY <n>
azd up
```

`azd` uses ACR remote build (`docker.remoteBuild: true`), so a local Docker daemon is not required.

## 4. Local run

```powershell
azd env get-values > .env.local
..\..\scripts\run-local.ps1 -Example realtime-api
```

The included infrastructure disables local auth, so local runs use Entra ID unless you point at a separate key-enabled resource and set `AZURE_OPENAI_API_KEY`.

## 5. Optional transcription opt-in

Input transcription requires its own Azure model deployment and quota. Deploy a transcription model in the Foundry portal, then set:

```powershell
az containerapp update -n <app> -g <resource-group> --set-env-vars REALTIME_TRANSCRIPTION_DEPLOYMENT=<deployment-name>
```

For an infrastructure-managed setting, add the env var to `infra\modules\resources.bicep` and redeploy.

## 6. Model switch

Default: `gpt-realtime-2.1-mini` version `2026-07-07`.

```powershell
azd env set AZURE_OPENAI_REALTIME_MODEL gpt-realtime-mini
azd env set REALTIME_DEPLOYMENT_CAPACITY <n>
azd up
```

`gpt-realtime-mini` uses version `2025-12-15`.

## 7. Teardown

```powershell
azd down --purge
```

`--purge` matters because soft-deleted Foundry resources retain names and quota until purged.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `AZURE_OPENAI_ENDPOINT` | required | `https://<resource>.openai.azure.com` |
| `AZURE_OPENAI_REALTIME_DEPLOYMENT` | `gpt-realtime-2.1-mini` | Deployment name used in the GA `model=` query |
| `AZURE_OPENAI_REALTIME_MODEL` | deployment name | Display label only |
| `REALTIME_VOICE` | `marin` | One of alloy, ash, ballad, coral, echo, sage, shimmer, verse, marin, cedar |
| `REALTIME_TURN_DETECTION` | `semantic_vad` | `semantic_vad` or `server_vad` |
| `REALTIME_NOISE_REDUCTION` | `near_field` | `near_field`, `far_field`, or `none` |
| `REALTIME_TRANSCRIPTION_DEPLOYMENT` | empty | Optional input transcription deployment |
| `AZURE_OPENAI_TOKEN_SCOPE` | `https://ai.azure.com/.default` | Override only if your tenant requires the legacy scope |
| `AZURE_OPENAI_API_KEY` | empty | Local-only key auth when the target resource permits keys |

## What's specific to the Realtime API

- GA endpoint: `/openai/v1/realtime?model=<deployment>`, with no `api-version`.
- No `OpenAI-Beta` header.
- The deployment is created and sized in this example; insufficient subscription quota fails deployment.
- `session.update` uses the GA nested audio schema and `max_output_tokens`.
- Assistant transcripts arrive without input transcription; input transcription is optional and separately deployed.

See the root README for the three-way comparison, `../../docs/09-environment-variables.md` for settings, `../../docs/06-comparison-one-pager.md` for the two-GA-API deep dive, and sibling examples `../voice-live-api/` and `../foundry-voice-agent/`.

*Last updated: 2026-09-29*
