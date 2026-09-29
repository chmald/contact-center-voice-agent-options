from __future__ import annotations

import asyncio
import importlib.util
import json
import shlex
import sys
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from tests.conftest import wait_until
from tests.fake_upstream import FakeRealtimeServer
from voiceagent_core.metrics import SessionMetrics
from voiceagent_core.profile import load_profile
from voiceagent_core.tools import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]
VOICE_LIVE_SRC = ROOT / "examples" / "voice-live-api" / "src"
if str(VOICE_LIVE_SRC) not in sys.path:
    sys.path.insert(0, str(VOICE_LIVE_SRC))

from voice_live_bridge import VOICE_LIVE_SCOPE, VoiceLiveBridge, VoiceLiveSettings


class FakeTokenProvider:
    def __init__(self):
        self.scopes: list[str] = []

    async def get_token(self, scope: str) -> str:
        self.scopes.append(scope)
        return "fake-token"


def _load_test_profile(profile_path: Path):
    return replace(load_profile(profile_path), greeting="")


def _bridge(profile_path: Path, settings: VoiceLiveSettings, token_provider: Any | None = None):
    profile = _load_test_profile(profile_path)
    emitted: list[dict[str, Any]] = []

    async def emit(message: dict[str, Any]) -> None:
        emitted.append(message)

    bridge = VoiceLiveBridge(
        profile=profile,
        tools=ToolRegistry.from_profile(profile),
        emit=emit,
        metrics=SessionMetrics("voice-live-test"),
        session_id="voice-live-test",
        settings=settings,
        token_provider=token_provider or FakeTokenProvider(),
    )
    return bridge, emitted


@pytest.mark.asyncio
async def test_url_building_services_cognitive_and_ws(profile_path):
    services_bridge, _ = _bridge(
        profile_path,
        VoiceLiveSettings(endpoint="https://demo.services.ai.azure.com/"),
    )
    services_url = await services_bridge.build_url()
    parsed = urlsplit(services_url)
    assert parsed.scheme == "wss"
    assert parsed.netloc == "demo.services.ai.azure.com"
    assert parsed.path == "/voice-live/realtime"
    assert parse_qs(parsed.query) == {
        "api-version": ["2026-07-15"],
        "model": ["gpt-realtime-mini"],
    }

    cognitive_bridge, _ = _bridge(
        profile_path,
        VoiceLiveSettings(
            endpoint="https://demo.cognitiveservices.azure.com/some/path/",
            model="gpt-realtime-2.1-mini",
        ),
    )
    cognitive_url = await cognitive_bridge.build_url()
    parsed = urlsplit(cognitive_url)
    assert parsed.netloc == "demo.cognitiveservices.azure.com"
    assert parsed.path == "/voice-live/realtime"
    assert parse_qs(parsed.query)["model"] == ["gpt-realtime-2.1-mini"]

    ws_bridge, _ = _bridge(
        profile_path,
        VoiceLiveSettings(
            endpoint="ws://127.0.0.1:1234/fake?api-version=test",
            model="gpt-realtime-2.1-mini",
        ),
    )
    ws_url = await ws_bridge.build_url()
    parsed = urlsplit(ws_url)
    assert parsed.scheme == "ws"
    assert parsed.path == "/fake"
    assert parse_qs(parsed.query) == {
        "api-version": ["test"],
        "model": ["gpt-realtime-2.1-mini"],
    }


@pytest.mark.asyncio
async def test_headers_use_ai_scope_or_api_key(profile_path):
    provider = FakeTokenProvider()
    bridge, _ = _bridge(
        profile_path,
        VoiceLiveSettings(endpoint="https://demo.services.ai.azure.com"),
        provider,
    )

    assert await bridge.build_headers() == {"Authorization": "Bearer fake-token"}
    assert provider.scopes == [VOICE_LIVE_SCOPE]

    api_key_provider = FakeTokenProvider()
    key_bridge, _ = _bridge(
        profile_path,
        VoiceLiveSettings(endpoint="https://demo.services.ai.azure.com", api_key="local-key"),
        api_key_provider,
    )
    assert await key_bridge.build_headers() == {"api-key": "local-key"}
    assert api_key_provider.scopes == []


def test_session_update_shape_voice_inference_and_validation(profile_path, monkeypatch):
    bridge, _ = _bridge(profile_path, VoiceLiveSettings(endpoint="https://demo.services.ai.azure.com"))
    update = bridge.build_session_update()
    assert update["type"] == "session.update"
    session = update["session"]

    assert session["modalities"] == ["text", "audio"]
    assert session["voice"] == {
        "type": "azure-standard",
        "name": "en-US-Ava:DragonHDLatestNeural",
        "temperature": 0.8,
    }
    assert session["input_audio_format"] == "pcm16"
    assert session["output_audio_format"] == "pcm16"
    assert session["input_audio_sampling_rate"] == 24000
    assert session["turn_detection"] == {
        "type": "azure_semantic_vad",
        "threshold": 0.5,
        "prefix_padding_ms": 300,
        "silence_duration_ms": 500,
        "create_response": True,
        "interrupt_response": True,
        "remove_filler_words": False,
    }
    assert session["input_audio_noise_reduction"] == {"type": "azure_deep_noise_suppression"}
    assert session["input_audio_echo_cancellation"] == {"type": "server_echo_cancellation"}
    assert session["input_audio_transcription"] == {"model": "gpt-4o-mini-transcribe"}
    assert session["tools"] == bridge.tools.definitions()
    assert session["tool_choice"] == "auto"
    assert session["temperature"] == 0.8
    assert session["max_response_output_tokens"] == "inf"

    assert "output_modalities" not in session
    assert "audio" not in session
    assert "type" not in session

    openai_bridge, _ = _bridge(
        profile_path,
        VoiceLiveSettings(endpoint="https://demo.services.ai.azure.com", voice="alloy"),
    )
    assert openai_bridge.build_session_update()["session"]["voice"] == {"type": "openai", "name": "alloy"}

    preview_bridge, _ = _bridge(
        profile_path,
        VoiceLiveSettings(endpoint="https://demo.services.ai.azure.com", model="gpt-realtime-2.1-mini"),
    )
    assert preview_bridge.build_session_update()["session"]["input_audio_transcription"] == {
        "model": "azure-speech"
    }

    override_bridge, _ = _bridge(
        profile_path,
        VoiceLiveSettings(
            endpoint="https://demo.services.ai.azure.com",
            transcription_model="whisper-1",
        ),
    )
    assert override_bridge.build_session_update()["session"]["input_audio_transcription"] == {
        "model": "whisper-1"
    }

    invalid_bridge, _ = _bridge(
        profile_path,
        VoiceLiveSettings(endpoint="https://demo.services.ai.azure.com", voice="unknown-voice"),
    )
    with pytest.raises(ValueError, match="VOICE_LIVE_VOICE"):
        invalid_bridge.build_session_update()

    monkeypatch.setenv("VOICE_LIVE_ENDPOINT", "https://demo.services.ai.azure.com")
    monkeypatch.setenv("VOICE_LIVE_TEMPERATURE", "1.3")
    with pytest.raises(ValueError, match="VOICE_LIVE_TEMPERATURE"):
        VoiceLiveSettings.from_env()


@pytest.mark.asyncio
async def test_voice_live_bridge_end_to_end_beta_tool_flow(profile_path):
    server = FakeRealtimeServer(dialect="beta", script_function_call=True)
    await server.start()
    provider = FakeTokenProvider()
    bridge, emitted = _bridge(
        profile_path,
        VoiceLiveSettings(endpoint=server.url),
        provider,
    )
    task = None
    try:
        await bridge.connect()
        task = asyncio.create_task(bridge.run())
        await bridge.send_text("check request")

        await wait_until(lambda: any(message["type"] == "tool_call" for message in emitted))
        await wait_until(lambda: any(message["type"] == "audio" for message in emitted))

        assert server.headers["authorization"] == "Bearer fake-token"
        assert provider.scopes == [VOICE_LIVE_SCOPE]
        assert server.path.startswith("/fake")
        assert server.rejected_response_creates == 0
        assert any(
            message["type"] == "transcript"
            and message["role"] == "assistant"
            and message["final"] is True
            for message in emitted
        )

        output_items = [
            event["item"]
            for event in server.received_events
            if event.get("type") == "conversation.item.create"
            and event.get("item", {}).get("type") == "function_call_output"
        ]
        assert len(output_items) == 1
        assert output_items[0]["call_id"] == "call_test_1"
        assert json.loads(output_items[0]["output"])["found"] is True
    finally:
        await bridge.close()
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await server.stop()


def test_main_loads_and_info_endpoint_reports_voice_live(monkeypatch, profile_path, repo_root):
    monkeypatch.setenv("VOICE_LIVE_ENDPOINT", "https://demo.services.ai.azure.com")
    monkeypatch.setenv("AGENT_PROFILE_PATH", str(profile_path))
    monkeypatch.setenv("STATIC_DIR", str(repo_root / "shared" / "static"))
    monkeypatch.setenv("MAX_CONCURRENT_SESSIONS", "20")
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)

    spec = importlib.util.spec_from_file_location("voice_live_main", VOICE_LIVE_SRC / "main.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["voice_live_main"] = module
    try:
        spec.loader.exec_module(module)
        with TestClient(module.app) as client:
            response = client.get("/api/info")
        assert response.status_code == 200
        payload = response.json()
        assert payload["api"] == "Voice Live API"
        assert payload["model"] == "gpt-realtime-mini"
    finally:
        sys.modules.pop("voice_live_main", None)


def test_dockerfile_copy_sources_exist(repo_root):
    dockerfile = repo_root / "examples" / "voice-live-api" / "Dockerfile"
    for raw_line in dockerfile.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("COPY "):
            continue
        parts = shlex.split(line)
        sources = [part for part in parts[1:-1] if not part.startswith("--")]
        for source in sources:
            assert (repo_root / source).exists(), f"Dockerfile COPY source does not exist: {source}"


def test_infra_contains_voice_live_contract_guards(repo_root):
    infra = repo_root / "examples" / "voice-live-api" / "infra"
    text = "\n".join(path.read_text(encoding="utf-8") for path in infra.rglob("*.bicep"))

    assert (infra / "modules" / "fetch-container-image.bicep").exists()
    assert "a97b65f3-24c7-4388-baec-2e87135dc908" in text
    assert "53ca6127-db72-4b80-b1b0-d745d6d5456d" in text
    assert "disableLocalAuth: true" in text
    assert "2026-07-15" in text
    assert "'azd-service-name': 'web'" in text


def test_azure_yaml_uses_repo_context_and_remote_build(repo_root):
    azure_yaml = (repo_root / "examples" / "voice-live-api" / "azure.yaml").read_text(encoding="utf-8")

    assert "context: ../.." in azure_yaml
    assert "remoteBuild: true" in azure_yaml
