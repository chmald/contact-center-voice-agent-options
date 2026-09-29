# Voice Live API example

This example runs the reusable browser voice-agent UI against Azure Voice Live API through a small FastAPI WebSocket bridge. It is intentionally raw-WebSocket based so it can be compared with the Realtime API example and the Foundry voice-agent preview; for production apps, also evaluate the GA `azure-ai-voicelive` Python SDK.

Architecture: browser -> FastAPI bridge on Azure Container Apps -> Voice Live API.

## Deploy

Use azd 1.30+ and tenant-explicit auth first. Never rely on a bare `az login` or ambient `azd up` context.

```powershell
az login --tenant <TENANT_ID>
az account set --subscription <SUBSCRIPTION_ID>
az account show --query "{tenant:tenantId, subscription:id, user:user.name}" -o table
azd auth login --tenant-id <TENANT_ID>

cd examples\voice-live-api
azd env new <name>
azd env set AZURE_TENANT_ID <TENANT_ID>
azd env set AZURE_SUBSCRIPTION_ID <SUBSCRIPTION_ID>
azd env set AZURE_LOCATION centralus
# Optional preview model:
azd env set VOICE_LIVE_MODEL gpt-realtime-2.1-mini
azd up
azd env get-value SERVICE_WEB_URI
```

Open `SERVICE_WEB_URI` in a browser after `azd up` completes.

## Run locally after provisioning

```powershell
cd examples\voice-live-api
azd env get-values > .env.local
..\..\scripts\run-local.ps1 -Example voice-live-api
```

Local runs use your `az login` identity. The infrastructure grants the deploying principal Voice Live RBAC when `AZURE_PRINCIPAL_ID` is set by azd.

## Switch models

```powershell
azd env set VOICE_LIVE_MODEL gpt-realtime-mini
azd provision
```

Allowed model values are `gpt-realtime-mini` and `gpt-realtime-2.1-mini`.

## Tear down

```powershell
azd down --purge
```

## Foundry project

The Foundry resource is created with project management enabled and a `voice-agents` project (`VOICE_LIVE_PROJECT_NAME`), matching the Realtime and voice agent examples so all three look the same in the Foundry portal. Voice Live still uses managed models, so the project holds no model deployment; the app keeps connecting to `/voice-live/realtime?model=…` on the resource.

## Optional: knowledge base and phone channels

Browser-only by default. To add the synthetic Azure AI Search knowledge base or phone channels (Asterisk over WSS, Twilio, ACS),
see [03 — Optional add-ons](../../docs/03-deployment.md#optional-add-ons-knowledge-base-and-phone-channels). Asterisk in three commands:

```powershell
../../scripts/enable-telephony.ps1 -Example voice-live-api -Providers asterisk   # generates the secrets
azd up
../../scripts/enable-telephony.ps1 -Example voice-live-api -WriteAsteriskConfig  # writes .azure/<env>/asterisk/*.conf
```

## Configuration

| Setting | Default | Notes |
|---|---|---|
| `VOICE_LIVE_ENDPOINT` | provisioned output | `https://<resource>.services.ai.azure.com` |
| `VOICE_LIVE_API_VERSION` | `2026-07-15` | Voice Live GA API version |
| `VOICE_LIVE_MODEL` | `gpt-realtime-mini` | Managed Voice Live model, no deployment needed |
| `VOICE_LIVE_VOICE` | `en-US-Ava:DragonHDLatestNeural` | Azure neural voice or supported OpenAI voice |
| `VOICE_LIVE_TRANSCRIPTION_MODEL` | derived | `gpt-4o-mini-transcribe` for `gpt-realtime-mini`; otherwise `azure-speech` |
| `VOICE_LIVE_TURN_DETECTION` | `azure_semantic_vad` | Also allows `azure_semantic_vad_multilingual`, `server_vad` |
| `VOICE_LIVE_TEMPERATURE` | `0.8` | Must be between `0.6` and `1.2` |
| `MAX_CONCURRENT_SESSIONS` | `20` | Per-replica admission cap |
| `VOICE_LIVE_API_KEY` | empty | Local-only; Bicep disables local auth for deployed resources |

## What's specific to Voice Live

- Endpoint: `wss://<foundry-resource>.services.ai.azure.com/voice-live/realtime?api-version=2026-07-15&model=<model>`.
- Auth: bearer tokens use scope `https://ai.azure.com/.default`; API keys only work when local auth is enabled.
- Session shape: the original flat realtime schema (`modalities`, `input_audio_format`, `turn_detection`, `tools`) rather than the newer OpenAI GA nested schema.
- Voices: Azure neural voices use `{"type":"azure-standard"}`; OpenAI voice names use `{"type":"openai"}`.
- Audio features: Azure semantic VAD, deep noise suppression, and server echo cancellation are enabled by default.
- Models are fully managed by Voice Live; this example creates no model deployment.

See the root README for the three-way comparison, `../../docs/09-environment-variables.md` for settings, `../../docs/06-comparison-one-pager.md` for the two-GA-API deep dive, and sibling examples `../realtime-api/` and `../foundry-voice-agent/`.

*Last updated: 2026-09-29*
