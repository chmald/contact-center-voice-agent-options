"""Azure OpenAI GPT Realtime API bridge specifics.

This example targets the GA Realtime API contract:
- GA ``/openai/v1/realtime`` endpoint with no date-based ``api-version``.
- A Realtime model deployment you create and size against TPM quota.
- GA nested ``session.update`` schema.
- The 10 OpenAI voices: alloy, ash, ballad, coral, echo, sage, shimmer, verse, marin, cedar.
- ``semantic_vad`` or ``server_vad`` turn detection.
- ``near_field`` / ``far_field`` noise reduction, or no noise-reduction block.
- Optional input transcription that requires a separate Azure model deployment.
- WebRTC is the browser-native production alternative; this demo keeps tools and credentials server-side.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from voiceagent_core.auth import TokenProvider, build_auth_headers
from voiceagent_core.bridge import RealtimeStyleBridge
from voiceagent_core.metrics import SessionMetrics
from voiceagent_core.profile import AgentProfile
from voiceagent_core.tools import ToolRegistry

DEFAULT_TOKEN_SCOPE = "https://ai.azure.com/.default"
DEFAULT_REALTIME_DEPLOYMENT = "gpt-realtime-2.1-mini"
REALTIME_VOICES = {
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "sage",
    "shimmer",
    "verse",
    "marin",
    "cedar",
}
TURN_DETECTION_TYPES = {"semantic_vad", "server_vad"}
NOISE_REDUCTION_TYPES = {"near_field", "far_field", "none"}


@dataclass(frozen=True)
class RealtimeApiSettings:
    """Environment-backed settings for the Azure OpenAI GPT Realtime API."""

    endpoint: str
    deployment: str = DEFAULT_REALTIME_DEPLOYMENT
    model: str = DEFAULT_REALTIME_DEPLOYMENT
    voice: str = "marin"
    turn_detection: str = "semantic_vad"
    noise_reduction: str = "near_field"
    transcription_deployment: str | None = None
    token_scope: str = DEFAULT_TOKEN_SCOPE
    api_key: str | None = None

    def __post_init__(self) -> None:
        if self.voice not in REALTIME_VOICES:
            allowed = ", ".join(sorted(REALTIME_VOICES))
            raise ValueError(f"REALTIME_VOICE must be one of: {allowed}")
        if self.turn_detection not in TURN_DETECTION_TYPES:
            allowed = ", ".join(sorted(TURN_DETECTION_TYPES))
            raise ValueError(f"REALTIME_TURN_DETECTION must be one of: {allowed}")
        if self.noise_reduction not in NOISE_REDUCTION_TYPES:
            allowed = ", ".join(sorted(NOISE_REDUCTION_TYPES))
            raise ValueError(f"REALTIME_NOISE_REDUCTION must be one of: {allowed}")

    @classmethod
    def from_env(cls) -> "RealtimeApiSettings":
        endpoint = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").strip()
        if not endpoint:
            raise ValueError(
                "AZURE_OPENAI_ENDPOINT is required, for example "
                "https://<resource>.openai.azure.com"
            )

        deployment = os.getenv(
            "AZURE_OPENAI_REALTIME_DEPLOYMENT",
            DEFAULT_REALTIME_DEPLOYMENT,
        ).strip()
        model = os.getenv("AZURE_OPENAI_REALTIME_MODEL", deployment).strip()
        transcription = os.getenv("REALTIME_TRANSCRIPTION_DEPLOYMENT")
        if transcription is not None:
            transcription = transcription.strip() or None

        return cls(
            endpoint=endpoint,
            deployment=deployment,
            model=model,
            voice=os.getenv("REALTIME_VOICE", "marin").strip(),
            turn_detection=os.getenv("REALTIME_TURN_DETECTION", "semantic_vad").strip(),
            noise_reduction=os.getenv("REALTIME_NOISE_REDUCTION", "near_field").strip(),
            transcription_deployment=transcription,
            token_scope=os.getenv("AZURE_OPENAI_TOKEN_SCOPE", DEFAULT_TOKEN_SCOPE).strip(),
            api_key=(os.getenv("AZURE_OPENAI_API_KEY") or None),
        )


class RealtimeApiBridge(RealtimeStyleBridge):
    api_name = "Realtime API"

    def __init__(
        self,
        profile: AgentProfile,
        tools: ToolRegistry,
        emit,
        metrics: SessionMetrics,
        session_id: str,
        *,
        settings: RealtimeApiSettings | None = None,
        token_provider: TokenProvider | None = None,
    ):
        super().__init__(profile, tools, emit, metrics, session_id)
        self.settings = settings or RealtimeApiSettings.from_env()
        self.token_provider = token_provider or TokenProvider()

    async def build_url(self) -> str:
        parsed = urlsplit(self.settings.endpoint)
        if parsed.scheme in {"ws", "wss"}:
            return _merge_query(self.settings.endpoint, {"model": self.settings.deployment})
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("AZURE_OPENAI_ENDPOINT must start with https://, ws://, or wss://")

        base = urlunsplit(("wss", parsed.netloc, "/openai/v1/realtime", "", ""))
        return _merge_query(base, {"model": self.settings.deployment})

    async def build_headers(self) -> dict[str, str]:
        return await build_auth_headers(
            self.settings.api_key,
            self.settings.token_scope,
            self.token_provider,
        )

    def build_session_update(self) -> dict[str, Any]:
        audio_input: dict[str, Any] = {
            "format": {"type": "audio/pcm", "rate": 24000},
            "turn_detection": self._turn_detection_config(),
        }
        if self.settings.noise_reduction != "none":
            audio_input["noise_reduction"] = {"type": self.settings.noise_reduction}
        if self.settings.transcription_deployment:
            audio_input["transcription"] = {"model": self.settings.transcription_deployment}

        return {
            "type": "session.update",
            "session": {
                "type": "realtime",
                "instructions": self.profile.instructions,
                "output_modalities": ["audio"],
                "audio": {
                    "input": audio_input,
                    "output": {
                        "format": {"type": "audio/pcm", "rate": 24000},
                        "voice": self.settings.voice,
                    },
                },
                "tools": self.tools.definitions(),
                "tool_choice": "auto",
                "max_output_tokens": "inf",
            },
        }

    def model_label(self) -> str:
        return self.settings.model

    def voice_label(self) -> str:
        return self.settings.voice

    def _turn_detection_config(self) -> dict[str, Any]:
        if self.settings.turn_detection == "server_vad":
            return {
                "type": "server_vad",
                "threshold": 0.5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 500,
                "create_response": True,
                "interrupt_response": True,
            }
        return {
            "type": "semantic_vad",
            "eagerness": "auto",
            "create_response": True,
            "interrupt_response": True,
        }


def _merge_query(url: str, params: dict[str, str]) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(params)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", urlencode(query), parsed.fragment))
