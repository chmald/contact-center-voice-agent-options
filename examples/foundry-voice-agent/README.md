# Foundry voice agent example (public preview)

> **Preview.** Foundry voice agents (announced 2026-09-24) are in **public preview** and are not recommended for production workloads. Use this example to show where a contact-center voice agent can go next; keep production on the Voice Live API or Realtime API examples.

This example runs the same browser UI, bridge, tools, RAG, and phone channels as the other two examples against a **Foundry voice agent**: a Foundry Agent Service agent (`kind: voice`) served by Voice Live in agent mode.

Architecture: browser / ACS call / Twilio call -> FastAPI bridge on Azure Container Apps -> Voice Live agent mode -> Foundry voice agent (managed `gpt-realtime-2.1-mini`).

## What is different from the Voice Live example

| | Voice Live example | This example |
|---|---|---|
| Connection | `.../voice-live/realtime?api-version=2026-07-15&model=<model>` | `.../voice-live/realtime?api-version=2026-07-15&agent-name=<agent>&agent-project-name=<project>` |
| Instructions, tools, voice | Sent by the bridge in every `session.update` | Stored on a **versioned agent** in a Foundry project; the bridge sends only the audio pipeline |
| Where the agent lives | Nowhere - the app is the agent | Foundry project (`accounts/projects`), visible in the Foundry portal with traces, stored transcripts/audio (`store: true`), and evaluations |
| Auth | Entra ID (API key allowed locally) | Entra ID only |
| Model / quota | Managed model, per-resource Voice Live limits | Same: managed model, **no deployment, no Azure OpenAI quota**, per-resource Voice Live limits |
| Tools and RAG | Shared `ToolRegistry` incl. `search_knowledge_base` | Same functions, declared on the agent and executed client-side by the shared bridge |
| Phone | Shared ACS / Twilio adapters | Same shared adapters (Foundry's native Twilio/Teams binding is intentionally not used, to keep all three aligned) |

## Deploy

Tenant-explicit auth first (see the root README). Standalone:

```powershell
cd examples\foundry-voice-agent
azd auth login --tenant-id <TENANT_ID>
azd env new <name>
azd env set AZURE_TENANT_ID <TENANT_ID>
azd env set AZURE_SUBSCRIPTION_ID <SUBSCRIPTION_ID>
azd env set AZURE_LOCATION centralus
# azd env set AZURE_APP_LOCATION eastus2   # when Container Apps is constrained in AZURE_LOCATION
azd up
```

`azd up` provisions the Foundry resource + project, then the `postprovision` hook runs `scripts\create-voice-agent.py`, which creates a new agent version from `config\agent-profile.json` (installing `scripts\requirements-agent.txt` if needed). The deploying user gets the Foundry User role for that step.

Shared single-endpoint mode (same Foundry resource and project as the platform):

```powershell
./scripts/use-shared-platform.ps1 -Example foundry-voice-agent -PlatformEnv <platform-env> -Telephony acs,twilio [-AppLocation eastus2]
cd examples\foundry-voice-agent; azd up
```

After editing `config\agent-profile.json`, re-run `azd hooks run postprovision` (or `python scripts\create-voice-agent.py`) to publish a new agent version; the app picks up the latest version on the next call unless `VOICE_AGENT_VERSION` pins one.

## Configuration

| Setting | Default | Notes |
|---|---|---|
| `VOICE_AGENT_ENDPOINT` | provisioned | `https://<foundry>.services.ai.azure.com` |
| `VOICE_AGENT_PROJECT` | provisioned | Foundry project name holding the agent |
| `VOICE_AGENT_PROJECT_ENDPOINT` | provisioned | Used by the agent-creation hook |
| `VOICE_AGENT_NAME` | `voice-agent-demo` | Agent name |
| `VOICE_AGENT_VERSION` | empty (latest) | Pin an agent version |
| `VOICE_AGENT_MODEL` | `gpt-realtime-2.1-mini` | Managed model; also `gpt-realtime-mini`, `gpt-realtime` |
| `VOICE_AGENT_VOICE` | `en-US-Ava:DragonHDLatestNeural` | Stored on the agent |
| `VOICE_AGENT_API_VERSION` | `2026-07-15` | Voice Live API version used in agent mode |
| `VOICE_AGENT_TURN_DETECTION` | `azure_semantic_vad` | Sent per session |

All common settings (`AZURE_LOCATION`, `AZURE_APP_LOCATION`, `MAX_CONCURRENT_SESSIONS`, telephony, search) are in [docs\09-environment-variables.md](../../docs/09-environment-variables.md).

## Tear down

```powershell
azd down --purge
```

*Last updated: 2026-09-29*
