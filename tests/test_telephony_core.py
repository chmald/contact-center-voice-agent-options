from __future__ import annotations

import base64

import numpy as np
import pytest

from voiceagent_core.telephony.audio import (
    Downsampler3x,
    MulawTelephonyCodec,
    Upsampler3x,
    array_to_pcm16_b64,
    pcm16_b64_to_array,
    ulaw_decode,
    ulaw_encode,
)
from voiceagent_core.telephony.security import (
    mint_call_token,
    secrets_match,
    twilio_signature,
    verify_call_token,
    verify_twilio_signature,
)
from voiceagent_core.telephony.settings import TelephonySettings

SECRET = "s" * 32


def test_ulaw_known_codes_and_round_trip():
    assert ulaw_encode(np.array([0], dtype=np.int16)) == b"\xff"
    assert ulaw_decode(b"\xff")[0] == 0
    assert ulaw_decode(b"\x80")[0] == 32124
    assert ulaw_decode(b"\x00")[0] == -32124

    samples = np.array([-32768, -12000, -1000, -50, 0, 50, 1000, 12000, 32767], dtype=np.int16)
    decoded = ulaw_decode(ulaw_encode(samples)).astype(np.int32)
    error = np.abs(decoded - samples.astype(np.int32))
    # mu-law quantisation error stays within a few percent of the magnitude (plus a small floor).
    assert np.all(error <= np.maximum(np.abs(samples.astype(np.int32)) * 0.07, 16) + 700 * (np.abs(samples) > 32000))


def test_resamplers_keep_rate_ratio_across_uneven_chunks():
    up = Upsampler3x()
    assert up.process(np.ones(160, dtype=np.int16)).size == 480

    down = Downsampler3x()
    total = sum(down.process(np.zeros(size, dtype=np.int16)).size for size in (100, 101, 479, 7, 2))
    assert total == (100 + 101 + 479 + 7 + 2 + 2) // 3


def test_downsampler_passes_speech_band_and_rejects_aliasing_tone():
    rate = 24000
    t = np.arange(rate) / rate
    speech_band = (8000 * np.sin(2 * np.pi * 1000 * t)).astype(np.int16)
    alias_tone = (8000 * np.sin(2 * np.pi * 7000 * t)).astype(np.int16)

    kept = Downsampler3x().process(speech_band)[200:]
    removed = Downsampler3x().process(alias_tone)[200:]
    assert np.sqrt(np.mean(kept.astype(float) ** 2)) > 5000
    assert np.sqrt(np.mean(removed.astype(float) ** 2)) < 800


def test_mulaw_codec_converts_both_directions():
    codec = MulawTelephonyCodec()
    phone_frame = base64.b64encode(b"\xff" * 160).decode()  # 20 ms of silence at 8 kHz
    to_bridge = pcm16_b64_to_array(codec.inbound(phone_frame))
    assert to_bridge.size == 480  # 20 ms at 24 kHz

    bridge_frame = array_to_pcm16_b64(np.zeros(480, dtype=np.int16))
    to_phone = base64.b64decode(codec.outbound(bridge_frame))
    assert 150 <= len(to_phone) <= 160


def test_call_tokens_are_bound_to_provider_call_and_expiry():
    token = mint_call_token(SECRET, "acs", "call-1", ttl_seconds=60, now=1000)
    assert verify_call_token(SECRET, "acs", token, now=1030) == "call-1"
    assert verify_call_token(SECRET, "twilio", token, now=1030) is None
    assert verify_call_token(SECRET, "acs", token, now=2000) is None
    assert verify_call_token("x" * 32, "acs", token, now=1030) is None
    assert verify_call_token(SECRET, "acs", token.replace(".", "x", 1), now=1030) is None
    assert verify_call_token(SECRET, "acs", None) is None


def test_shared_secret_and_twilio_signature():
    assert secrets_match(SECRET, SECRET)
    assert not secrets_match(SECRET, "wrong")
    assert not secrets_match("", "")

    url = "https://agent.example.test/telephony/twilio/voice"
    params = {"CallSid": "CA123", "From": "+15555550100", "To": "+15555550101"}
    signature = twilio_signature("token-abc", url, params)
    assert verify_twilio_signature("token-abc", url, params, signature)
    assert not verify_twilio_signature("token-abc", url + "?x=1", params, signature)
    assert not verify_twilio_signature("token-abc", url, {**params, "From": "+1"}, signature)


def test_telephony_settings_validation(monkeypatch):
    assert TelephonySettings().enabled is False
    with pytest.raises(ValueError, match="unknown"):
        TelephonySettings(providers=frozenset({"pstn"}))
    with pytest.raises(ValueError, match="TELEPHONY_WEBHOOK_SECRET"):
        TelephonySettings(providers=frozenset({"acs"}), acs_endpoint="https://x")
    with pytest.raises(ValueError, match="ACS_ENDPOINT"):
        TelephonySettings(providers=frozenset({"acs"}), webhook_secret=SECRET)
    with pytest.raises(ValueError, match="ACS_EVENTGRID_SECRET"):
        TelephonySettings(providers=frozenset({"acs"}), webhook_secret=SECRET, acs_endpoint="https://x")
    with pytest.raises(ValueError, match="must differ"):
        TelephonySettings(
            providers=frozenset({"acs"}), webhook_secret=SECRET, acs_endpoint="https://x", acs_eventgrid_secret=SECRET
        )
    with pytest.raises(ValueError, match="TWILIO_AUTH_TOKEN"):
        TelephonySettings(providers=frozenset({"twilio"}), webhook_secret=SECRET)
    with pytest.raises(ValueError, match="E.164"):
        TelephonySettings(
            providers=frozenset({"twilio"}), webhook_secret=SECRET, twilio_auth_token="t", overflow_number="555"
        )

    monkeypatch.setenv("TELEPHONY_PROVIDERS", "ACS, twilio")
    monkeypatch.setenv("TELEPHONY_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("ACS_ENDPOINT", "https://acs.example.test")
    monkeypatch.setenv("ACS_EVENTGRID_SECRET", "e" * 32)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "t")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://agent.example.test/")
    settings = TelephonySettings.from_env()
    assert settings.providers == frozenset({"acs", "twilio"})
    assert settings.public_base_url == "https://agent.example.test"
