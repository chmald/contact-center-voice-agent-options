"""Voice Live API bridge specifics.

Voice Live keeps the realtime-style event flow used by the shared bridge, but
the API-specific contract is Azure-shaped: a Voice Live endpoint under
``/voice-live/realtime``, the ``https://ai.azure.com/.default`` auth scope, a
flat realtime session schema, Azure/OpenAI voice selection, Azure semantic VAD,
noise suppression, echo cancellation, and managed models that do not require a
customer deployment.
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

VOICE_LIVE_SCOPE = "https://ai.azure.com/.default"
AZURE_VOICE_TEMPERATURE = 0.8
OPENAI_VOICES = {
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
TURN_DETECTION_TYPES = {"azure_semantic_vad", "azure_semantic_vad_multilingual", "server_vad"}


@dataclass(frozen=True)
class VoiceLiveSettings:
    """Environment-backed Voice Live settings.

    ``VOICE_LIVE_API_KEY`` is for local key-auth experiments only. The included
    Bicep sets ``disableLocalAuth: true``, so deployed apps use Entra ID bearer
    auth through the managed identity.
    """

    endpoint: str
    api_version: str = "2026-07-15"
    model: str = "gpt-realtime-mini"
    voice: str = "en-US-Ava:DragonHDLatestNeural"
    transcription_model: str | None = None
    turn_detection: str = "azure_semantic_vad"
    temperature: float = 0.8
    api_key: str | None = None

    @classmethod
    def from_env(cls) -> "VoiceLiveSettings":
        endpoint = (os.getenv("VOICE_LIVE_ENDPOINT") or "").strip()
        if not endpoint:
            raise ValueError(
                "VOICE_LIVE_ENDPOINT is required, for example "
                "https://<foundry-resource>.services.ai.azure.com"
            )

        model = os.getenv("VOICE_LIVE_MODEL", "gpt-realtime-mini").strip()
        transcription_model = os.getenv("VOICE_LIVE_TRANSCRIPTION_MODEL")
        if transcription_model is not None:
            transcription_model = transcription_model.strip() or None

        turn_detection = os.getenv("VOICE_LIVE_TURN_DETECTION", "azure_semantic_vad").strip()
        if turn_detection not in TURN_DETECTION_TYPES:
            allowed = ", ".join(sorted(TURN_DETECTION_TYPES))
            raise ValueError(f"VOICE_LIVE_TURN_DETECTION must be one of: {allowed}")

        raw_temperature = os.getenv("VOICE_LIVE_TEMPERATURE", "0.8")
        try:
            temperature = float(raw_temperature)
        except ValueError as exc:
            raise ValueError("VOICE_LIVE_TEMPERATURE must be a number from 0.6 to 1.2") from exc
        if not 0.6 <= temperature <= 1.2:
            raise ValueError("VOICE_LIVE_TEMPERATURE must be between 0.6 and 1.2")

        return cls(
            endpoint=endpoint,
            api_version=os.getenv("VOICE_LIVE_API_VERSION", "2026-07-15").strip(),
            model=model,
            voice=os.getenv("VOICE_LIVE_VOICE", "en-US-Ava:DragonHDLatestNeural").strip(),
            transcription_model=transcription_model,
            turn_detection=turn_detection,
            temperature=temperature,
            api_key=(os.getenv("VOICE_LIVE_API_KEY") or None),
        )

    def resolved_transcription_model(self) -> str:
        if self.transcription_model:
            return self.transcription_model
        if self.model in {"gpt-realtime", "gpt-realtime-mini"}:
            return "gpt-4o-mini-transcribe"
        return "azure-speech"


class VoiceLiveBridge(RealtimeStyleBridge):
    api_name = "Voice Live API"

    def __init__(
        self,
        profile: AgentProfile,
        tools: ToolRegistry,
        emit,
        metrics: SessionMetrics,
        session_id: str,
        *,
        settings: VoiceLiveSettings | None = None,
        token_provider: TokenProvider | None = None,
    ):
        super().__init__(profile, tools, emit, metrics, session_id)
        self.settings = settings or VoiceLiveSettings.from_env()
        self.token_provider = token_provider or TokenProvider()

    async def build_url(self) -> str:
        parsed = urlsplit(self.settings.endpoint)
        if parsed.scheme in {"ws", "wss"}:
            return _merge_query(
                self.settings.endpoint,
                {"api-version": self.settings.api_version, "model": self.settings.model},
                keep_existing=True,
            )
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("VOICE_LIVE_ENDPOINT must start with https://, ws://, or wss://")

        base = urlunsplit(("wss", parsed.netloc, "/voice-live/realtime", "", ""))
        return _merge_query(
            base,
            {"api-version": self.settings.api_version, "model": self.settings.model},
            keep_existing=False,
        )

    async def build_headers(self) -> dict[str, str]:
        return await build_auth_headers(self.settings.api_key, VOICE_LIVE_SCOPE, self.token_provider)

    def build_session_update(self) -> dict[str, Any]:
        session: dict[str, Any] = {
            "modalities": ["text", "audio"],
            "instructions": self.profile.instructions,
            "voice": self._voice_config(),
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "input_audio_sampling_rate": 24000,
            "turn_detection": self._turn_detection_config(),
            "input_audio_noise_reduction": {"type": "azure_deep_noise_suppression"},
            "input_audio_echo_cancellation": {"type": "server_echo_cancellation"},
            "input_audio_transcription": {"model": self.settings.resolved_transcription_model()},
            "tools": self.tools.definitions(),
            "tool_choice": "auto",
            "temperature": self.settings.temperature,
            "max_response_output_tokens": "inf",
        }
        return {"type": "session.update", "session": session}

    def model_label(self) -> str:
        return self.settings.model

    def voice_label(self) -> str:
        return self.settings.voice

    def _voice_config(self) -> dict[str, Any]:
        voice = self.settings.voice
        if ":" in voice or voice.endswith("Neural"):
            # Azure voice temperature controls speech expressiveness; it is independent
            # of the model sampling temperature (VOICE_LIVE_TEMPERATURE).
            return {
                "type": "azure-standard",
                "name": voice,
                "temperature": AZURE_VOICE_TEMPERATURE,
            }
        if voice in OPENAI_VOICES:
            return {"type": "openai", "name": voice}
        known = ", ".join(sorted(OPENAI_VOICES))
        raise ValueError(
            "VOICE_LIVE_VOICE must be an Azure neural voice name or one of "
            f"the supported OpenAI voices: {known}"
        )

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
