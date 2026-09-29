"""Twilio Programmable Voice + Media Streams adapter.

Works for any call that Twilio can hand to a TwiML webhook:

- a Twilio phone number whose Voice webhook is ``POST /telephony/twilio/voice``
- a Twilio **SIP Domain** with the same Voice URL - this is how an existing PBX
  (for example Asterisk with a SIP trunk to a Twilio SIP Domain) routes an
  extension, IVR option, or queue overflow to the agent over SIP.

The webhook validates ``X-Twilio-Signature`` and returns
``<Connect><Stream>`` TwiML. Twilio then opens ``WS /telephony/twilio/media``
and streams G.711 mu-law 8 kHz, which is converted to the bridge's PCM16
24 kHz at the edge. Barge-in sends Twilio's ``clear`` message.
"""

from __future__ import annotations

import asyncio
import json
import logging
from xml.sax.saxutils import escape, quoteattr

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from ..bridge import RealtimeStyleBridge
from ..sessions import SessionHub
from .audio import MulawTelephonyCodec
from .common import public_base_url, run_phone_session, websocket_base_url
from .security import mint_call_token, verify_call_token, verify_twilio_signature
from .settings import TelephonySettings

LOGGER = logging.getLogger("voiceagent.telephony.twilio")
PROVIDER = "twilio"
TWIML_MEDIA_TYPE = "application/xml"


def connect_stream_twiml(stream_url: str, token: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Connect>"
        f"<Stream url={quoteattr(stream_url)}>"
        f'<Parameter name="token" value={quoteattr(token)}/>'
        "</Stream></Connect></Response>"
    )


def busy_twiml(message: str, overflow_number: str | None) -> str:
    overflow = f"<Dial>{escape(overflow_number)}</Dial>" if overflow_number else "<Hangup/>"
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Say>{escape(message)}</Say>{overflow}</Response>'


def build_twilio_router(hub: SessionHub, settings: TelephonySettings) -> APIRouter:
    router = APIRouter(prefix="/telephony/twilio")

    @router.post("/voice")
    async def voice(request: Request) -> Response:
        form = await request.form()
        params = {key: str(value) for key, value in form.items()}
        base = public_base_url(request, settings)
        if not settings.twilio_skip_signature_validation:
            signed_url = f"{base}{request.url.path}"
            if request.url.query:
                signed_url += f"?{request.url.query}"
            if not verify_twilio_signature(
                settings.twilio_auth_token or "", signed_url, params, request.headers.get("x-twilio-signature")
            ):
                LOGGER.warning(json.dumps({"event": "twilio_signature_rejected"}))
                return Response(status_code=403)

        call_id = params.get("CallSid") or ""
        if not call_id:
            return Response(status_code=400)
        if not await hub.reserve(call_id, settings.reservation_ttl_seconds):
            LOGGER.info(json.dumps({"event": "twilio_call_busy", "overflow": bool(settings.overflow_number)}))
            return Response(busy_twiml(settings.busy_message, settings.overflow_number), media_type=TWIML_MEDIA_TYPE)

        token = mint_call_token(settings.webhook_secret, PROVIDER, call_id, settings.token_ttl_seconds)
        stream_url = f"{websocket_base_url(base)}/telephony/twilio/media"
        return Response(connect_stream_twiml(stream_url, token), media_type=TWIML_MEDIA_TYPE)

    # Caps sockets that are connected but not yet authenticated (the token only arrives in "start").
    handshakes = asyncio.Semaphore(settings.max_pending_handshakes)

    @router.websocket("/media")
    async def media(websocket: WebSocket) -> None:
        if handshakes.locked():
            await websocket.close(code=1013)
            return
        async with handshakes:
            await websocket.accept()
            try:
                stream_sid, call_id = await asyncio.wait_for(
                    _await_start(websocket, settings), timeout=settings.handshake_timeout_seconds
                )
            except asyncio.TimeoutError:
                stream_sid, call_id = None, None
        if stream_sid is None or call_id is None:
            await websocket.close(code=1008)
            return
        if not await hub.claim(call_id):
            await websocket.close(code=1013)
            return

        codec = MulawTelephonyCodec()

        async def send_audio(audio_b64: str) -> None:
            payload = codec.outbound(audio_b64)
            if payload:
                await websocket.send_text(
                    json.dumps({"event": "media", "streamSid": stream_sid, "media": {"payload": payload}})
                )

        async def flush() -> None:
            await websocket.send_text(json.dumps({"event": "clear", "streamSid": stream_sid}))

        async def inbound(bridge: RealtimeStyleBridge) -> None:
            try:
                while True:
                    message = json.loads(await websocket.receive_text())
                    if not isinstance(message, dict):
                        continue
                    event = message.get("event")
                    if event == "media":
                        media_block = message.get("media") or {}
                        if media_block.get("track", "inbound") != "inbound":
                            continue
                        payload = media_block.get("payload")
                        if isinstance(payload, str) and payload:
                            await bridge.send_audio(codec.inbound(payload))
                    elif event == "stop":
                        return
            except WebSocketDisconnect:
                return

        try:
            await run_phone_session(hub, "twilio", call_id, send_audio=send_audio, flush=flush, inbound=inbound)
        finally:
            try:
                await websocket.close()
            except Exception:
                LOGGER.debug("Twilio media socket already closed", exc_info=True)

    return router


async def _await_start(websocket: WebSocket, settings: TelephonySettings) -> tuple[str | None, str | None]:
    """Read ``connected``/``start`` and validate the per-call token from ``customParameters``."""

    try:
        for _ in range(5):
            message = json.loads(await websocket.receive_text())
            if not isinstance(message, dict):
                continue
            if message.get("event") != "start":
                continue
            start = message.get("start") or {}
            params = start.get("customParameters") or {}
            call_id = verify_call_token(settings.webhook_secret, PROVIDER, params.get("token"))
            if call_id is None:
                LOGGER.warning(json.dumps({"event": "twilio_stream_token_rejected"}))
                return None, None
            stream_sid = message.get("streamSid") or start.get("streamSid")
            return (str(stream_sid) if stream_sid else None), call_id
    except (WebSocketDisconnect, json.JSONDecodeError):
        return None, None
    return None, None
