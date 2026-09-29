# Changelog — Voice Live API vs. GPT Realtime API

Change history for the reusable demo pattern. Entries are newest-first.

---

## [1.2.0] - 2026-09-29

### Added

- **Third example: `examples\foundry-voice-agent\` (Foundry voice agents, public preview, announced 2026-09-24).** A Foundry Agent Service agent (`kind: voice`) on managed `gpt-realtime-2.1-mini`, served by Voice Live in agent mode (`agent-name` / `agent-project-name` query parameters, the same ones the `azure-ai-voicelive` SDK sends). `VoiceAgentBridge` reuses the shared bridge, so browser, ACS, Twilio, metrics, admission control, and the load probe are identical across all three examples.
- Agent as code: `scripts\create-voice-agent.py` builds a `VoiceAgentDefinition` from `config\agent-profile.json` (instructions, function tools, voice, `store: true`) and creates a new agent version with `azure-ai-projects` 2.7.0; run by the example's `postprovision` hook (`hooks\postprovision.ps1`).
- RAG and tools stay shared: the agent declares the same function tools, which are executed client-side by the shared bridge, so `search_knowledge_base` behaves the same in all three examples. Foundry's native Twilio/Teams phone binding is deliberately not used, to keep telephony aligned.
- Platform: the shared Foundry resource now has `allowProjectManagement` + system identity and a `voice-agents` project (`SHARED_FOUNDRY_PROJECT`), so all three examples run on one endpoint.
- Root README: three-way comparison (status, where the agent lives, deployment vs managed model, quota model, protocol, auth, telephony, extras, when to choose).
- `docs\09-environment-variables.md`: every deploy-time and runtime variable, with a capacity-constraint section (`AZURE_APP_LOCATION`, `REALTIME_DEPLOYMENT_CAPACITY`).
- Doc 07: Voice Live and the voice agent **share** the resource's per-resource Voice Live limits in shared mode; Realtime quota is separate.
- Tests: agent-mode URL/auth/session contract, agent function call answered by the shared RAG tool, agent definition built from the profile and accepted by the SDK model, infra contract (84 tests).

### Docs refreshed for three options

- 00 (new Part D + three-app smoke/load/teardown), 01 (architecture, differences table, decisions), 02 (voice-agent RBAC/region/quota), 03 and 03b (IaC + manual voice-agent deployment), 04 (bake-off rows E-F, capacity math, walkthrough), 05 (postprovision, agent-mode connection/session errors, shared-limit throttling, hook-path error), 06 (now the two-GA-API deep dive with a preview section; PDF left at the 2026-09-25 two-API version), HTML one-pager, architecture .drawio (third app path), example READMEs, loadtest README, and docstrings.

### Known gaps

- Not yet deployed live. Region support for voice agents requires both Agent Service and Voice Live; re-check before use.
- Session-level audio settings in agent mode follow the Voice Live agent sample; confirm on first live run that the service accepts them alongside the agent definition.

---
## [1.1.0] - 2026-09-28

### Added

- **Shared single-endpoint platform** (`platform\`, infra-only azd project): one Foundry `AIServices` endpoint (`disableLocalAuth`) with one Global Standard realtime deployment, Azure AI Search (Basic, semantic ranker free tier, key auth disabled), and Azure Communication Services. Default region `centralus`.
- **Shared mode** for both examples (`SHARED_RESOURCE_GROUP` + `SHARED_FOUNDRY_NAME`): the app skips its own Foundry resource/deployment and a `shared-access.bicep` module grants its managed identity the API role on the shared endpoint, Search Index Data Reader on the index, and Contributor on ACS. Standalone mode is unchanged when these are empty.
- **Telephony adapters** (`shared\voiceagent_core\telephony\`), enabled with `TELEPHONY_PROVIDERS`:
  - ACS Call Automation: Event Grid `IncomingCall` webhook, answer with bidirectional WebSocket media streaming in `pcm24KMono`, `StopAudio` on barge-in, overflow redirect or busy reject.
  - Twilio Media Streams: signed `/telephony/twilio/voice` TwiML webhook (numbers and SIP Domains, so a PBX can route to the agent), mu-law 8 kHz ↔ PCM16 24 kHz conversion, `clear` on barge-in, busy `<Say>` + `<Dial>` overflow.
  - Short-lived purpose-bound HMAC tokens for media/stream URLs, call-length tokens for ACS callbacks, a separate `ACS_EVENTGRID_SECRET` for the Event Grid endpoint (distinct from the token signing key), `X-Twilio-Signature` validation, and a handshake timeout + cap on unauthenticated Twilio sockets.
  - Atomic slot reservation at call arrival, claimed when media connects (expires after 30 s; released on answer failure).
- **RAG tool**: `knowledge_search` handler and `search_knowledge_base` profile tool — Azure AI Search (managed identity, keyword + semantic, optional integrated-vectorizer text query) or local `config\knowledge-base.json`. Works on every channel through the shared tool path.
- `AZURE_APP_LOCATION` (`appLocation`): deploy Container Apps, ACR, Log Analytics, and the app identity to a different region than the AI endpoint when Container Apps capacity is constrained (e.g. keep AI in `centralus`, apps in `eastus2`). `use-shared-platform.ps1 -AppLocation` validates the region offers Container Apps.
- `SessionHub`: one admission counter across browser and phone sessions; session logs now carry `channel`.
- Scripts: `use-shared-platform.ps1`, `configure-telephony.ps1` (tenant/subscription check before acting), `load-knowledge-index.py`.
- Docs: `docs\07-telephony-and-shared-endpoint.md`, including a side-by-side **Voice Live vs Realtime quota and limits** table (Voice Live native models are not a deployment and use per-resource limits; Realtime uses deployment quota in a subscription-level pool). `02-prerequisites` and `06-comparison-one-pager` now note the Voice Live TPM formula (TPM = NCPM × 4,000) and Learn's inconsistent 100-NCPM/120K-TPM defaults.
- Tests: telephony audio/security/settings, ACS and Twilio adapters, shared admission, RAG backends, platform/shared-mode infra contract, and an end-to-end Twilio → Realtime bridge → fake upstream call with a RAG tool round-trip, plus reservation/cleanup/token-purpose regression tests (73 tests).

### Changed

- **Realtime capacity default 100 → 10** (example and platform). Realtime Global Standard quota is counted in RPM units (`Requests Per Minute - <model> - GlobalStandard`), and new subscriptions commonly have 10; the old default failed ARM preflight with `InsufficientQuota`. New `preprovision` hook (`hooks\preprovision.ps1` in each project, a wrapper because azd rejects hook paths outside the project folder, calling `scripts\check-realtime-quota.ps1`) compares `REALTIME_DEPLOYMENT_CAPACITY` with available quota (adding back an existing deployment's capacity on re-provision) and stops early with the value to set.

- Foundry role-assignment resource names in both examples now derive from the resource group + resource name (needed for the conditional Foundry resource). Existing standalone deployments get new assignments on the next `azd up`; remove the old duplicates if desired.
- Agent instructions now tell the model to call `search_knowledge_base` before answering how-to or policy questions.
- New runtime dependencies: `numpy`, `azure-communication-callautomation`, `python-multipart`.

### Known gaps

- Not yet exercised against live ACS/Twilio calls or a live deployment.
- No automated phone-call load generator; scale testing still uses the browser/probe sweep.

---

## [1.0.0] - 2026-09-25

### Shipped

- Two side-by-side browser voice-agent examples:
  - `examples\voice-live-api\` targets Azure AI Voice Live API with default `gpt-realtime-mini`.
  - `examples\realtime-api\` targets Azure OpenAI GPT Realtime API GA with default `gpt-realtime-2.1-mini`.
- Shared browser client, FastAPI app factory, `RealtimeStyleBridge` base class, server-side tool registry, app-side metrics, admission control, and config-driven agent profile.
- `azd` deployment for each example to Azure Container Apps with ACR remote build, Log Analytics, a user-assigned managed identity, Foundry `AIServices` resource, `disableLocalAuth: true`, and API-specific RBAC.
- Realtime example model deployment for `gpt-realtime-2.1-mini` or `gpt-realtime-mini`, with `REALTIME_DEPLOYMENT_CAPACITY` defaulting to `100`.
- Load probe at `loadtest\concurrency_probe.py` for concurrent text turns and p50/p90 TTFA, response time, token, and busy-count measurements.
- Reusability guard tests that keep domain terms out of shared code and verify retargeting through config/data instead of code edits.
- Core narrative docs: README, changelog, reproduction orchestrator, architecture, and prerequisites.

### Verification record

Claims in the v1 docs were checked against the provided 2026-09-25 research bundle and the actual repo code. Source URLs used as citations include:

| Claim area | Source URL |
|---|---|
| Voice Live GA API version, endpoint, session schema, events | https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live-api-reference-2026-07-15 |
| Voice Live release notes and SDK default API version | https://learn.microsoft.com/en-us/azure/ai-services/speech-service/releasenotes |
| Voice Live model list, tier mapping, pricing structure | https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live |
| Voice Live limits | https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-services-quotas-and-limits?tabs=voice-live |
| Voice Live regions tab | https://learn.microsoft.com/en-us/azure/ai-services/speech-service/regions?tabs=voice-live |
| Voice Live pricing page | https://azure.microsoft.com/en-us/pricing/details/cognitive-services/speech-services/ |
| Realtime API GA endpoint, no `api-version`, transport guidance | https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/realtime-audio |
| Realtime WebRTC client-secrets path and GA v1 samples | https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/realtime-audio-webrtc |
| Realtime model lifecycle and retirement schedule | https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule |
| Realtime region availability and PTU gap | https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability |
| Realtime quotas and limits | https://learn.microsoft.com/en-us/azure/foundry/openai/quotas-limits |
| Realtime quota management | https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/quota |
| Realtime pricing page | https://azure.microsoft.com/en-us/pricing/details/cognitive-services/openai-service/ |
| Azure built-in AI roles | https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles/ai-machine-learning |
| Cognitive Services account/deployment Bicep schema | https://learn.microsoft.com/en-us/azure/templates/microsoft.cognitiveservices/accounts |
| Container Apps ingress | https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview |
| Container Apps managed environment schema | https://learn.microsoft.com/en-us/azure/templates/microsoft.app/managedenvironments |
| Container Apps app schema | https://learn.microsoft.com/en-us/azure/templates/microsoft.app/containerapps |
| ACR role GUID | https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles/containers |
| `azd` schema and tenant-explicit auth flags | https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/azd-schema |

The code reconciliation pass used the actual `shared\`, `config\`, `loadtest\`, `scripts\run-local.ps1`, `.github\workflows\ci.yml`, `demo-ids.template.json`, `.gitignore`, `.dockerignore`, and both `examples\*\` folders. The docs reflect the code's current Bicep API versions, env vars, azd parameter names, role GUIDs, outputs, and default values.

### Corrections made during research and review

- Voice Live GA `api-version` is `2026-07-15`, not `2025-10-01`.
- Azure AI User was renamed **Foundry User**; the role GUID remains `53ca6127-db72-4b80-b1b0-d745d6d5456d`.
- Voice Live uses the flat session schema (`modalities`, `voice`, `input_audio_format`, `turn_detection`), not the OpenAI GA nested schema.
- Realtime GA v1 uses `/openai/v1/realtime?model=<deployment-name>` and takes no `api-version`.
- `az cognitiveservices model list` does not exist; use `az cognitiveservices usage list`, `az cognitiveservices account list-models`, and deployment list commands instead.
- `gpt-realtime-mini` retirement rows conflict in the live retirement schedule; plan against the earlier date until Microsoft corrects the page.
- No PTU or Provisioned deployment path was found for realtime models in the verified region matrix.
- Realtime input transcription requires its own Azure model deployment and quota because the GA Azure schema resolves the transcription `model` as a deployment name.
- Accelerator guidance was corrected:
  - Voice Live accelerator is useful for managed identity, production SDK posture, and audio defaults, but carries telephony scope and a cascaded-model default outside this minimal comparison.
  - Realtime accelerator is stale for GA Realtime because it uses preview endpoint/schema/events, no native `azd` Container Apps service block, telephony dependencies, and incomplete barge-in truncation.
- The shared bridge fixed the tool-call follow-up timing bug: `response.create` is sent only after the function-call response's `response.done`, avoiding `conversation_already_has_active_response`.
- End-to-end smoke testing (real `uvicorn` app, fake upstream, load probe) found a second instance of the same conflict: a turn typed while the greeting was still playing sent a second `response.create`. The bridge now treats it as barge-in. It sends `response.cancel`, emits a new `interrupted` browser message so playback flushes, drops the cancelled audio, and creates the new response on the cancelled `response.done`. Benign `response_cancel_not_active` errors are no longer shown to the user.
- The load probe now waits for the greeting to finish before timing turn 1, so greeting audio and metrics can't be attributed to the first scripted turn.
- The fake upstream now keeps per-connection response state (so concurrent probe sessions don't interfere) and honors `response.cancel`. New regression tests cover typed barge-in during the greeting and an end-to-end probe run with admission control (2 ok + 1 busy at a cap of 2).
- Review fixes before publishing:
  - The web client now streams assistant transcript deltas into one bubble instead of one bubble per delta.
  - The capture worklet is connected to the audio graph so every browser processes it.
  - `AudioContext` is closed on stop.
  - The container apps depend on the AcrPull role assignment, and the Realtime container app also depends on its model deployment.
  - The Azure voice temperature is fixed, independent of the model sampling temperature.
  - `demo-ids.template.json` now lists capacity units, not "KTPM".
- Bicep API versions were pinned down from `2026-07-01`-era resource-provider versions because local Bicep 0.43.8 emits `BCP081`; current templates build cleanly with Cognitive Services `2025-06-01`, App `2025-07-01`, Log Analytics `2025-02-01`, ACR `2025-11-01`, Managed Identity `2024-11-30`, and role assignments `2022-04-01`.

### Known gaps

- Voice Live dollar pricing is not quoted. The pricing page confirms the Basic/Pro/Lite token-billing structure, but exact values were not extractable from the static page in the verified research.
- Realtime TPM-per-capacity-unit ratio is undocumented for the realtime family; confirm in Foundry quota before raising `REALTIME_DEPLOYMENT_CAPACITY`.
- `disableLocalAuth` compatibility for these data-plane calls is inferred from reference implementations and supported Entra auth paths, not from an explicit sentence in the Learn pages.
- `gpt-realtime-2.1-mini` Voice Live regional availability is preview and should be checked at deployment time in the Voice Live regions tab.
- Data Zone Standard availability conflicts: pricing meters exist for realtime 2.1-family Data Zone SKUs, while the region-availability page shows no realtime Data Zone rows.
- Docker was not built locally (no local Docker daemon during authoring); the intended path is ACR remote build through `docker.remoteBuild: true`. The Dockerfile `COPY` sources are guarded by tests, and both apps were smoke-tested as real `uvicorn` processes against a fake upstream.
- Neither example has been deployed to a live Azure subscription as part of v1.0.0. The first live `azd up` of each example is the remaining validation step.

---

*Last updated: 2026-09-25*
