from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from voiceagent_core.bridge import RealtimeStyleBridge
from voiceagent_core.server import create_app
from voiceagent_core.settings import CommonSettings
from voiceagent_core.telephony import TelephonySettings
from voiceagent_core.telephony.security import mint_call_token, twilio_signature

SECRET = "telephony-test-secret-0123456789"
EG_SECRET = "eventgrid-test-secret-0123456789"
BASE = "https://agent.example.test"
BARGE_IN_MARKER = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
# 7 mu-law bytes from Twilio -> 21 PCM16 samples at 24 kHz -> 42 bytes reach the bridge.
BARGE_IN_PCM_BYTES = 42
TWILIO_BARGE_IN_PAYLOAD = base64.b64encode(b"\xff" * 7).decode()


class PhoneTestBridge(RealtimeStyleBridge):
    """Echo bridge: every inbound audio chunk is played back; a marker triggers barge-in."""

    api_name = "phone-test"
    received: list[str] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._closed = asyncio.Event()

    async def build_url(self) -> str:
        return "ws://unused"

    async def build_headers(self) -> dict[str, str]:
        return {}

    def build_session_update(self) -> dict[str, Any]:
        return {}

    def model_label(self) -> str:
        return "test-model"

    def voice_label(self) -> str:
        return "test-voice"

    async def connect(self) -> None:
        return None

    async def send_audio(self, b64: str) -> None:
        PhoneTestBridge.received.append(b64)
        if b64 == BARGE_IN_MARKER or len(base64.b64decode(b64)) == BARGE_IN_PCM_BYTES:
            await self.emit({"type": "speech_started"})
            return
        await self.emit({"type": "audio", "audio": b64})

    async def run(self) -> None:
        await self._closed.wait()

    async def close(self) -> None:
        self._closed.set()


class FakeAcsClient:
    def __init__(self):
        self.answered: list[dict[str, Any]] = []
        self.rejected: list[tuple[str, str]] = []
        self.redirected: list[tuple[str, Any]] = []

    async def answer_call(self, context, callback_url, **kwargs):
        self.answered.append({"context": context, "callback_url": callback_url, **kwargs})

    async def reject_call(self, context, call_reject_reason=None):
        self.rejected.append((context, call_reject_reason))

    async def redirect_call(self, context, target):
        self.redirected.append((context, target))


def _app(repo_root, profile_path, telephony: TelephonySettings, *, max_sessions=20, acs_client=None):
    settings = CommonSettings(
        agent_profile_path=profile_path,
        max_concurrent_sessions=max_sessions,
        static_dir=repo_root / "shared" / "static",
    )
    return create_app(
        lambda profile, tools, emit, metrics, sid: PhoneTestBridge(profile, tools, emit, metrics, sid),
        settings,
        telephony,
        acs_client_factory=(lambda: acs_client) if acs_client is not None else None,
    )


def _acs_settings(**overrides) -> TelephonySettings:
    values = dict(
        providers=frozenset({"acs"}),
        webhook_secret=SECRET,
        public_base_url=BASE,
        acs_endpoint="https://acs.example.test",
        acs_eventgrid_secret=EG_SECRET,
    )
    values.update(overrides)
    return TelephonySettings(**values)


def _twilio_settings(**overrides) -> TelephonySettings:
    values = dict(
        providers=frozenset({"twilio"}),
        webhook_secret=SECRET,
        public_base_url=BASE,
        twilio_auth_token="twilio-auth-token",
    )
    values.update(overrides)
    return TelephonySettings(**values)


def _incoming_call_event() -> list[dict[str, Any]]:
    return [
        {
            "eventType": "Microsoft.Communication.IncomingCall",
            "data": {
                "incomingCallContext": "ctx-123",
                "from": {"kind": "phoneNumber", "rawId": "4:+15555550100", "phoneNumber": {"value": "+15555550100"}},
                "to": {"kind": "phoneNumber", "rawId": "4:+15555550101", "phoneNumber": {"value": "+15555550101"}},
            },
        }
    ]


def test_no_telephony_routes_by_default(repo_root, profile_path):
    client = TestClient(_app(repo_root, profile_path, TelephonySettings()))
    assert client.post("/telephony/acs/events").status_code == 404
    assert client.post("/telephony/twilio/voice").status_code == 404
    info = client.get("/api/info").json()
    assert info["telephony"] == []
    assert info["knowledge"] == "local"


def test_acs_event_grid_validation_and_secret(repo_root, profile_path):
    client = TestClient(_app(repo_root, profile_path, _acs_settings(), acs_client=FakeAcsClient()))
    validation = [{"eventType": "Microsoft.EventGrid.SubscriptionValidationEvent", "data": {"validationCode": "abc"}}]

    assert client.post("/telephony/acs/events", json=validation).status_code == 401
    assert client.post("/telephony/acs/events?secret=wrong", json=validation).status_code == 401
    response = client.post(f"/telephony/acs/events?secret={EG_SECRET}", json=validation)
    assert response.json() == {"validationResponse": "abc"}


def test_acs_incoming_call_is_answered_with_bidirectional_pcm24k(repo_root, profile_path):
    fake = FakeAcsClient()
    client = TestClient(_app(repo_root, profile_path, _acs_settings(), acs_client=fake))

    assert client.post(f"/telephony/acs/events?secret={EG_SECRET}", json=_incoming_call_event()).status_code == 200

    assert len(fake.answered) == 1
    answered = fake.answered[0]
    assert answered["context"] == "ctx-123"
    assert answered["callback_url"].startswith(f"{BASE}/telephony/acs/callbacks?token=")
    media = answered["media_streaming"]
    assert media.transport_url.startswith("wss://agent.example.test/telephony/acs/media?token=")
    assert media.enable_bidirectional is True
    assert str(media.audio_format.value) == "pcm24KMono"
    assert media.start_media_streaming is True


def test_acs_busy_call_goes_to_overflow_or_is_rejected(repo_root, profile_path):
    fake = FakeAcsClient()
    client = TestClient(
        _app(repo_root, profile_path, _acs_settings(overflow_number="+15555550199"), max_sessions=0, acs_client=fake)
    )
    client.app.state.session_hub.max_sessions = 1
    client.app.state.session_hub.active = 1

    client.post(f"/telephony/acs/events?secret={EG_SECRET}", json=_incoming_call_event())
    assert fake.answered == []
    assert fake.redirected and fake.redirected[0][0] == "ctx-123"

    fake2 = FakeAcsClient()
    client2 = TestClient(_app(repo_root, profile_path, _acs_settings(), acs_client=fake2))
    client2.app.state.session_hub.max_sessions = 1
    client2.app.state.session_hub.active = 1
    client2.post(f"/telephony/acs/events?secret={EG_SECRET}", json=_incoming_call_event())
    assert fake2.rejected == [("ctx-123", "busy")]


def test_acs_callbacks_require_a_long_lived_callback_token(repo_root, profile_path):
    client = TestClient(_app(repo_root, profile_path, _acs_settings(), acs_client=FakeAcsClient()))
    events = [{"type": "Microsoft.Communication.CallConnected", "data": {}}]
    # Callback tokens outlive the 5-minute media token so mid-call and hang-up events keep arriving.
    long_call = mint_call_token(SECRET, "acs-callback", "call-1", ttl_seconds=3600, now=time.time() - 1800)
    media_token = mint_call_token(SECRET, "acs-media", "call-1")
    assert client.post("/telephony/acs/callbacks?token=bad", json=events).status_code == 401
    assert client.post(f"/telephony/acs/callbacks?token={media_token}", json=events).status_code == 401
    assert client.post(f"/telephony/acs/callbacks?token={long_call}", json=events).status_code == 200


def test_acs_media_stream_round_trip_and_barge_in(repo_root, profile_path):
    PhoneTestBridge.received = []
    client = TestClient(_app(repo_root, profile_path, _acs_settings(), acs_client=FakeAcsClient()))
    token = mint_call_token(SECRET, "acs-media", "call-1")
    frame = base64.b64encode(np.arange(480, dtype="<i2").tobytes()).decode()

    with client.websocket_connect(f"/telephony/acs/media?token={token}") as ws:
        ws.send_text(json.dumps({"kind": "AudioMetadata", "audioMetadata": {"encoding": "PCM", "sampleRate": 24000}}))
        ws.send_text(json.dumps({"kind": "AudioData", "audioData": {"data": frame, "silent": False}}))
        played = json.loads(ws.receive_text())
        assert played == {"Kind": "AudioData", "AudioData": {"Data": frame}, "StopAudio": None}

        ws.send_text(json.dumps({"kind": "AudioData", "audioData": {"data": BARGE_IN_MARKER}}))
        assert json.loads(ws.receive_text())["Kind"] == "StopAudio"
        assert client.app.state.session_hub.active == 1

    assert PhoneTestBridge.received[0] == frame


def test_acs_media_rejects_bad_or_cross_purpose_tokens(repo_root, profile_path):
    client = TestClient(_app(repo_root, profile_path, _acs_settings(), acs_client=FakeAcsClient()))
    twilio_token = mint_call_token(SECRET, "twilio", "call-1")
    callback_token = mint_call_token(SECRET, "acs-callback", "call-1")
    for url in (
        "/telephony/acs/media",
        f"/telephony/acs/media?token={twilio_token}",
        f"/telephony/acs/media?token={callback_token}",
    ):
        with pytest.raises(Exception):
            with client.websocket_connect(url) as ws:
                ws.receive_text()


def test_eventgrid_secret_is_separate_from_token_signing_key(repo_root, profile_path):
    client = TestClient(_app(repo_root, profile_path, _acs_settings(), acs_client=FakeAcsClient()))
    validation = [{"eventType": "Microsoft.EventGrid.SubscriptionValidationEvent", "data": {"validationCode": "abc"}}]
    assert client.post(f"/telephony/acs/events?secret={SECRET}", json=validation).status_code == 401
    # Knowing the Event Grid secret does not let anyone mint a valid media token.
    forged = mint_call_token(EG_SECRET, "acs-media", "call-1")
    with pytest.raises(Exception):
        with client.websocket_connect(f"/telephony/acs/media?token={forged}") as ws:
            ws.receive_text()


def test_concurrent_acs_arrivals_reserve_atomically(repo_root, profile_path):
    fake = FakeAcsClient()
    client = TestClient(_app(repo_root, profile_path, _acs_settings(), max_sessions=1, acs_client=fake))
    hub = client.app.state.session_hub

    client.post(f"/telephony/acs/events?secret={EG_SECRET}", json=_incoming_call_event())
    client.post(f"/telephony/acs/events?secret={EG_SECRET}", json=_incoming_call_event())
    assert len(fake.answered) == 1
    assert fake.rejected == [("ctx-123", "busy")]
    assert hub.active == 1

    # Media for the answered call claims the reservation instead of taking a second slot.
    call_id = fake.answered[0]["operation_context"]
    media_url = fake.answered[0]["media_streaming"].transport_url.split("/telephony", 1)[1]
    with client.websocket_connect("/telephony" + media_url) as ws:
        ws.send_text(json.dumps({"kind": "AudioData", "audioData": {"data": "AAAA"}}))
        ws.receive_text()
        assert hub.active == 1
    assert call_id
    assert hub.active == 0


def test_failed_answer_releases_the_reservation(repo_root, profile_path):
    class FailingClient(FakeAcsClient):
        async def answer_call(self, context, callback_url, **kwargs):
            raise RuntimeError("answer failed")

    client = TestClient(_app(repo_root, profile_path, _acs_settings(), max_sessions=1, acs_client=FailingClient()))
    client.post(f"/telephony/acs/events?secret={EG_SECRET}", json=_incoming_call_event())
    assert client.app.state.session_hub.active == 0


def _signed_twilio_post(client, params: dict[str, str], token="twilio-auth-token"):
    url = f"{BASE}/telephony/twilio/voice"
    return client.post(
        "/telephony/twilio/voice",
        data=params,
        headers={"X-Twilio-Signature": twilio_signature(token, url, params)},
    )


def test_twilio_voice_webhook_validates_signature_and_returns_stream_twiml(repo_root, profile_path):
    client = TestClient(_app(repo_root, profile_path, _twilio_settings()))
    params = {"CallSid": "CA123", "From": "+15555550100", "To": "+15555550101"}

    assert client.post("/telephony/twilio/voice", data=params).status_code == 403
    assert _signed_twilio_post(client, params, token="wrong-token").status_code == 403

    response = _signed_twilio_post(client, params)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert '<Stream url="wss://agent.example.test/telephony/twilio/media">' in response.text
    assert '<Parameter name="token" value="' in response.text


def test_twilio_busy_twiml_dials_overflow(repo_root, profile_path):
    client = TestClient(_app(repo_root, profile_path, _twilio_settings(overflow_number="+15555550199")))
    client.app.state.session_hub.max_sessions = 1
    client.app.state.session_hub.active = 1
    response = _signed_twilio_post(client, {"CallSid": "CA1"})
    assert "<Say>" in response.text and "<Dial>+15555550199</Dial>" in response.text
    assert "<Stream" not in response.text


def test_twilio_media_stream_converts_mulaw_and_clears_on_barge_in(repo_root, profile_path):
    PhoneTestBridge.received = []
    client = TestClient(_app(repo_root, profile_path, _twilio_settings()))
    token = mint_call_token(SECRET, "twilio", "CA123")
    mulaw_silence = base64.b64encode(b"\xff" * 160).decode()

    with client.websocket_connect("/telephony/twilio/media") as ws:
        ws.send_text(json.dumps({"event": "connected", "protocol": "Call"}))
        ws.send_text(
            json.dumps(
                {
                    "event": "start",
                    "streamSid": "MZ1",
                    "start": {"callSid": "CA123", "customParameters": {"token": token}},
                }
            )
        )
        ws.send_text(json.dumps({"event": "media", "streamSid": "MZ1", "media": {"track": "inbound", "payload": mulaw_silence}}))
        played = json.loads(ws.receive_text())
        assert played["event"] == "media" and played["streamSid"] == "MZ1"
        assert 150 <= len(base64.b64decode(played["media"]["payload"])) <= 160

        ws.send_text(json.dumps({"event": "media", "streamSid": "MZ1", "media": {"payload": TWILIO_BARGE_IN_PAYLOAD}}))
        assert json.loads(ws.receive_text()) == {"event": "clear", "streamSid": "MZ1"}
        ws.send_text(json.dumps({"event": "stop", "streamSid": "MZ1"}))

    upsampled = base64.b64decode(PhoneTestBridge.received[0])
    assert len(upsampled) == 480 * 2  # 160 mu-law samples -> 480 PCM16 samples at 24 kHz
    assert client.app.state.session_hub.active == 0


def test_twilio_media_rejects_missing_token(repo_root, profile_path):
    client = TestClient(_app(repo_root, profile_path, _twilio_settings()))
    with client.websocket_connect("/telephony/twilio/media") as ws:
        ws.send_text(json.dumps({"event": "start", "streamSid": "MZ1", "start": {"customParameters": {}}}))
        with pytest.raises(Exception):
            ws.receive_text()
    assert client.app.state.session_hub.active == 0


def test_twilio_unauthenticated_socket_times_out(repo_root, profile_path):
    client = TestClient(_app(repo_root, profile_path, _twilio_settings(handshake_timeout_seconds=0.2)))
    with client.websocket_connect("/telephony/twilio/media") as ws:
        with pytest.raises(Exception):
            ws.receive_text()  # server closes after the handshake timeout without any "start"
    assert client.app.state.session_hub.active == 0


def test_twilio_webhook_reserves_and_media_claims_the_same_slot(repo_root, profile_path):
    client = TestClient(_app(repo_root, profile_path, _twilio_settings(), max_sessions=1))
    hub = client.app.state.session_hub
    first = _signed_twilio_post(client, {"CallSid": "CA-A"})
    assert "<Stream" in first.text and hub.active == 1
    second = _signed_twilio_post(client, {"CallSid": "CA-B"})
    assert "<Stream" not in second.text and "<Hangup/>" in second.text

    token = first.text.split('name="token" value="', 1)[1].split('"', 1)[0]
    with client.websocket_connect("/telephony/twilio/media") as ws:
        ws.send_text(json.dumps({"event": "start", "streamSid": "MZA", "start": {"customParameters": {"token": token}}}))
        ws.send_text(json.dumps({"event": "media", "media": {"payload": base64.b64encode(b"\xff" * 8).decode()}}))
        ws.receive_text()
        assert hub.active == 1
        ws.send_text(json.dumps({"event": "stop"}))
    assert hub.active == 0


def test_phone_and_browser_share_one_admission_counter(repo_root, profile_path):
    client = TestClient(_app(repo_root, profile_path, _twilio_settings(), max_sessions=1))
    token = mint_call_token(SECRET, "twilio", "CA9")
    with client.websocket_connect("/telephony/twilio/media") as phone:
        phone.send_text(json.dumps({"event": "start", "streamSid": "MZ9", "start": {"customParameters": {"token": token}}}))
        phone.send_text(json.dumps({"event": "media", "media": {"payload": base64.b64encode(b"\xff" * 8).decode()}}))
        phone.receive_text()
        with client.websocket_connect("/ws") as browser:
            assert browser.receive_json()["type"] == "busy"
        phone.send_text(json.dumps({"event": "stop"}))
