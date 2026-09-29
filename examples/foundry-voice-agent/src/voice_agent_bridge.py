"""Foundry voice agent (preview) bridge specifics.

A Foundry voice agent is a Foundry Agent Service agent (``kind: voice``). The default
route is the project-scoped endpoint used by the Foundry portal sample (verified live
2026-09-29: greeting, tool call, and spoken answer all work):

``wss://<foundry>.services.ai.azure.com/api/projects/<p>/agents/<a>/endpoint/protocols/voice?api-version=2025-11-15-preview``
with the ``Foundry-Features: VoiceAgents=V1Preview`` header.

``VOICE_AGENT_ROUTE=voice-live`` keeps the older Voice Live agent-mode route. For
``kind: voice`` agents it currently fails server-side ("Session configuration failed
after 5 attempts ... invalid_session_update_message", close 1008) even when the client
sends nothing, so it is kept only for classic agent-mode experiments:

``wss://<foundry>.services.ai.azure.com/voice-live/realtime?api-version=<v>&agent-name=<a>&agent-project-name=<p>``

(the same query parameters the ``azure-ai-voicelive`` SDK builds from
``connect(agent_name=..., project_name=...)``).

Differences from the Voice Live example:

- The agent version owns **instructions, tools, voice, greeting, the audio pipeline
  (turn detection, noise suppression, echo cancellation, transcription), and storage**.
  They are created from ``config/agent-profile.json`` by ``scripts/create-voice-agent.py``.
- The bridge therefore sends **no session.update and no greeting** by default: Agent
  Service rejects ``response.create`` with ``instructions`` ("Overriding instructions in
  response.create is not supported with Agent service"), and the portal sample sends no
  session configuration. ``VOICE_AGENT_SEND_SESSION_CONFIG=true`` re-enables an audio-only
  session.update for experiments.
- Function tools on the agent are **client-executed**: the model emits the same
  ``response.function_call_arguments.done`` event and the shared bridge answers it
  through the shared ``ToolRegistry`` - including the shared ``search_knowledge_base``
  RAG tool - on every channel (browser, ACS, Twilio).
- Agent mode supports Microsoft Entra ID only; there is no API-key path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from voiceagent_core.auth import TokenProvider, build_auth_headers
from voiceagent_core.bridge import RealtimeStyleBridge
from voiceagent_core.metrics import SessionMetrics
from voiceagent_core.profile import AgentProfile
from voiceagent_core.tools import ToolRegistry

VOICE_AGENT_SCOPE = "https://ai.azure.com/.default"
DEFAULT_API_VERSION = "2026-07-15"
DEFAULT_AGENT_NAME = "voice-agent-demo"
DEFAULT_PROJECT_ROUTE_API_VERSION = "2025-11-15-preview"
FOUNDRY_FEATURES_HEADER = {"Foundry-Features": "VoiceAgents=V1Preview"}
ROUTES = {"voice-live", "project"}
TURN_DETECTION_TYPES = {"azure_semantic_vad", "azure_semantic_vad_multilingual", "server_vad"}
NATIVE_TRANSCRIPTION_MODELS = {"gpt-realtime", "gpt-realtime-mini"}


@dataclass(frozen=True)
class VoiceAgentSettings:
    """Environment-backed settings for the Foundry voice agent example."""

    endpoint: str
    project_name: str
    agent_name: str = DEFAULT_AGENT_NAME
    agent_version: str | None = None
    api_version: str = DEFAULT_API_VERSION
    model_label: str = "gpt-realtime-2.1-mini"
    voice_label: str = "en-US-Ava:DragonHDLatestNeural"
    turn_detection: str = "azure_semantic_vad"
    transcription_model: str | None = None
    route: str = "project"
    project_route_api_version: str = DEFAULT_PROJECT_ROUTE_API_VERSION
    send_session_config: bool = False

    def __post_init__(self) -> None:
        if self.route not in ROUTES:
            raise ValueError(f"VOICE_AGENT_ROUTE must be one of: {', '.join(sorted(ROUTES))}")
        if self.turn_detection not in TURN_DETECTION_TYPES:
            allowed = ", ".join(sorted(TURN_DETECTION_TYPES))
            raise ValueError(f"VOICE_AGENT_TURN_DETECTION must be one of: {allowed}")

    @classmethod
    def from_env(cls) -> "VoiceAgentSettings":
        endpoint = (os.getenv("VOICE_AGENT_ENDPOINT") or "").strip()
        if not endpoint:
            raise ValueError(
                "VOICE_AGENT_ENDPOINT is required, for example https://<foundry-resource>.services.ai.azure.com"
            )
        project = (os.getenv("VOICE_AGENT_PROJECT") or "").strip()
        if not project:
            raise ValueError("VOICE_AGENT_PROJECT (the Foundry project name that holds the agent) is required")
        transcription = (os.getenv("VOICE_AGENT_TRANSCRIPTION_MODEL") or "").strip() or None
        return cls(
            endpoint=endpoint,
            project_name=project,
            agent_name=(os.getenv("VOICE_AGENT_NAME") or DEFAULT_AGENT_NAME).strip(),
            agent_version=(os.getenv("VOICE_AGENT_VERSION") or "").strip() or None,
            api_version=(os.getenv("VOICE_AGENT_API_VERSION") or DEFAULT_API_VERSION).strip(),
            model_label=(os.getenv("VOICE_AGENT_MODEL") or "gpt-realtime-2.1-mini").strip(),
            voice_label=(os.getenv("VOICE_AGENT_VOICE") or "en-US-Ava:DragonHDLatestNeural").strip(),
            turn_detection=(os.getenv("VOICE_AGENT_TURN_DETECTION") or "azure_semantic_vad").strip(),
            transcription_model=transcription,
            route=(os.getenv("VOICE_AGENT_ROUTE") or "project").strip().lower(),
            project_route_api_version=(
                os.getenv("VOICE_AGENT_PROJECT_API_VERSION") or DEFAULT_PROJECT_ROUTE_API_VERSION
            ).strip(),
            send_session_config=(os.getenv("VOICE_AGENT_SEND_SESSION_CONFIG") or "").strip().lower()
            in {"1", "true", "yes", "on"},
        )

    def resolved_transcription_model(self) -> str:
        if self.transcription_model:
            return self.transcription_model
        return "gpt-4o-mini-transcribe" if self.model_label in NATIVE_TRANSCRIPTION_MODELS else "azure-speech"


class VoiceAgentBridge(RealtimeStyleBridge):
    api_name = "Foundry Voice Agent (preview)"

    def __init__(
        self,
        profile: AgentProfile,
        tools: ToolRegistry,
        emit,
        metrics: SessionMetrics,
        session_id: str,
        *,
        settings: VoiceAgentSettings | None = None,
        token_provider: TokenProvider | None = None,
    ):
        super().__init__(profile, tools, emit, metrics, session_id)
        self.settings = settings or VoiceAgentSettings.from_env()
        self.token_provider = token_provider or TokenProvider()

    def _agent_params(self) -> dict[str, str]:
        params = {
            "api-version": self.settings.api_version,
            "agent-name": self.settings.agent_name,
            "agent-project-name": self.settings.project_name,
        }
        if self.settings.agent_version:
            params["agent-version"] = self.settings.agent_version
        return params

    async def build_url(self) -> str:
        if self.settings.route == "project":
            return self._project_route_url()
        parsed = urlsplit(self.settings.endpoint)
        if parsed.scheme in {"ws", "wss"}:
            return _merge_query(self.settings.endpoint, self._agent_params(), keep_existing=True)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("VOICE_AGENT_ENDPOINT must start with https://, ws://, or wss://")
        base = urlunsplit(("wss", parsed.netloc, "/voice-live/realtime", "", ""))
        return _merge_query(base, self._agent_params(), keep_existing=False)

    def _project_route_url(self) -> str:
        parsed = urlsplit(self.settings.endpoint)
        scheme = {"https": "wss", "http": "ws"}.get(parsed.scheme, parsed.scheme)
        if scheme not in {"ws", "wss"} or not parsed.netloc:
            raise ValueError("VOICE_AGENT_ENDPOINT must start with https://, ws://, or wss://")
        path = (
            f"/api/projects/{quote(self.settings.project_name, safe='')}"
            f"/agents/{quote(self.settings.agent_name, safe='')}/endpoint/protocols/voice"
        )
        query = urlencode({"api-version": self.settings.project_route_api_version})
        return urlunsplit((scheme, parsed.netloc, path, query, ""))

    async def build_headers(self) -> dict[str, str]:
        # Agent mode is Entra-only, so no API key is ever passed.
        headers = await build_auth_headers(None, VOICE_AGENT_SCOPE, self.token_provider)
        if self.settings.route == "project":
            headers.update(FOUNDRY_FEATURES_HEADER)
        return headers

    async def send_greeting(self) -> None:
        """The agent speaks its own greeting (agent definition), so the bridge sends nothing."""

        return None

    def build_session_update(self) -> dict[str, Any] | None:
        if not self.settings.send_session_config:
            return None
        session: dict[str, Any] = {
            "modalities": ["text", "audio"],
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "input_audio_sampling_rate": 24000,
            "turn_detection": self._turn_detection_config(),
            "input_audio_noise_reduction": {"type": "azure_deep_noise_suppression"},
            "input_audio_echo_cancellation": {"type": "server_echo_cancellation"},
            "input_audio_transcription": {"model": self.settings.resolved_transcription_model()},
        }
        return {"type": "session.update", "session": session}

    def model_label(self) -> str:
        return f"{self.settings.model_label} (agent {self.settings.agent_name})"

    def voice_label(self) -> str:
        return self.settings.voice_label

    def _turn_detection_config(self) -> dict[str, Any]:
        config: dict[str, Any] = {
            "type": self.settings.turn_detection,
            "threshold": 0.5,
            "prefix_padding_ms": 300,
            "silence_duration_ms": 500,
            "create_response": True,
            "interrupt_response": True,
        }
        if self.settings.turn_detection.startswith("azure_semantic_vad"):
            config["remove_filler_words"] = False
        return config


def _merge_query(url: str, params: dict[str, str], *, keep_existing: bool) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        if keep_existing and key in query:
            continue
        query[key] = value
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", urlencode(query), parsed.fragment))
