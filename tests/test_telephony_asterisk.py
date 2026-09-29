from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from voiceagent_core.bridge import RealtimeStyleBridge
from voiceagent_core.server import create_app
from voiceagent_core.settings import CommonSettings
from voiceagent_core.telephony import TelephonySettings
from voiceagent_core.telephony.asterisk import AsteriskCodec, parse_control

SECRET = "telephony-test-secret-0123456789"
AST_SECRET = "asterisk-test-secret-0123456789"
BARGE_IN_BYTES = 42  # a PCM16 24 kHz chunk of this size makes the fake bridge emit speech_started
TURN_END_BYTES = 44  # ...and this size makes it emit a metrics (turn finished) event


class EchoBridge(RealtimeStyleBridge):
    api_name = "asterisk-test"
    received: list[str] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._closed = asyncio.Event()

    async def build_url(self):
        return "ws://unused"

    async def build_headers(self):
        return {}

    def build_session_update(self):
        return None

    def model_label(self):
        return "m"

    def voice_label(self):
        return "v"

    async def connect(self):
        return None

    async def send_audio(self, b64: str) -> None:
        EchoBridge.received.append(b64)
        size = len(base64.b64decode(b64))
        if size == BARGE_IN_BYTES:
            await self.emit({"type": "speech_started"})
        elif size == TURN_END_BYTES:
            await self.emit({"type": "metrics", "turn": {}, "session": {}})
        else:
            await self.emit({"type": "audio", "audio": b64})

    async def run(self):
        await self._closed.wait()

    async def close(self):
        self._closed.set()


def _client(repo_root, profile_path, max_sessions=20):
    app = create_app(
        lambda p, t, e, m, s: EchoBridge(p, t, e, m, s),
        CommonSettings(agent_profile_path=profile_path, max_concurrent_sessions=max_sessions, static_dir=repo_root / "shared" / "static"),
        TelephonySettings(providers=frozenset({"asterisk"}), webhook_secret=SECRET, asterisk_websocket_secret=AST_SECRET),
    )
    return TestClient(app)


def _basic(password: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"asterisk:{password}".encode()).decode()}


def _media_start_json(fmt: str = "slin24", channel_id: str = "pbx1-1.1") -> str:
    return json.dumps({"event": "MEDIA_START", "connection_id": "c1", "channel": "WebSocket/voice_agent", "channel_id": channel_id, "format": fmt, "optimal_frame_size": 960, "ptime": 20})


def test_parse_control_supports_json_and_plain_text():
    fields, is_json = parse_control(_media_start_json())
    assert is_json and fields["event"] == "MEDIA_START" and fields["format"] == "slin24"
    fields, is_json = parse_control("MEDIA_START connection_id:abc channel:WebSocket/x channel_id:pbx-1.2 format:ulaw optimal_frame_size:160 ptime:20")
    assert not is_json and fields == {"event": "MEDIA_START", "connection_id": "abc", "channel": "WebSocket/x", "channel_id": "pbx-1.2", "format": "ulaw", "optimal_frame_size": "160", "ptime": "20"}


def test_codecs_convert_to_and_from_bridge_format():
    pcm24 = np.arange(960, dtype="<i2").tobytes()
    slin24 = AsteriskCodec("slin24")
    assert base64.b64decode(slin24.to_bridge(pcm24)) == pcm24
    assert slin24.to_asterisk(base64.b64encode(pcm24).decode()) == pcm24
    ulaw = AsteriskCodec("ulaw")
    assert len(base64.b64decode(ulaw.to_bridge(b"\xff" * 160))) == 960  # 20 ms at 24 kHz
    assert 150 <= len(ulaw.to_asterisk(base64.b64encode(bytes(960)).decode())) <= 160
    slin = AsteriskCodec("slin")
    assert len(base64.b64decode(slin.to_bridge(bytes(320)))) == 960
    assert 300 <= len(slin.to_asterisk(base64.b64encode(bytes(960)).decode())) <= 320


def test_requires_secret_via_basic_auth_or_query(repo_root, profile_path):
    client = _client(repo_root, profile_path)
    for kwargs in ({}, {"headers": _basic("wrong")}):
        with pytest.raises(Exception):
            with client.websocket_connect("/telephony/asterisk/media", **kwargs) as ws:
                ws.receive_text()
    with client.websocket_connect(f"/telephony/asterisk/media?secret={AST_SECRET}") as ws:
        ws.send_text(_media_start_json())
        ws.send_bytes(np.ones(480, dtype="<i2").tobytes())
        assert ws.receive_text() == json.dumps({"command": "START_MEDIA_BUFFERING"})
        ws.close()


def test_slin24_round_trip_buffering_barge_in_and_turn_end(repo_root, profile_path):
    EchoBridge.received = []
    client = _client(repo_root, profile_path)
    frame = np.arange(480, dtype="<i2").tobytes()  # 20 ms slin24
    with client.websocket_connect("/telephony/asterisk/media", headers={**_basic(AST_SECRET), "Sec-WebSocket-Protocol": "media"}) as ws:
        assert ws.accepted_subprotocol == "media"
        ws.send_text(_media_start_json())
        ws.send_bytes(frame)
        assert json.loads(ws.receive_text()) == {"command": "START_MEDIA_BUFFERING"}
        assert ws.receive_bytes() == frame  # agent audio back as raw PCM, no conversion
        assert client.app.state.session_hub.active == 1

        ws.send_bytes(bytes(TURN_END_BYTES))
        assert json.loads(ws.receive_text()) == {"command": "STOP_MEDIA_BUFFERING", "correlation_id": "pbx1-1.1"}

        ws.send_bytes(frame)
        assert json.loads(ws.receive_text()) == {"command": "START_MEDIA_BUFFERING"}
        ws.receive_bytes()
        ws.send_bytes(bytes(BARGE_IN_BYTES))
        assert json.loads(ws.receive_text()) == {"command": "FLUSH_MEDIA"}
    assert base64.b64decode(EchoBridge.received[0]) == frame
    assert client.app.state.session_hub.active == 0


def test_plain_text_control_format_is_answered_in_plain_text(repo_root, profile_path):
    client = _client(repo_root, profile_path)
    with client.websocket_connect("/telephony/asterisk/media", headers=_basic(AST_SECRET)) as ws:
        ws.send_text("MEDIA_START connection_id:c2 channel:WebSocket/x channel_id:pbx-2.1 format:ulaw optimal_frame_size:160 ptime:20")
        ws.send_bytes(b"\xff" * 160)
        assert ws.receive_text() == "START_MEDIA_BUFFERING"
        assert 150 <= len(ws.receive_bytes()) <= 160


def test_unsupported_format_and_busy_calls_are_hung_up(repo_root, profile_path):
    client = _client(repo_root, profile_path)
    with client.websocket_connect("/telephony/asterisk/media", headers=_basic(AST_SECRET)) as ws:
        ws.send_text(_media_start_json(fmt="opus"))
        assert json.loads(ws.receive_text()) == {"command": "HANGUP"}

    busy = _client(repo_root, profile_path, max_sessions=1)
    busy.app.state.session_hub.active = 1
    with busy.websocket_connect("/telephony/asterisk/media", headers=_basic(AST_SECRET)) as ws:
        ws.send_text(_media_start_json())
        assert json.loads(ws.receive_text()) == {"command": "HANGUP"}
    assert busy.app.state.session_hub.active == 1


def test_asterisk_settings_require_secret():
    with pytest.raises(ValueError, match="ASTERISK_WEBSOCKET_SECRET"):
        TelephonySettings(providers=frozenset({"asterisk"}), webhook_secret=SECRET)
    assert TelephonySettings(providers=frozenset({"asterisk"}), webhook_secret=SECRET, asterisk_websocket_secret=AST_SECRET).enabled


def test_enable_telephony_script_generates_every_required_secret(repo_root):
    script = (repo_root / "scripts" / "enable-telephony.ps1").read_text(encoding="utf-8")
    for name in ("TELEPHONY_PROVIDERS", "TELEPHONY_WEBHOOK_SECRET", "ASTERISK_WEBSOCKET_SECRET", "ACS_EVENTGRID_SECRET", "TWILIO_AUTH_TOKEN"):
        assert name in script
    assert "RandomNumberGenerator" in script
    assert "WriteAsteriskConfig" in script
    assert "/telephony/asterisk/media" in script and "c(slin24)f(json)" in script
    deploy_doc = (repo_root / "docs" / "03-deployment.md").read_text(encoding="utf-8")
    assert "enable-telephony.ps1" in deploy_doc and "ASTERISK_WEBSOCKET_SECRET" in deploy_doc
