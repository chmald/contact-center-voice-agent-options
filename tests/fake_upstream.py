"""Reusable in-process fake realtime WebSocket server for example tests.

Usage:
    server = FakeRealtimeServer(dialect="ga")
    await server.start()
    try:
        bridge points at server.url
        assert server.received_events
    finally:
        await server.stop()

Set ``dialect="ga"`` for ``response.output_audio.*`` and
``conversation.item.added`` events, or ``dialect="beta"`` for
``response.audio.*`` and ``conversation.item.created`` events. Set
``script_function_call=True`` to emit a function-call turn first; after the
bridge sends ``function_call_output`` plus a new ``response.create``, the fake
emits the final audio, transcript, and usage block.

The fake mirrors the real API's response lifecycle per connection: a
``response.create`` received while a response is in progress is rejected with
``conversation_already_has_active_response``; ``response.cancel`` ends the
active response with a cancelled ``response.done`` (or returns
``response_cancel_not_active`` when nothing is in progress). Use
``response_delay`` to keep responses "in progress" long enough to exercise
barge-in deterministically. State is per connection, so concurrent sessions
(e.g. the load probe) don't interfere with each other.
"""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass, field
from typing import Any

import websockets


def tiny_audio_b64() -> str:
    return base64.b64encode((0).to_bytes(2, "little", signed=True) * 240).decode("ascii")


FULL_USAGE = {
    "input_tokens": 7,
    "output_tokens": 5,
    "total_tokens": 12,
    "input_token_details": {"cached_tokens": 2, "text_tokens": 4, "audio_tokens": 3},
    "output_token_details": {"text_tokens": 2, "audio_tokens": 3},
}
TOOL_CALL_USAGE = {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4}
CANCELLED_USAGE = {"input_tokens": 2, "output_tokens": 0, "total_tokens": 2}


@dataclass(eq=False)
class _Connection:
    websocket: Any
    item_index: int = 0
    tool_requested: bool = False
    active_task: asyncio.Task | None = None
    tasks: set[asyncio.Task] = field(default_factory=set)

    @property
    def active(self) -> bool:
        return self.active_task is not None and not self.active_task.done()


class FakeRealtimeServer:
    def __init__(
        self,
        dialect: str = "ga",
        script_function_call: bool = False,
        function_name: str = "lookup_request_status",
        function_arguments: dict[str, Any] | None = None,
        response_delay: float = 0.0,
    ):
        if dialect not in {"ga", "beta"}:
            raise ValueError("dialect must be 'ga' or 'beta'")
        self.dialect = dialect
        self.script_function_call = script_function_call
        self.function_name = function_name
        self.function_arguments = function_arguments or {"request_id": "SR-1001"}
        self.response_delay = response_delay
        self.received_events: list[dict[str, Any]] = []
        self.headers: dict[str, str] = {}
        self.path = ""
        self.url = ""
        self.rejected_response_creates = 0
        self.cancelled_responses = 0
        self._server = None
        self._connections: set[_Connection] = set()

    async def start(self) -> "FakeRealtimeServer":
        self._server = await websockets.serve(self._handler, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}/fake?api-version=test"
        return self

    async def stop(self) -> None:
        for conn in list(self._connections):
            for task in list(conn.tasks):
                task.cancel()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handler(self, websocket, path: str | None = None) -> None:
        request = getattr(websocket, "request", None)
        self.path = path or getattr(request, "path", "") or ""
        raw_headers = getattr(request, "headers", None) or getattr(websocket, "request_headers", {})
        self.headers = {str(k).lower(): str(v) for k, v in raw_headers.items()}

        conn = _Connection(websocket)
        self._connections.add(conn)
        try:
            await self._send(conn, {"type": "session.created"})
            async for raw in websocket:
                await self._on_client_event(conn, json.loads(raw))
        except websockets.ConnectionClosed:
            pass
        finally:
            for task in list(conn.tasks):
                task.cancel()
            self._connections.discard(conn)

    async def _on_client_event(self, conn: _Connection, event: dict[str, Any]) -> None:
        self.received_events.append(event)
        event_type = event.get("type")
        if event_type == "session.update":
            await self._send(conn, {"type": "session.updated"})
        elif event_type == "conversation.item.create":
            await self._emit_item_created(conn, event.get("item", {}))
        elif event_type == "response.create":
            if conn.active:
                self.rejected_response_creates += 1
                await self._error(conn, "conversation_already_has_active_response", "Conversation already has an active response")
                return
            if self.script_function_call and not conn.tool_requested:
                conn.tool_requested = True
                coro = self._emit_function_call(conn)
            else:
                coro = self._emit_response(conn)
            conn.active_task = asyncio.create_task(coro)
            conn.tasks.add(conn.active_task)
            conn.active_task.add_done_callback(conn.tasks.discard)
        elif event_type == "response.cancel":
            if not conn.active:
                await self._error(conn, "response_cancel_not_active", "Cancellation failed: no active response found")
                return
            conn.active_task.cancel()
            conn.active_task = None
            self.cancelled_responses += 1
            await self._send(conn, {"type": "response.done", "response": {"status": "cancelled", "usage": CANCELLED_USAGE}})

    async def _send(self, conn: _Connection, payload: dict[str, Any]) -> None:
        await conn.websocket.send(json.dumps(payload))

    async def _error(self, conn: _Connection, code: str, message: str) -> None:
        await self._send(conn, {"type": "error", "error": {"code": code, "message": message}})

    async def _emit_item_created(self, conn: _Connection, item: dict[str, Any]) -> None:
        conn.item_index += 1
        item_event = "conversation.item.added" if self.dialect == "ga" else "conversation.item.created"
        item_id = item.get("id") or f"item_{conn.item_index}"
        await self._send(conn, {"type": item_event, "item": {"id": item_id}})

    async def _emit_function_call(self, conn: _Connection) -> None:
        await self._send(conn, {"type": "response.created"})
        await self._send(
            conn,
            {
                "type": "response.function_call_arguments.done",
                "call_id": "call_test_1",
                "name": self.function_name,
                "arguments": json.dumps(self.function_arguments),
            },
        )
        # Real servers finish the function-call response shortly after the
        # arguments; the gap exposes clients that send response.create too early.
        await asyncio.sleep(max(0.05, self.response_delay))
        conn.active_task = None
        await self._send(conn, {"type": "response.done", "response": {"status": "completed", "usage": TOOL_CALL_USAGE}})

    async def _emit_response(self, conn: _Connection) -> None:
        ga = self.dialect == "ga"
        audio_event = "response.output_audio.delta" if ga else "response.audio.delta"
        transcript_delta = "response.output_audio_transcript.delta" if ga else "response.audio_transcript.delta"
        transcript_done = "response.output_audio_transcript.done" if ga else "response.audio_transcript.done"
        await self._send(conn, {"type": "response.created"})
        await self._send(conn, {"type": "input_audio_buffer.speech_started"})
        if self.response_delay:
            await asyncio.sleep(self.response_delay)
        await self._send(conn, {"type": audio_event, "delta": tiny_audio_b64()})
        await self._send(conn, {"type": transcript_delta, "delta": "Done"})
        await self._send(conn, {"type": transcript_done, "transcript": "Done."})
        conn.active_task = None
        await self._send(conn, {"type": "response.done", "response": {"status": "completed", "usage": FULL_USAGE}})
