"""End-to-end: Twilio phone stream -> real Realtime API bridge -> fake upstream, with a RAG tool call."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import threading
from pathlib import Path

from fastapi.testclient import TestClient

from tests.fake_upstream import FakeRealtimeServer
from voiceagent_core.server import create_app
from voiceagent_core.settings import CommonSettings
from voiceagent_core.telephony import TelephonySettings
from voiceagent_core.telephony.security import mint_call_token

ROOT = Path(__file__).resolve().parents[1]
REALTIME_SRC = ROOT / "examples" / "realtime-api" / "src"
if str(REALTIME_SRC) not in sys.path:
    sys.path.insert(0, str(REALTIME_SRC))

from realtime_api_bridge import RealtimeApiBridge, RealtimeApiSettings  # noqa: E402

SECRET = "telephony-e2e-secret-0123456789"


class _StaticTokens:
    async def get_token(self, scope: str) -> str:
        return "fake-token"


class _LoopThread:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=10)

    def __exit__(self, *exc):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)


def test_twilio_call_reaches_realtime_bridge_and_grounds_answer_with_rag(repo_root, profile_path, monkeypatch):
    monkeypatch.delenv("AZURE_SEARCH_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_SEARCH_INDEX", raising=False)
    fake = FakeRealtimeServer(
        dialect="ga",
        script_function_call=True,
        function_name="search_knowledge_base",
        function_arguments={"query": "reset my password"},
    )

    with _LoopThread() as upstream:
        upstream.run(fake.start())
        try:
            settings = RealtimeApiSettings(endpoint=fake.url, deployment="gpt-realtime-2.1-mini")

            def factory(profile, tools, emit, metrics, session_id):
                return RealtimeApiBridge(
                    profile, tools, emit, metrics, session_id, settings=settings, token_provider=_StaticTokens()
                )

            app = create_app(
                factory,
                CommonSettings(agent_profile_path=profile_path, static_dir=repo_root / "shared" / "static"),
                TelephonySettings(
                    providers=frozenset({"twilio"}),
                    webhook_secret=SECRET,
                    public_base_url="https://agent.example.test",
                    twilio_auth_token="unused",
                ),
            )
            client = TestClient(app)
            token = mint_call_token(SECRET, "twilio", "CA-e2e")

            with client.websocket_connect("/telephony/twilio/media") as ws:
                ws.send_text(json.dumps({"event": "connected"}))
                ws.send_text(
                    json.dumps(
                        {"event": "start", "streamSid": "MZe2e", "start": {"customParameters": {"token": token}}}
                    )
                )
                caller_audio = base64.b64encode(b"\xff" * 160).decode()
                ws.send_text(json.dumps({"event": "media", "media": {"track": "inbound", "payload": caller_audio}}))

                # The fake upstream answers the greeting with a knowledge_search call, then speech_started
                # (-> Twilio clear) and agent audio (-> Twilio media, mu-law 8 kHz).
                seen: list[str] = []
                while "media" not in seen:
                    seen.append(json.loads(ws.receive_text())["event"])
                assert "clear" in seen
                ws.send_text(json.dumps({"event": "stop"}))
        finally:
            upstream.run(fake.stop())

    types = [event.get("type") for event in fake.received_events]
    assert types[0] == "session.update"
    session = fake.received_events[0]["session"]
    assert session["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert "search_knowledge_base" in [tool["name"] for tool in session["tools"]]

    appended = [event for event in fake.received_events if event.get("type") == "input_audio_buffer.append"]
    assert appended and len(base64.b64decode(appended[0]["audio"])) == 480 * 2

    outputs = [
        event["item"]
        for event in fake.received_events
        if event.get("type") == "conversation.item.create" and event["item"].get("type") == "function_call_output"
    ]
    assert outputs, "the RAG tool result should be returned to the model"
    rag_result = json.loads(outputs[0]["output"])
    assert rag_result["results"][0]["source"] == "kb/password-reset"
