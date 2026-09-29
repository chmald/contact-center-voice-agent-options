"""Provider-neutral phone-call session runner and URL helpers."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.requests import HTTPConnection

from ..bridge import RealtimeStyleBridge
from ..sessions import SessionHub, pump
from .settings import TelephonySettings

LOGGER = logging.getLogger("voiceagent.telephony")

SendAudio = Callable[[str], Awaitable[None]]
Flush = Callable[[], Awaitable[None]]
Inbound = Callable[[RealtimeStyleBridge], Awaitable[None]]
TurnEnd = Callable[[], Awaitable[None]]


def public_base_url(connection: HTTPConnection, settings: TelephonySettings) -> str:
    """Public https base URL the phone platform should call back on.

    ``PUBLIC_BASE_URL`` wins (set by the Bicep from the Container Apps domain);
    otherwise it is reconstructed from forwarded headers for local tunnels.
    """

    if settings.public_base_url:
        return settings.public_base_url
    headers = connection.headers
    scheme = (headers.get("x-forwarded-proto") or connection.url.scheme or "https").split(",")[0].strip()
    if scheme in {"ws", "wss"}:
        scheme = "https" if scheme == "wss" else "http"
    host = (headers.get("x-forwarded-host") or headers.get("host") or connection.url.netloc).split(",")[0].strip()
    return f"{scheme}://{host}"


def websocket_base_url(http_base: str) -> str:
    if http_base.startswith("https://"):
        return "wss://" + http_base[len("https://") :]
    if http_base.startswith("http://"):
        return "ws://" + http_base[len("http://") :]
    return http_base


async def run_phone_session(
    hub: SessionHub,
    channel: str,
    call_id: str,
    *,
    send_audio: SendAudio,
    flush: Flush,
    inbound: Inbound,
    on_turn_end: TurnEnd | None = None,
) -> None:
    """Connect a bridge for an already-admitted phone call and pump audio both ways.

    The caller acquires a ``SessionHub`` slot first; this function always releases it.
    Bridge events map onto the phone: ``audio`` -> play, ``speech_started`` /
    ``interrupted`` -> flush queued playback (barge-in). Transcripts are logged at
    DEBUG only because they can contain caller PII.
    """

    async def emit(message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "audio":
            audio = message.get("audio")
            if isinstance(audio, str) and audio:
                await send_audio(audio)
        elif kind in {"speech_started", "interrupted"}:
            await flush()
        elif kind == "metrics" and on_turn_end is not None:
            # A response finished; lets adapters close out buffered playback (e.g. Asterisk).
            await on_turn_end()
        elif kind == "tool_call":
            LOGGER.info(json.dumps({"event": "phone_tool_call", "channel": channel, "call_id": call_id, "tool": message.get("name")}))
        elif kind == "error":
            LOGGER.warning(json.dumps({"event": "phone_bridge_error", "channel": channel, "call_id": call_id, "message": message.get("message")}))
        elif kind == "transcript" and message.get("final"):
            LOGGER.debug(json.dumps({"event": "phone_transcript", "channel": channel, "call_id": call_id, "role": message.get("role"), "text": message.get("text")}))

    bridge = None
    metrics = None
    session_id = ""
    try:
        bridge, metrics, session_id = hub.new_session(emit)
        hub.log_start(session_id, bridge.api_name, channel, call_id=call_id)
        await bridge.connect()
        for exc in await pump(inbound(bridge), bridge):
            LOGGER.info(json.dumps({"event": "phone_session_stopped", "channel": channel, "call_id": call_id, "reason": type(exc).__name__}))
    except Exception as exc:
        LOGGER.warning(json.dumps({"event": "phone_session_failed", "channel": channel, "call_id": call_id, "error": str(exc)}))
    finally:
        try:
            if bridge is not None:
                await bridge.close()
        except Exception:
            LOGGER.warning("Bridge close failed", exc_info=True)
        finally:
            await hub.release()
            if bridge is not None and metrics is not None:
                hub.log_end(session_id, bridge.api_name, channel, metrics, call_id=call_id)
