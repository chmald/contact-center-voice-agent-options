from __future__ import annotations

import importlib.util
import json
import shlex
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from tests.fake_upstream import FakeRealtimeServer
from voiceagent_core.metrics import SessionMetrics
from voiceagent_core.profile import load_profile
from voiceagent_core.tools import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "foundry-voice-agent"
SRC = EXAMPLE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from voice_agent_bridge import VOICE_AGENT_SCOPE, VoiceAgentBridge, VoiceAgentSettings  # noqa: E402


class FakeTokenProvider:
    def __init__(self):
        self.scopes: list[str] = []

    async def get_token(self, scope: str) -> str:
        self.scopes.append(scope)
        return "fake-token"


def _bridge(profile_path: Path, settings: VoiceAgentSettings, tokens: FakeTokenProvider | None = None):
    profile = replace(load_profile(profile_path), greeting="")
    emitted: list[dict[str, Any]] = []

    async def emit(message: dict[str, Any]) -> None:
        emitted.append(message)

    bridge = VoiceAgentBridge(
        profile,
        ToolRegistry.from_profile(profile),
        emit,
        SessionMetrics("agent-test"),
        "agent-test",
        settings=settings,
        token_provider=tokens or FakeTokenProvider(),
    )
    return bridge, emitted


async def test_url_uses_agent_mode_query_not_model(profile_path):
    bridge, _ = _bridge(
        profile_path,
        VoiceAgentSettings(endpoint="https://demo.services.ai.azure.com/", project_name="voice-agents", agent_version="3"),
    )
    parsed = urlsplit(await bridge.build_url())
    assert (parsed.scheme, parsed.netloc, parsed.path) == ("wss", "demo.services.ai.azure.com", "/voice-live/realtime")
    assert parse_qs(parsed.query) == {
        "api-version": ["2026-07-15"],
        "agent-name": ["voice-agent-demo"],
        "agent-project-name": ["voice-agents"],
        "agent-version": ["3"],
    }


async def test_headers_are_entra_only(profile_path):
    tokens = FakeTokenProvider()
    bridge, _ = _bridge(profile_path, VoiceAgentSettings(endpoint="https://d", project_name="p"), tokens)
    assert await bridge.build_headers() == {"Authorization": "Bearer fake-token"}
    assert tokens.scopes == [VOICE_AGENT_SCOPE]


def test_no_session_update_by_default_because_the_agent_owns_the_session(profile_path):
    bridge, _ = _bridge(profile_path, VoiceAgentSettings(endpoint="https://d", project_name="p"))
    assert bridge.build_session_update() is None


def test_optional_session_update_carries_audio_pipeline_only(profile_path):
    bridge, _ = _bridge(profile_path, VoiceAgentSettings(endpoint="https://d", project_name="p", send_session_config=True))
    session = bridge.build_session_update()["session"]
    for agent_owned in ("instructions", "tools", "tool_choice", "voice", "temperature"):
        assert agent_owned not in session
    assert session["input_audio_sampling_rate"] == 24000
    assert session["turn_detection"]["type"] == "azure_semantic_vad"
    assert session["input_audio_noise_reduction"] == {"type": "azure_deep_noise_suppression"}
    assert session["input_audio_transcription"] == {"model": "azure-speech"}


async def test_project_route_matches_the_foundry_portal_sample(profile_path):
    tokens = FakeTokenProvider()
    bridge, _ = _bridge(
        profile_path,
        VoiceAgentSettings(endpoint="https://demo.services.ai.azure.com", project_name="voice-agents", agent_name="my agent", route="project"),
        tokens,
    )
    assert await bridge.build_url() == (
        "wss://demo.services.ai.azure.com/api/projects/voice-agents/agents/my%20agent/endpoint/protocols/voice"
        "?api-version=2025-11-15-preview"
    )
    assert await bridge.build_headers() == {"Authorization": "Bearer fake-token", "Foundry-Features": "VoiceAgents=V1Preview"}
    with pytest.raises(ValueError, match="VOICE_AGENT_ROUTE"):
        VoiceAgentSettings(endpoint="https://d", project_name="p", route="other")


async def test_connect_sends_no_instruction_override_or_session_config(profile_path):
    server = FakeRealtimeServer(dialect="beta")
    await server.start()
    try:
        profile = load_profile(profile_path)  # keeps the profile greeting on purpose
        assert profile.greeting
        emitted: list[dict[str, Any]] = []

        async def emit(message):
            emitted.append(message)

        bridge = VoiceAgentBridge(
            profile, ToolRegistry.from_profile(profile), emit, SessionMetrics("g"), "g",
            settings=VoiceAgentSettings(endpoint=server.url, project_name="voice-agents"),
            token_provider=FakeTokenProvider(),
        )
        await bridge.connect()
        await bridge.close()
    finally:
        await server.stop()
    types = [e.get("type") for e in server.received_events]
    assert "session.update" not in types
    assert not any(e.get("type") == "response.create" and "instructions" in (e.get("response") or {}) for e in server.received_events)


def test_settings_require_endpoint_and_project(monkeypatch):
    monkeypatch.delenv("VOICE_AGENT_ENDPOINT", raising=False)
    with pytest.raises(ValueError, match="VOICE_AGENT_ENDPOINT"):
        VoiceAgentSettings.from_env()
    monkeypatch.setenv("VOICE_AGENT_ENDPOINT", "https://d")
    monkeypatch.delenv("VOICE_AGENT_PROJECT", raising=False)
    with pytest.raises(ValueError, match="VOICE_AGENT_PROJECT"):
        VoiceAgentSettings.from_env()
    with pytest.raises(ValueError, match="TURN_DETECTION"):
        VoiceAgentSettings(endpoint="https://d", project_name="p", turn_detection="semantic_vad")


async def test_agent_function_call_is_answered_by_shared_rag_tool(profile_path, monkeypatch):
    monkeypatch.delenv("AZURE_SEARCH_ENDPOINT", raising=False)
    server = FakeRealtimeServer(
        dialect="beta",
        script_function_call=True,
        function_name="search_knowledge_base",
        function_arguments={"query": "support hours"},
    )
    await server.start()
    try:
        bridge, emitted = _bridge(profile_path, VoiceAgentSettings(endpoint=server.url, project_name="voice-agents"))
        await bridge.connect()
        run = __import__("asyncio").create_task(bridge.run())
        await bridge.send_text("When is the service desk open?")
        from tests.conftest import wait_until

        await wait_until(lambda: any(m["type"] == "metrics" for m in emitted))
        run.cancel()
        await bridge.close()
    finally:
        await server.stop()

    query = parse_qs(urlsplit(server.path).query)
    assert query["agent-name"] == ["voice-agent-demo"] and "model" not in query
    outputs = [
        json.loads(e["item"]["output"])
        for e in server.received_events
        if e.get("type") == "conversation.item.create" and e["item"].get("type") == "function_call_output"
    ]
    assert outputs[0]["results"][0]["source"] == "kb/support-hours"
    assert any(m["type"] == "tool_call" and m["name"] == "search_knowledge_base" for m in emitted)


def _load_create_script():
    spec = importlib.util.spec_from_file_location("create_voice_agent", ROOT / "scripts" / "create-voice-agent.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_agent_definition_is_built_from_the_shared_profile(profile_path):
    module = _load_create_script()
    definition = module.build_definition(profile_path, "gpt-realtime-2.1-mini", "en-US-Ava:DragonHDLatestNeural")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))

    assert definition["kind"] == "voice" and definition["model_type"] == "managed"
    assert definition["model"] == "gpt-realtime-2.1-mini"
    assert definition["instructions"] == profile["instructions"]
    assert [t["name"] for t in definition["tools"]] == [t["name"] for t in profile["tools"]]
    assert all(t["type"] == "function" for t in definition["tools"])
    assert "handler_config" not in json.dumps(definition)  # server never sees local handler wiring
    assert definition["audio"]["output"] == {"voice": "en-US-Ava:DragonHDLatestNeural", "voice_type": "azure-standard"}
    assert definition["audio"]["input"]["turn_detection"] == {"type": "azure_semantic_vad"}
    assert definition["audio"]["input"]["transcription"] == {"model": "azure-speech"}
    assert definition["greeting"] == {"type": "template", "text": profile["greeting"]}
    assert module.voice_config("marin") == {"voice": "marin", "voice_type": "openai"}
    assert definition["store"] is True


def test_agent_definition_is_accepted_by_the_sdk_model(profile_path):
    models = pytest.importorskip("azure.ai.projects.models")
    module = _load_create_script()
    definition = module.build_definition(profile_path, "gpt-realtime-2.1-mini", "en-US-Ava:DragonHDLatestNeural")
    sdk = models.VoiceAgentDefinition(definition)
    round_trip = sdk.as_dict()
    assert round_trip["kind"] == "voice"
    assert type(sdk.greeting).__name__ == "VoiceAgentTemplateGreetingConfig"
    assert type(sdk.audio.input.turn_detection).__name__ == "VoiceAgentAzureSemanticVadTurnDetection"
    assert round_trip["tools"][0]["type"] == "function"


def test_main_loads_and_reports_agent(monkeypatch, profile_path, repo_root):
    monkeypatch.setenv("VOICE_AGENT_ENDPOINT", "https://demo.services.ai.azure.com")
    monkeypatch.setenv("VOICE_AGENT_PROJECT", "voice-agents")
    monkeypatch.setenv("AGENT_PROFILE_PATH", str(profile_path))
    monkeypatch.setenv("STATIC_DIR", str(repo_root / "shared" / "static"))
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    monkeypatch.delenv("TELEPHONY_PROVIDERS", raising=False)
    spec = importlib.util.spec_from_file_location("voice_agent_main", SRC / "main.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["voice_agent_main"] = module
    try:
        assert spec and spec.loader
        spec.loader.exec_module(module)
        with TestClient(module.app) as client:
            payload = client.get("/api/info").json()
        assert payload["api"] == "Foundry Voice Agent (preview)"
        assert payload["model"] == "gpt-realtime-2.1-mini (agent voice-agent-demo)"
    finally:
        sys.modules.pop("voice_agent_main", None)


def test_dockerfile_copy_sources_exist(repo_root):
    for raw_line in (EXAMPLE / "Dockerfile").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("COPY "):
            for source in [p for p in shlex.split(line)[1:-1] if not p.startswith("--")]:
                assert (repo_root / source).exists(), source


def test_infra_and_azd_contract():
    text = "\n".join(p.read_text(encoding="utf-8") for p in (EXAMPLE / "infra").rglob("*.bicep"))
    assert "allowProjectManagement: true" in text
    assert "Microsoft.CognitiveServices/accounts/projects@" in text
    assert "53ca6127-db72-4b80-b1b0-d745d6d5456d" in text  # Foundry User
    assert "disableLocalAuth: true" in text
    assert "GlobalStandard" not in text  # managed model: no deployment, no Azure OpenAI quota
    azure_yaml = (EXAMPLE / "azure.yaml").read_text(encoding="utf-8")
    assert "run: hooks/postprovision.ps1" in azure_yaml
    assert (EXAMPLE / "hooks" / "postprovision.ps1").exists()
