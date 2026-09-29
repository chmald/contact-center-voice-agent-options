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
REALTIME_SRC = ROOT / "examples" / "realtime-api" / "src"
if str(REALTIME_SRC) not in sys.path:
    sys.path.insert(0, str(REALTIME_SRC))

from realtime_api_bridge import DEFAULT_TOKEN_SCOPE, RealtimeApiBridge, RealtimeApiSettings


class FakeTokenProvider:
    def __init__(self):
        self.scopes: list[str] = []

    async def get_token(self, scope: str) -> str:
        self.scopes.append(scope)
        return "fake-token"


def _load_test_profile(profile_path: Path):
    return replace(load_profile(profile_path), greeting="")


def _bridge(profile_path: Path, settings: RealtimeApiSettings, token_provider: Any | None = None):
    profile = _load_test_profile(profile_path)
    emitted: list[dict[str, Any]] = []

    async def emit(message: dict[str, Any]) -> None:
        emitted.append(message)

    bridge = RealtimeApiBridge(
        profile=profile,
        tools=ToolRegistry.from_profile(profile),
        emit=emit,
        metrics=SessionMetrics("realtime-test"),
        session_id="realtime-test",
        settings=settings,
        token_provider=token_provider or FakeTokenProvider(),
    )
    return bridge, emitted


@pytest.mark.asyncio
async def test_url_building_ga_v1_no_api_version_and_ws_passthrough(profile_path):
    bridge, _ = _bridge(
        profile_path,
        RealtimeApiSettings(endpoint="https://demo.openai.azure.com/"),
    )
    url = await bridge.build_url()
    parsed = urlsplit(url)
    assert parsed.scheme == "wss"
    assert parsed.netloc == "demo.openai.azure.com"
    assert parsed.path == "/openai/v1/realtime"
    assert parse_qs(parsed.query) == {"model": ["gpt-realtime-2.1-mini"]}
    assert "api-version" not in url

    ws_bridge, _ = _bridge(
        profile_path,
        RealtimeApiSettings(
            endpoint="ws://127.0.0.1:1234/fake?existing=yes",
            deployment="rt-test-deployment",
            model="display-label",
        ),
    )
    ws_url = await ws_bridge.build_url()
    parsed = urlsplit(ws_url)
    assert parsed.scheme == "ws"
    assert parsed.path == "/fake"
    assert parse_qs(parsed.query) == {"existing": ["yes"], "model": ["rt-test-deployment"]}
    assert "api-version" not in ws_url


@pytest.mark.asyncio
async def test_headers_use_ai_scope_override_api_key_and_no_beta_header(profile_path):
    provider = FakeTokenProvider()
    bridge, _ = _bridge(
        profile_path,
        RealtimeApiSettings(endpoint="https://demo.openai.azure.com"),
        provider,
    )

    headers = await bridge.build_headers()
    assert headers == {"Authorization": "Bearer fake-token"}
    assert provider.scopes == [DEFAULT_TOKEN_SCOPE]
    assert "OpenAI-Beta" not in headers

    override_provider = FakeTokenProvider()
    override_bridge, _ = _bridge(
        profile_path,
        RealtimeApiSettings(
            endpoint="https://demo.openai.azure.com",
            token_scope="https://cognitiveservices.azure.com/.default",
        ),
        override_provider,
    )
    assert await override_bridge.build_headers() == {"Authorization": "Bearer fake-token"}
    assert override_provider.scopes == ["https://cognitiveservices.azure.com/.default"]

    api_key_provider = FakeTokenProvider()
    key_bridge, _ = _bridge(
        profile_path,
        RealtimeApiSettings(endpoint="https://demo.openai.azure.com", api_key="local-key"),
        api_key_provider,
    )
    assert await key_bridge.build_headers() == {"api-key": "local-key"}
    assert api_key_provider.scopes == []


def test_ga_session_shape_defaults_variants_and_validation(profile_path):
    bridge, _ = _bridge(profile_path, RealtimeApiSettings(endpoint="https://demo.openai.azure.com"))
    update = bridge.build_session_update()
    assert update["type"] == "session.update"
    session = update["session"]

    assert session["type"] == "realtime"
    assert session["output_modalities"] == ["audio"]
    assert session["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert session["audio"]["input"]["turn_detection"] == {
        "type": "semantic_vad",
        "eagerness": "auto",
        "create_response": True,
        "interrupt_response": True,
    }
    assert session["audio"]["input"]["noise_reduction"] == {"type": "near_field"}
    assert "transcription" not in session["audio"]["input"]
    assert session["audio"]["output"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert session["audio"]["output"]["voice"] == "marin"
    assert session["tools"] == bridge.tools.definitions()
    assert session["tool_choice"] == "auto"
    assert session["max_output_tokens"] == "inf"

    for beta_key in (
        "modalities",
        "input_audio_format",
        "output_audio_format",
        "voice",
        "input_audio_sampling_rate",
        "max_response_output_tokens",
    ):
        assert beta_key not in session

    transcribe_bridge, _ = _bridge(
        profile_path,
        RealtimeApiSettings(
            endpoint="https://demo.openai.azure.com",
            transcription_deployment="gpt-4o-mini-transcribe-deployment",
        ),
    )
    assert transcribe_bridge.build_session_update()["session"]["audio"]["input"]["transcription"] == {
        "model": "gpt-4o-mini-transcribe-deployment"
    }

    none_bridge, _ = _bridge(
        profile_path,
        RealtimeApiSettings(endpoint="https://demo.openai.azure.com", noise_reduction="none"),
    )
    assert "noise_reduction" not in none_bridge.build_session_update()["session"]["audio"]["input"]

    server_vad_bridge, _ = _bridge(
        profile_path,
        RealtimeApiSettings(endpoint="https://demo.openai.azure.com", turn_detection="server_vad"),
    )
    assert server_vad_bridge.build_session_update()["session"]["audio"]["input"]["turn_detection"] == {
        "type": "server_vad",
        "threshold": 0.5,
        "prefix_padding_ms": 300,
        "silence_duration_ms": 500,
        "create_response": True,
        "interrupt_response": True,
    }

    with pytest.raises(ValueError, match="REALTIME_VOICE"):
        RealtimeApiSettings(endpoint="https://demo.openai.azure.com", voice="unknown-voice")


@pytest.mark.asyncio
async def test_realtime_bridge_end_to_end_ga_tool_flow(profile_path):
    server = FakeRealtimeServer(dialect="ga", script_function_call=True)
    await server.start()
    provider = FakeTokenProvider()
    bridge, emitted = _bridge(
        profile_path,
        RealtimeApiSettings(endpoint=server.url),
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
        assert "openai-beta" not in server.headers
        assert provider.scopes == [DEFAULT_TOKEN_SCOPE]
        assert server.path.startswith("/fake")
        assert parse_qs(urlsplit(server.path).query)["model"] == ["gpt-realtime-2.1-mini"]
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


def test_main_loads_and_info_endpoint_reports_realtime_api(monkeypatch, profile_path, repo_root):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://demo.openai.azure.com")
    monkeypatch.setenv("AGENT_PROFILE_PATH", str(profile_path))
    monkeypatch.setenv("STATIC_DIR", str(repo_root / "shared" / "static"))
    monkeypatch.setenv("MAX_CONCURRENT_SESSIONS", "20")
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)

    spec = importlib.util.spec_from_file_location("realtime_api_main", REALTIME_SRC / "main.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["realtime_api_main"] = module
    try:
        spec.loader.exec_module(module)
        with TestClient(module.app) as client:
            response = client.get("/api/info")
        assert response.status_code == 200
        payload = response.json()
        assert payload["api"] == "Realtime API"
        assert payload["model"] == "gpt-realtime-2.1-mini"
        assert payload["voice"] == "marin"
    finally:
        sys.modules.pop("realtime_api_main", None)


def test_dockerfile_copy_sources_exist(repo_root):
    dockerfile = repo_root / "examples" / "realtime-api" / "Dockerfile"
    for raw_line in dockerfile.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line.startswith("COPY "):
            continue
        parts = shlex.split(line)
        sources = [part for part in parts[1:-1] if not part.startswith("--")]
        for source in sources:
            assert (repo_root / source).exists(), f"Dockerfile COPY source does not exist: {source}"


def test_infra_contains_realtime_contract_guards(repo_root):
    infra = repo_root / "examples" / "realtime-api" / "infra"
    text = "\n".join(path.read_text(encoding="utf-8") for path in infra.rglob("*.bicep"))

    assert (infra / "modules" / "fetch-container-image.bicep").exists()
    assert "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd" in text
    assert "disableLocalAuth: true" in text
    assert "GlobalStandard" in text
    assert "2026-07-07" in text
    assert "2025-12-15" in text
    assert "'azd-service-name': 'web'" in text
    assert "dependsOn:" in text
    assert "realtimeDeployment" in text


def test_azure_yaml_uses_repo_context_and_remote_build(repo_root):
    azure_yaml = (repo_root / "examples" / "realtime-api" / "azure.yaml").read_text(encoding="utf-8")

    assert "context: ../.." in azure_yaml
    assert "remoteBuild: true" in azure_yaml
