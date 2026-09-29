"""Azure Communication Services (ACS) Call Automation adapter.

Flow for an inbound PSTN call to an ACS phone number (or a Direct Routing
trunk from an existing SBC / contact-center platform):

1. Event Grid delivers ``Microsoft.Communication.IncomingCall`` to
   ``POST /telephony/acs/events?secret=<ACS_EVENTGRID_SECRET>``. A session slot is
   reserved atomically here; if none is free the call goes to overflow/busy.
2. The app answers with bidirectional media streaming over WebSocket in
   ``pcm24KMono`` - the bridge's native format, so no resampling.
3. ACS opens ``WS /telephony/acs/media?token=<per-call token>``; audio frames
   go to the shared bridge and agent audio comes back as ``AudioData``.
   Barge-in sends ``StopAudio`` so queued agent speech stops immediately.

When every slot is taken, the call is redirected to
``TELEPHONY_OVERFLOW_NUMBER`` (the human queue) or rejected as busy.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

from ..bridge import RealtimeStyleBridge
from ..sessions import SessionHub
from .common import public_base_url, run_phone_session, websocket_base_url
from .security import mint_call_token, secrets_match, verify_call_token
from .settings import TelephonySettings

LOGGER = logging.getLogger("voiceagent.telephony.acs")

VALIDATION_EVENT = "Microsoft.EventGrid.SubscriptionValidationEvent"
INCOMING_CALL_EVENT = "Microsoft.Communication.IncomingCall"
# Token purposes: the short-lived media token and the call-length callback token are not interchangeable.
MEDIA_PURPOSE = "acs-media"
CALLBACK_PURPOSE = "acs-callback"

AcsClientFactory = Callable[[], Any]


def default_acs_client_factory(settings: TelephonySettings) -> AcsClientFactory:
    """Lazily build one async ``CallAutomationClient`` (managed identity preferred)."""

    client: Any = None

    def factory() -> Any:
        nonlocal client
        if client is None:
            from azure.communication.callautomation.aio import CallAutomationClient

            if settings.acs_connection_string:
                client = CallAutomationClient.from_connection_string(settings.acs_connection_string)
            else:
                from azure.identity.aio import DefaultAzureCredential

                kwargs = {"managed_identity_client_id": settings.azure_client_id} if settings.azure_client_id else {}
                client = CallAutomationClient(settings.acs_endpoint, DefaultAzureCredential(**kwargs))
        return client

    return factory


def _media_streaming_options(transport_url: str) -> Any:
    from azure.communication.callautomation import (
        AudioFormat,
        MediaStreamingAudioChannelType,
        MediaStreamingContentType,
        MediaStreamingOptions,
        StreamingTransportType,
    )

    return MediaStreamingOptions(
        transport_url=transport_url,
        transport_type=StreamingTransportType.WEBSOCKET,
        content_type=MediaStreamingContentType.AUDIO,
        audio_channel_type=MediaStreamingAudioChannelType.MIXED,
        start_media_streaming=True,
        enable_bidirectional=True,
        audio_format=AudioFormat.PCM24_K_MONO,
    )


def _phone_identifier(number: str) -> Any:
    from azure.communication.callautomation import PhoneNumberIdentifier

    return PhoneNumberIdentifier(number)


def _caller(data: dict[str, Any]) -> str:
    source = data.get("from") if isinstance(data.get("from"), dict) else {}
    phone = source.get("phoneNumber") if isinstance(source.get("phoneNumber"), dict) else {}
    return str(phone.get("value") or source.get("rawId") or "unknown")


def audio_out_message(audio_b64: str) -> dict[str, Any]:
    return {"Kind": "AudioData", "AudioData": {"Data": audio_b64}, "StopAudio": None}


STOP_AUDIO_MESSAGE: dict[str, Any] = {"Kind": "StopAudio", "AudioData": None, "StopAudio": {}}


def build_acs_router(
    hub: SessionHub,
    settings: TelephonySettings,
    client_factory: AcsClientFactory | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/telephony/acs")
    get_client = client_factory or default_acs_client_factory(settings)

    @router.post("/events")
    async def events(request: Request) -> Response:
        if not secrets_match(settings.acs_eventgrid_secret, request.query_params.get("secret")):
            return Response(status_code=401)
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return Response(status_code=400)
        events_list = payload if isinstance(payload, list) else [payload]

        for event in events_list:
            if not isinstance(event, dict):
                continue
            event_type = event.get("eventType") or event.get("type")
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            if event_type == VALIDATION_EVENT:
                return JSONResponse({"validationResponse": data.get("validationCode")})
            if event_type == INCOMING_CALL_EVENT:
                await _handle_incoming_call(request, data)
        return Response(status_code=200)

    async def _handle_incoming_call(request: Request, data: dict[str, Any]) -> None:
        context = data.get("incomingCallContext")
        if not isinstance(context, str) or not context:
            return
        client = get_client()
        caller = _caller(data)
        call_id = str(uuid.uuid4())
        if not await hub.reserve(call_id, settings.reservation_ttl_seconds):
            LOGGER.info(json.dumps({"event": "acs_call_busy", "overflow": bool(settings.overflow_number)}))
            try:
                if settings.overflow_number:
                    await client.redirect_call(context, _phone_identifier(settings.overflow_number))
                else:
                    await client.reject_call(context, call_reject_reason="busy")
            except Exception as exc:
                LOGGER.warning(json.dumps({"event": "acs_busy_handling_failed", "error": str(exc)}))
            return

        media_token = mint_call_token(settings.webhook_secret, MEDIA_PURPOSE, call_id, settings.token_ttl_seconds)
        callback_token = mint_call_token(
            settings.webhook_secret, CALLBACK_PURPOSE, call_id, settings.callback_token_ttl_seconds
        )
        base = public_base_url(request, settings)
        callback_url = f"{base}/telephony/acs/callbacks?token={callback_token}"
        transport_url = f"{websocket_base_url(base)}/telephony/acs/media?token={media_token}"
        try:
            await client.answer_call(
                context,
                callback_url,
                operation_context=call_id,
                media_streaming=_media_streaming_options(transport_url),
            )
            LOGGER.info(json.dumps({"event": "acs_call_answered", "call_id": call_id}))
            LOGGER.debug(json.dumps({"event": "acs_call_caller", "call_id": call_id, "caller": caller}))
        except Exception as exc:
            await hub.cancel_reservation(call_id)
            LOGGER.warning(json.dumps({"event": "acs_answer_failed", "call_id": call_id, "error": str(exc)}))

    @router.post("/callbacks")
    async def callbacks(request: Request) -> Response:
        call_id = verify_call_token(settings.webhook_secret, CALLBACK_PURPOSE, request.query_params.get("token"))
        if call_id is None:
            return Response(status_code=401)
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return Response(status_code=400)
        for event in payload if isinstance(payload, list) else [payload]:
            if isinstance(event, dict):
                event_type = str(event.get("type") or event.get("eventType") or "")
                level = logging.WARNING if event_type.endswith("Failed") else logging.INFO
                LOGGER.log(level, json.dumps({"event": "acs_callback", "call_id": call_id, "type": event_type}))
        return Response(status_code=200)

    @router.websocket("/media")
    async def media(websocket: WebSocket) -> None:
        call_id = verify_call_token(settings.webhook_secret, MEDIA_PURPOSE, websocket.query_params.get("token"))
        if call_id is None:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        if not await hub.claim(call_id):
            await websocket.close(code=1013)
            await _hang_up(websocket.headers.get("x-ms-call-connection-id"))
            return

        async def send_audio(audio_b64: str) -> None:
            await websocket.send_text(json.dumps(audio_out_message(audio_b64)))

        async def flush() -> None:
            await websocket.send_text(json.dumps(STOP_AUDIO_MESSAGE))

        async def inbound(bridge: RealtimeStyleBridge) -> None:
            try:
                while True:
                    message = json.loads(await websocket.receive_text())
                    if not isinstance(message, dict):
                        continue
                    kind = str(message.get("kind") or message.get("Kind") or "")
                    if kind == "AudioData":
                        audio = message.get("audioData") or message.get("AudioData") or {}
                        data = audio.get("data") or audio.get("Data")
                        if isinstance(data, str) and data:
                            await bridge.send_audio(data)
                    elif kind == "AudioMetadata":
                        meta = message.get("audioMetadata") or {}
                        if meta.get("sampleRate") not in (None, 24000):
                            LOGGER.warning(json.dumps({"event": "acs_unexpected_sample_rate", "call_id": call_id, "sample_rate": meta.get("sampleRate")}))
            except WebSocketDisconnect:
                return

        try:
            await run_phone_session(hub, "acs", call_id, send_audio=send_audio, flush=flush, inbound=inbound)
        finally:
            try:
                await websocket.close()
            except Exception:
                LOGGER.debug("ACS media socket already closed", exc_info=True)

    async def _hang_up(call_connection_id: str | None) -> None:
        if not call_connection_id:
            return
        try:
            await get_client().get_call_connection(call_connection_id).hang_up(is_for_everyone=True)
        except Exception as exc:
            LOGGER.warning(json.dumps({"event": "acs_hang_up_failed", "error": str(exc)}))

    return router
