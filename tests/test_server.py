from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from voiceagent_core.bridge import RealtimeStyleBridge
from voiceagent_core.metrics import SessionMetrics
from voiceagent_core.server import create_app
from voiceagent_core.settings import CommonSettings

CLOSE_SIGNAL = "__close__"


def _end_session(ws) -> None:
    ws.send_json({"type": "text", "text": CLOSE_SIGNAL})
    with pytest.raises(WebSocketDisconnect):
        while True:
            ws.receive_json()


class ServerTestBridge(RealtimeStyleBridge):
    api_name = "server-test"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._closed = asyncio.Event()

    async def build_url(self) -> str:
        return "ws://unused"

    async def build_headers(self) -> dict[str, str]:
        return {}

    def build_session_update(self) -> dict[str, Any]:
        return {"type": "session.update", "session": {}}

    def model_label(self) -> str:
        return "test-model"

    def voice_label(self) -> str:
        return "test-voice"

    async def connect(self) -> None:
        return None

    async def send_text(self, text: str) -> None:
        if text == CLOSE_SIGNAL:
            # Simulates the upstream ending so the server closes the socket first,
            # which avoids a TestClient teardown race on client-initiated close.
            self._closed.set()
            return
        self.metrics.mark_turn_start()
        self.metrics.mark_first_audio()
        turn = self.metrics.finish_turn(
            {
                "response": {
                    "usage": {
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    }
                }
            }
        )
        await self.emit({"type": "audio", "audio": "AAAA"})
        await self.emit({"type": "metrics", "turn": turn, "session": self.metrics.session_summary()})

    async def run(self) -> None:
        await self._closed.wait()

    async def close(self) -> None:
        self._closed.set()


def _app(repo_root, profile_path, max_sessions=20):
    settings = CommonSettings(
        agent_profile_path=profile_path,
        max_concurrent_sessions=max_sessions,
        static_dir=repo_root / "shared" / "static",
    )
    return create_app(lambda *args: ServerTestBridge(*args), settings)


def test_healthz_and_info(repo_root, profile_path):
    client = TestClient(_app(repo_root, profile_path))

    assert client.get("/healthz").json() == {"status": "ok"}
    info = client.get("/api/info").json()
    assert info["api"] == "server-test"
    assert info["model"] == "test-model"
    assert info["voice"] == "test-voice"
    assert info["active_sessions"] == 0


def test_websocket_happy_path(repo_root, profile_path):
    client = TestClient(_app(repo_root, profile_path))

    with client.websocket_connect("/ws") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        assert ready["api"] == "server-test"
        ws.send_json({"type": "text", "text": "hello"})
        messages = [ws.receive_json(), ws.receive_json()]
        assert {message["type"] for message in messages} == {"audio", "metrics"}
        _end_session(ws)


def test_admission_control_returns_busy(repo_root, profile_path):
    client = TestClient(_app(repo_root, profile_path, max_sessions=1))

    with client.websocket_connect("/ws") as first:
        assert first.receive_json()["type"] == "ready"
        with client.websocket_connect("/ws") as second:
            busy = second.receive_json()
            assert busy["type"] == "busy"
            assert "busy" in busy["message"]
        _end_session(first)
    # The slot is released after the session ends.
    assert client.get("/api/info").json()["active_sessions"] == 0
