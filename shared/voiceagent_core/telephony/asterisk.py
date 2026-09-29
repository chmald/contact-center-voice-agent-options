"""Asterisk WebSocket media adapter (``chan_websocket``).

Asterisk 20.16+, 21.11+, 22.6+ and 23 can dial an extension to ``WebSocket/<client>/...``
and open an **outbound** WSS connection to this app, streaming raw call audio as BINARY
frames and control messages as TEXT frames (plain text or JSON). This adapter accepts
those connections at ``WS /telephony/asterisk/media`` and feeds the shared bridge:

- Auth: HTTP Basic (``username``/``password`` in ``websocket_client.conf``; the password
  must equal ``ASTERISK_WEBSOCKET_SECRET``) or ``?secret=`` added with the ``v()`` dial option.
- Codecs: ``slin24`` (PCM16 24 kHz - the bridge's format, no conversion, recommended),
  ``ulaw`` (8 kHz), and ``slin`` (PCM16 8 kHz). Others are rejected with ``HANGUP``.
- Agent audio is sent between ``START_MEDIA_BUFFERING`` / ``STOP_MEDIA_BUFFERING`` so
  Asterisk re-frames and re-times it; barge-in sends ``FLUSH_MEDIA``.
- One admission slot per call; when all slots are busy the call is hung up so the
  dialplan can continue to an overflow destination.

Reference: https://docs.asterisk.org/Configuration/Channel-Drivers/WebSocket/
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..bridge import RealtimeStyleBridge
from ..sessions import SessionHub
from .audio import Downsampler3x, MulawTelephonyCodec, Upsampler3x, array_to_pcm16_b64, pcm16_b64_to_array
from .common import run_phone_session
from .security import secrets_match
from .settings import TelephonySettings

LOGGER = logging.getLogger("voiceagent.telephony.asterisk")

# chan_websocket closes the socket (and hangs up) on messages over 65500 bytes; stay below it
# on a 20 ms frame boundary for slin24 (960 bytes per frame).
MAX_BINARY_BYTES = 960 * 67


class AsteriskCodec:
    """Convert between an Asterisk channel format and the bridge's base64 PCM16 24 kHz."""

    SUPPORTED = ("slin24", "ulaw", "slin")

    def __init__(self, fmt: str):
        self.fmt = fmt
        self._mulaw = MulawTelephonyCodec() if fmt == "ulaw" else None
        self._up = Upsampler3x() if fmt == "slin" else None
        self._down = Downsampler3x() if fmt == "slin" else None

    def to_bridge(self, data: bytes) -> str:
        if self.fmt == "slin24":
            return base64.b64encode(data[: len(data) - len(data) % 2]).decode("ascii")
        if self._mulaw is not None:
            return self._mulaw.inbound(base64.b64encode(data).decode("ascii"))
        import numpy as np

        samples = np.frombuffer(data[: len(data) - len(data) % 2], dtype="<i2")
        return array_to_pcm16_b64(self._up.process(samples))

    def to_asterisk(self, pcm24k_b64: str) -> bytes:
        if self.fmt == "slin24":
            return base64.b64decode(pcm24k_b64)
        if self._mulaw is not None:
            return base64.b64decode(self._mulaw.outbound(pcm24k_b64))
        return self._down.process(pcm16_b64_to_array(pcm24k_b64)).astype("<i2").tobytes()


def parse_control(text: str) -> tuple[dict[str, Any], bool]:
    """Parse a chan_websocket TEXT frame. Returns (fields, is_json)."""

    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            return (data if isinstance(data, dict) else {}), True
        except json.JSONDecodeError:
            return {}, True
    parts = stripped.split()
    if not parts:
        return {}, False
    fields: dict[str, Any] = {"event": parts[0]}
    for part in parts[1:]:
        key, sep, value = part.partition(":")
        if sep:
            fields[key] = value
    return fields, False


def _authorized(websocket: WebSocket, settings: TelephonySettings) -> bool:
    secret = settings.asterisk_websocket_secret
    if secrets_match(secret, websocket.query_params.get("secret")):
        return True
    header = websocket.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            _, _, password = base64.b64decode(header[6:].strip()).decode("utf-8").partition(":")
        except (ValueError, UnicodeDecodeError):
            return False
        return secrets_match(secret, password)
    return False


def build_asterisk_router(hub: SessionHub, settings: TelephonySettings) -> APIRouter:
    router = APIRouter(prefix="/telephony/asterisk")

    @router.websocket("/media")
    async def media(websocket: WebSocket) -> None:
        if not _authorized(websocket, settings):
            LOGGER.warning(json.dumps({"event": "asterisk_auth_rejected"}))
            await websocket.close(code=1008)
            return
        # Echo the subprotocol Asterisk asked for (websocket_client.conf "protocols"), if any.
        offered = [p.strip() for p in websocket.headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
        await websocket.accept(subprotocol=offered[0] if offered else None)

        state: dict[str, Any] = {"json": True, "buffering": False}

        async def command(name: str, **params: Any) -> None:
            if state["json"]:
                await websocket.send_text(json.dumps({"command": name, **params}))
            else:
                await websocket.send_text(" ".join([name, *[str(v) for v in params.values()]]))

        start = await _await_media_start(websocket, settings, state)
        if start is None:
            await websocket.close(code=1008)
            return
        fmt = str(start.get("format") or "").lower()
        call_id = str(start.get("channel_id") or start.get("connection_id") or "unknown")
        if fmt not in AsteriskCodec.SUPPORTED:
            LOGGER.warning(json.dumps({"event": "asterisk_unsupported_format", "format": fmt, "call_id": call_id}))
            await command("HANGUP")
            await websocket.close(code=1003)
            return
        if not await hub.try_acquire():
            LOGGER.info(json.dumps({"event": "asterisk_call_busy", "call_id": call_id}))
            await command("HANGUP")
            await websocket.close(code=1013)
            return

        codec = AsteriskCodec(fmt)

        async def send_audio(audio_b64: str) -> None:
            if not state["buffering"]:
                await command("START_MEDIA_BUFFERING")
                state["buffering"] = True
            data = codec.to_asterisk(audio_b64)
            for offset in range(0, len(data), MAX_BINARY_BYTES):
                await websocket.send_bytes(data[offset : offset + MAX_BINARY_BYTES])

        async def flush() -> None:
            # FLUSH_MEDIA also ends any bulk transfer in progress.
            await command("FLUSH_MEDIA")
            state["buffering"] = False

        async def turn_end() -> None:
            if state["buffering"]:
                await command("STOP_MEDIA_BUFFERING", correlation_id=call_id)
                state["buffering"] = False

        async def inbound(bridge: RealtimeStyleBridge) -> None:
            try:
                while True:
                    message = await websocket.receive()
                    if message.get("type") == "websocket.disconnect":
                        return
                    if message.get("bytes"):
                        await bridge.send_audio(codec.to_bridge(message["bytes"]))
                        continue
                    fields, _ = parse_control(message.get("text") or "")
                    event = fields.get("event")
                    if event in {"MEDIA_XOFF", "MEDIA_XON"}:
                        LOGGER.info(json.dumps({"event": "asterisk_flow_control", "call_id": call_id, "state": event}))
                    elif event == "DTMF_END":
                        LOGGER.info(json.dumps({"event": "asterisk_dtmf", "call_id": call_id, "digit": fields.get("digit")}))
            except WebSocketDisconnect:
                return

        try:
            await run_phone_session(
                hub, "asterisk", call_id, send_audio=send_audio, flush=flush, inbound=inbound, on_turn_end=turn_end
            )
        finally:
            try:
                await websocket.close()
            except Exception:
                LOGGER.debug("Asterisk media socket already closed", exc_info=True)

    return router


async def _await_media_start(websocket: WebSocket, settings: TelephonySettings, state: dict[str, Any]) -> dict[str, Any] | None:
    """Wait for MEDIA_START (first TEXT frame) within the handshake timeout."""

    import asyncio

    try:
        async with asyncio.timeout(settings.handshake_timeout_seconds):
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    return None
                text = message.get("text")
                if not text:
                    continue  # media before MEDIA_START is not expected; ignore it
                fields, is_json = parse_control(text)
                if fields.get("event") == "MEDIA_START":
                    state["json"] = is_json
                    return fields
    except (TimeoutError, WebSocketDisconnect):
        return None
