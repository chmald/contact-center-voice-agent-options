"""Generic realtime-style WebSocket bridge.

Browser -> server messages:
``{"type":"audio","audio":"<base64 PCM16 mono 24 kHz>"}``,
``{"type":"text","text":"..."}``, and ``{"type":"interrupt"}``.

Server -> browser messages:
``ready``, ``audio``, ``speech_started``, ``interrupted``, ``transcript``,
``tool_call``, ``metrics``, ``busy``, and ``error``. ``speech_started`` and
``interrupted`` both tell the client to flush queued playback (voice barge-in
detected by the server VAD, or a typed turn that cancelled the active response).
API-specific examples subclass ``RealtimeStyleBridge`` and override only the
URL, headers, session update, model label, and voice label hooks.
"""

from __future__ import annotations

import abc
import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

import websockets

from .metrics import SessionMetrics
from .profile import AgentProfile
from .tools import ToolRegistry

Emit = Callable[[dict[str, Any]], Awaitable[None]]

# Upstream errors that are expected side effects of barge-in and not worth showing.
BENIGN_ERROR_CODES = {"response_cancel_not_active"}


class RealtimeStyleBridge(abc.ABC):
    """Base bridge for OpenAI-realtime-compatible WebSocket protocols."""

    api_name: str = "realtime-compatible"
    EVENT_ALIASES: dict[str, tuple[str, ...]] = {
        "audio_delta": ("response.output_audio.delta", "response.audio.delta"),
        "assistant_transcript_delta": (
            "response.output_audio_transcript.delta",
            "response.audio_transcript.delta",
        ),
        "assistant_transcript_done": (
            "response.output_audio_transcript.done",
            "response.audio_transcript.done",
        ),
        "user_transcript_done": ("conversation.item.input_audio_transcription.completed",),
        "speech_started": ("input_audio_buffer.speech_started",),
        "speech_stopped": ("input_audio_buffer.speech_stopped",),
        "item_created": ("conversation.item.added", "conversation.item.created"),
        "function_args_done": ("response.function_call_arguments.done",),
        "response_created": ("response.created",),
        "response_done": ("response.done",),
        "session_ready": ("session.updated",),
        "session_created": ("session.created",),
        "error": ("error",),
    }

    def __init__(
        self,
        profile: AgentProfile,
        tools: ToolRegistry,
        emit: Emit,
        metrics: SessionMetrics,
        session_id: str,
    ):
        self.profile = profile
        self.tools = tools
        self.emit = emit
        self.metrics = metrics
        self.session_id = session_id
        self.ws: Any | None = None
        self._item_ids: list[str] = []
        self._active_response = False
        # Set when the next response.create must wait for the active response to finish
        # (after a tool call or a barge-in); the API rejects a second response.create
        # while one is active.
        self._pending_response_create = False
        self._discard_audio = False

    @abc.abstractmethod
    async def build_url(self) -> str:
        raise NotImplementedError

    @abc.abstractmethod
    async def build_headers(self) -> dict[str, str]:
        raise NotImplementedError

    @abc.abstractmethod
    def build_session_update(self) -> dict[str, Any] | None:
        """Return the session.update to send, or None when the service owns the session config."""
        raise NotImplementedError

    @abc.abstractmethod
    def model_label(self) -> str:
        raise NotImplementedError

    @abc.abstractmethod
    def voice_label(self) -> str:
        raise NotImplementedError

    def _is(self, event_type: str | None, logical_name: str) -> bool:
        return event_type in self.EVENT_ALIASES.get(logical_name, ())

    async def connect(self) -> None:
        """Open the upstream socket, configure the session, and optionally greet."""

        url = await self.build_url()
        headers = await self.build_headers()
        try:
            self.ws = await websockets.connect(url, additional_headers=headers, max_size=None)
        except TypeError:
            self.ws = await websockets.connect(url, extra_headers=headers, max_size=None)

        session_update = self.build_session_update()
        if session_update is not None:
            await self._send_upstream(session_update)
            await self._wait_for_session_ready()
        else:
            # Server-configured sessions (e.g. a Foundry voice agent) need no session.update;
            # the session is usable once the service announces it.
            await self._wait_for_session_ready(require_update=False)

        await self.send_greeting()

    async def send_greeting(self) -> None:
        """Speak the profile greeting once. Subclasses whose service owns the greeting override this."""

        if self.profile.greeting:
            await self._send_upstream(
                {
                    "type": "response.create",
                    "response": {
                        "instructions": f"Say this greeting exactly once: {self.profile.greeting}"
                    },
                }
            )
            self._active_response = True

    async def _wait_for_session_ready(self, require_update: bool = True) -> None:
        assert self.ws is not None
        deadline = time.monotonic() + 10
        saw_created = False
        while time.monotonic() < deadline:
            timeout = max(0.01, deadline - time.monotonic())
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
            except TimeoutError:
                if saw_created:
                    return
                raise TimeoutError("Timed out waiting for upstream session readiness")
            event = self._parse_event(raw)
            event_type = event.get("type")
            if self._is(event_type, "session_created"):
                saw_created = True
                if not require_update:
                    return
            if self._is(event_type, "session_ready"):
                return
            if self._is(event_type, "error"):
                message = self._error_message(event)
                raise RuntimeError(f"Upstream session setup failed: {message}")
            if not require_update and event_type == "conversation.created":
                return
            if not require_update and event_type not in (None, "error"):
                # Any other server event before session.created still means the socket is live;
                # hand it to the normal handler so nothing (e.g. greeting audio) is lost.
                await self.handle_event(event)
        if not saw_created:
            raise TimeoutError("Timed out waiting for upstream session readiness")

    async def send_audio(self, b64: str) -> None:
        await self._send_upstream({"type": "input_audio_buffer.append", "audio": b64})

    async def send_text(self, text: str) -> None:
        self.metrics.mark_turn_start()
        await self._send_upstream(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                },
            }
        )
        if self._active_response:
            # A typed turn while the assistant is still responding (e.g. during the
            # greeting) is a barge-in. The API rejects a second response.create while
            # one is active, so cancel it and create the new response on response.done.
            await self._barge_in()
            return
        await self._send_upstream({"type": "response.create"})
        self._active_response = True

    async def interrupt(self) -> None:
        if self._active_response:
            await self._barge_in(create_followup=False)

    async def _barge_in(self, create_followup: bool = True) -> None:
        await self._send_upstream({"type": "response.cancel"})
        self._discard_audio = True
        if create_followup:
            self._pending_response_create = True
        await self.emit({"type": "interrupted"})

    async def run(self) -> None:
        """Read upstream events until the socket closes."""

        assert self.ws is not None
        async for raw in self.ws:
            event = self._parse_event(raw)
            await self.handle_event(event)

    async def handle_event(self, event: dict[str, Any]) -> None:
        """Handle a single upstream event. Tests can call this without a socket."""

        event_type = event.get("type")
        if self._is(event_type, "audio_delta"):
            if self._discard_audio:
                return  # tail of a response the user just interrupted
            self.metrics.mark_first_audio()
            audio = event.get("delta") or event.get("audio")
            if audio:
                await self.emit({"type": "audio", "audio": audio})
            return

        if self._is(event_type, "assistant_transcript_delta"):
            text = event.get("delta") or event.get("transcript") or event.get("text") or ""
            await self.emit({"type": "transcript", "role": "assistant", "text": text, "final": False})
            return

        if self._is(event_type, "assistant_transcript_done"):
            text = event.get("transcript") or event.get("text") or ""
            await self.emit({"type": "transcript", "role": "assistant", "text": text, "final": True})
            return

        if self._is(event_type, "user_transcript_done"):
            text = event.get("transcript") or event.get("text") or ""
            await self.emit({"type": "transcript", "role": "user", "text": text, "final": True})
            return

        if self._is(event_type, "speech_started"):
            await self.emit({"type": "speech_started"})
            return

        if self._is(event_type, "speech_stopped"):
            self.metrics.mark_turn_start()
            return

        if self._is(event_type, "item_created"):
            item = event.get("item") if isinstance(event.get("item"), dict) else {}
            item_id = item.get("id") or event.get("item_id")
            if isinstance(item_id, str) and item_id:
                self._item_ids.append(item_id)
            return

        if self._is(event_type, "function_args_done"):
            await self._handle_tool_call(event)
            return

        if self._is(event_type, "response_created"):
            self._active_response = True
            return

        if self._is(event_type, "response_done"):
            self._active_response = False
            self._discard_audio = False
            if self._pending_response_create:
                # A tool call or a barge-in is waiting on this response to finish: count
                # its tokens toward the same user turn, then create the next response.
                self._pending_response_create = False
                self.metrics.add_usage(event)
                await self._send_upstream({"type": "response.create"})
                self._active_response = True
                return
            turn = self.metrics.finish_turn(event)
            await self.emit(
                {
                    "type": "metrics",
                    "turn": turn,
                    "session": self.metrics.session_summary(),
                }
            )
            self.metrics.log_turn(self.api_name)
            await self._trim_history()
            return

        if self._is(event_type, "error"):
            error = event.get("error") if isinstance(event.get("error"), dict) else {}
            if error.get("code") in BENIGN_ERROR_CODES:
                return  # e.g. a cancel that raced the natural end of a response
            await self.emit({"type": "error", "message": self._error_message(event)})

    async def close(self) -> None:
        if self.ws is not None:
            await self.ws.close()
            self.ws = None

    async def _handle_tool_call(self, event: dict[str, Any]) -> None:
        call_id = str(event.get("call_id") or event.get("item_id") or "")
        name = str(event.get("name") or event.get("function", {}).get("name") or "")
        arguments = event.get("arguments") or event.get("arguments_json") or "{}"
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments)

        result = await self.tools.call(name, arguments)
        try:
            parsed_arguments: Any = json.loads(arguments)
        except json.JSONDecodeError:
            parsed_arguments = arguments

        await self.emit(
            {
                "type": "tool_call",
                "name": name,
                "arguments": parsed_arguments,
                "result": result,
            }
        )
        await self._send_upstream(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result),
                },
            }
        )
        # response.create is sent on the function-call response's response.done.
        self._pending_response_create = True

    async def _trim_history(self) -> None:
        cap = self.profile.conversation.max_history_items
        if not isinstance(cap, int):
            return
        while len(self._item_ids) > cap:
            item_id = self._item_ids.pop(0)
            await self._send_upstream({"type": "conversation.item.delete", "item_id": item_id})

    async def _send_upstream(self, payload: dict[str, Any]) -> None:
        if self.ws is None:
            raise RuntimeError("Upstream WebSocket is not connected")
        await self.ws.send(json.dumps(payload))

    @staticmethod
    def _parse_event(raw: str | bytes) -> dict[str, Any]:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return {"type": "error", "error": {"message": "Upstream sent invalid JSON"}}
        return event if isinstance(event, dict) else {"type": "error", "error": {"message": "Upstream sent non-object JSON"}}

    @staticmethod
    def _error_message(event: dict[str, Any]) -> str:
        error = event.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code")
            if message:
                return str(message)
        return str(event.get("message") or "Upstream error")
