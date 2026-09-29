"""FastAPI app factory for browser voice-agent demos.

Browser -> server messages:
``{"type":"audio","audio":"<base64 PCM16 mono 24 kHz>"}``,
``{"type":"text","text":"..."}``, and ``{"type":"interrupt"}``.

Server -> browser messages:
``{"type":"ready","api","model","voice","assistant_name"}``,
``{"type":"audio","audio":"<b64>"}``, ``{"type":"speech_started"}``,
``{"type":"interrupted"}`` (flush playback after a typed barge-in),
``{"type":"transcript","role":"user"|"assistant","text","final"}``,
``{"type":"tool_call","name","arguments","result"}``,
``{"type":"metrics","turn","session"}``, ``{"type":"busy","message"}``,
and ``{"type":"error","message"}``.

Phone calls reach the same bridge through the optional telephony adapters in
``voiceagent_core.telephony`` (ACS Call Automation and Twilio Media Streams),
enabled with ``TELEPHONY_PROVIDERS``. All channels share one admission counter.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import rag
from .bridge import RealtimeStyleBridge
from .profile import load_profile
from .sessions import BUSY_MESSAGE, BridgeFactory, SessionHub, pump
from .settings import CommonSettings
from .telephony import TelephonySettings, mount_telephony
from .tools import ToolRegistry

LOGGER = logging.getLogger("voiceagent.server")

__all__ = ["BridgeFactory", "create_app"]


def create_app(
    bridge_factory: BridgeFactory,
    settings: CommonSettings,
    telephony_settings: TelephonySettings | None = None,
    *,
    acs_client_factory: Any = None,
) -> FastAPI:
    profile = load_profile(settings.agent_profile_path)
    tools = ToolRegistry.from_profile(profile)
    app = FastAPI(title="Reusable Voice Agent Demo")
    app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")
    app.router.on_shutdown.append(rag.close)

    hub = SessionHub(bridge_factory, profile, tools, settings.max_concurrent_sessions)
    app.state.session_hub = hub

    telephony = telephony_settings if telephony_settings is not None else TelephonySettings.from_env()
    mount_telephony(app, hub, telephony, acs_client_factory=acs_client_factory)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(settings.static_dir / "index.html")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/info")
    async def api_info() -> dict[str, Any]:
        return {**hub.info(), "telephony": sorted(telephony.providers), "knowledge": rag.describe_backend()}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()

        if not await hub.try_acquire():
            await websocket.send_json({"type": "busy", "message": BUSY_MESSAGE})
            await websocket.close(code=1013)
            return

        async def emit(message: dict[str, Any]) -> None:
            await websocket.send_json(message)

        bridge: RealtimeStyleBridge | None = None
        metrics = None
        session_id = ""
        try:
            bridge, metrics, session_id = hub.new_session(emit)
            hub.log_start(session_id, bridge.api_name, "browser")
            try:
                await bridge.connect()
            except Exception as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
                await websocket.close(code=1011)
                return

            await websocket.send_json({"type": "ready", **hub.info()})

            for exc in await pump(_browser_to_bridge(websocket, bridge), bridge):
                if not isinstance(exc, WebSocketDisconnect):
                    await _safe_send_error(websocket, str(exc))
        finally:
            try:
                if bridge is not None:
                    await bridge.close()
            except Exception:
                LOGGER.warning("Bridge close failed", exc_info=True)
            finally:
                await hub.release()
                if bridge is not None and metrics is not None:
                    hub.log_end(session_id, bridge.api_name, "browser", metrics)
                await _safe_close(websocket)

    return app


async def _safe_close(websocket: WebSocket) -> None:
    """Close the browser socket once the upstream session ends (no-op if already closed)."""

    try:
        await websocket.close(code=1000)
    except Exception:
        LOGGER.debug("Browser WebSocket already closed", exc_info=True)


async def _browser_to_bridge(websocket: WebSocket, bridge: RealtimeStyleBridge) -> None:
    async for raw in websocket.iter_text():
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            await websocket.send_json({"type": "error", "message": "Client message was not valid JSON"})
            continue
        if not isinstance(message, dict):
            await websocket.send_json({"type": "error", "message": "Client message must be a JSON object"})
            continue

        message_type = message.get("type")
        if message_type == "audio":
            audio = message.get("audio")
            if isinstance(audio, str):
                await bridge.send_audio(audio)
        elif message_type == "text":
            text = message.get("text")
            if isinstance(text, str) and text.strip():
                await bridge.send_text(text)
        elif message_type == "interrupt":
            await bridge.interrupt()
        else:
            await websocket.send_json({"type": "error", "message": f"Unknown client message type: {message_type}"})


async def _safe_send_error(websocket: WebSocket, message: str) -> None:
    try:
        await websocket.send_json({"type": "error", "message": message})
    except Exception:
        LOGGER.debug("Could not send WebSocket error to client", exc_info=True)
