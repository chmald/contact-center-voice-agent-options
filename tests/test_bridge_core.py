from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import replace

import pytest

from tests.conftest import wait_until
from tests.fake_upstream import FakeRealtimeServer
from voiceagent_core.metrics import SessionMetrics
from voiceagent_core.profile import ConversationSettings, load_profile
from voiceagent_core.tools import ToolRegistry


async def _start_bridge(profile_path, dummy_bridge_class, server, profile_transform=None):
    await server.start()
    dummy_bridge_class.upstream_url = server.url
    profile = load_profile(profile_path)
    profile = replace(profile, greeting="")
    if profile_transform:
        profile = profile_transform(profile)
    emitted = []

    async def emit(message):
        emitted.append(message)

    bridge = dummy_bridge_class(
        profile=profile,
        tools=ToolRegistry.from_profile(profile),
        emit=emit,
        metrics=SessionMetrics("test-session"),
        session_id="test-session",
    )
    await bridge.connect()
    task = asyncio.create_task(bridge.run())
    return bridge, task, emitted


async def _stop_bridge(bridge, task, server):
    await bridge.close()
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    await server.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("dialect", ["ga", "beta"])
async def test_audio_transcript_speech_and_metrics_relay(profile_path, dummy_bridge_class, dialect):
    server = FakeRealtimeServer(dialect=dialect)
    bridge, task, emitted = await _start_bridge(profile_path, dummy_bridge_class, server)
    try:
        await bridge.send_text("hello")
        await wait_until(lambda: any(message["type"] == "metrics" for message in emitted))

        assert server.path.startswith("/fake")
        assert server.headers["x-test-header"] == "yes"
        assert any(message["type"] == "speech_started" for message in emitted)
        assert any(message["type"] == "audio" for message in emitted)
        assert any(
            message["type"] == "transcript"
            and message["role"] == "assistant"
            and message["final"] is True
            for message in emitted
        )
        metrics = [message for message in emitted if message["type"] == "metrics"][-1]
        assert metrics["turn"]["total_tokens"] == 12
    finally:
        await _stop_bridge(bridge, task, server)


@pytest.mark.asyncio
async def test_tool_round_trip_and_function_call_output_shape(profile_path, dummy_bridge_class):
    server = FakeRealtimeServer(dialect="ga", script_function_call=True)
    bridge, task, emitted = await _start_bridge(profile_path, dummy_bridge_class, server)
    try:
        await bridge.send_text("check request")
        await wait_until(lambda: any(message["type"] == "tool_call" for message in emitted))
        await wait_until(lambda: any(message["type"] == "audio" for message in emitted))

        tool_message = [message for message in emitted if message["type"] == "tool_call"][0]
        assert tool_message["name"] == "lookup_request_status"
        assert tool_message["result"]["found"] is True

        output_items = [
            event["item"]
            for event in server.received_events
            if event.get("type") == "conversation.item.create"
            and event.get("item", {}).get("type") == "function_call_output"
        ]
        assert len(output_items) == 1
        assert output_items[0]["call_id"] == "call_test_1"
        assert json.loads(output_items[0]["output"])["found"] is True
        # Follow-up response.create must wait for the function-call response.done.
        assert server.rejected_response_creates == 0
        await wait_until(lambda: any(message["type"] == "metrics" for message in emitted))
        metrics = [message for message in emitted if message["type"] == "metrics"]
        assert len(metrics) == 1, "tool call + spoken answer should be one turn"
        assert metrics[0]["turn"]["total_tokens"] == 4 + 12
        assert not any(message["type"] == "error" for message in emitted)
    finally:
        await _stop_bridge(bridge, task, server)


@pytest.mark.asyncio
async def test_history_trimming_sends_delete(profile_path, dummy_bridge_class):
    server = FakeRealtimeServer(dialect="ga")

    def set_cap(profile):
        return replace(profile, conversation=ConversationSettings(max_history_items=1))

    bridge, task, emitted = await _start_bridge(profile_path, dummy_bridge_class, server, set_cap)
    try:
        await bridge.send_text("first")
        await wait_until(lambda: len([m for m in emitted if m["type"] == "metrics"]) >= 1)
        await bridge.send_text("second")
        await wait_until(lambda: any(event.get("type") == "conversation.item.delete" for event in server.received_events))

        deletes = [event for event in server.received_events if event.get("type") == "conversation.item.delete"]
        assert deletes[0]["item_id"] == "item_1"
    finally:
        await _stop_bridge(bridge, task, server)


@pytest.mark.asyncio
@pytest.mark.parametrize("dialect", ["ga", "beta"])
async def test_typed_turn_during_greeting_cancels_then_creates(profile_path, dummy_bridge_class, dialect):
    """Regression: a turn sent while the greeting is still playing must not send a
    second response.create (rejected upstream as conversation_already_has_active_response)."""

    server = FakeRealtimeServer(dialect=dialect, response_delay=0.3)
    await server.start()
    dummy_bridge_class.upstream_url = server.url
    profile = replace(load_profile(profile_path), greeting="Hello there")
    emitted = []

    async def emit(message):
        emitted.append(message)

    bridge = dummy_bridge_class(
        profile=profile,
        tools=ToolRegistry.from_profile(profile),
        emit=emit,
        metrics=SessionMetrics("barge-in"),
        session_id="barge-in",
    )
    await bridge.connect()  # greeting response is now in progress upstream
    task = asyncio.create_task(bridge.run())
    try:
        await bridge.send_text("What's the status of SR-1001?")
        await wait_until(lambda: any(m["type"] == "metrics" for m in emitted), timeout=5)

        assert server.rejected_response_creates == 0
        assert server.cancelled_responses == 1
        assert any(m["type"] == "interrupted" for m in emitted)
        assert not any(m["type"] == "error" for m in emitted)
        creates = [e for e in server.received_events if e.get("type") == "response.create"]
        assert len(creates) == 2, "greeting + the deferred user response"
        metrics = [m for m in emitted if m["type"] == "metrics"]
        assert len(metrics) == 1
        assert metrics[0]["turn"]["total_tokens"] == 2 + 12  # cancelled greeting + answer
        assert metrics[0]["turn"]["ttfa_ms"] is not None
    finally:
        await _stop_bridge(bridge, task, server)


@pytest.mark.asyncio
async def test_benign_cancel_error_is_not_surfaced(profile_path, dummy_bridge_class):
    profile = replace(load_profile(profile_path), greeting="")
    emitted = []

    async def emit(message):
        emitted.append(message)

    bridge = dummy_bridge_class(
        profile=profile,
        tools=ToolRegistry.from_profile(profile),
        emit=emit,
        metrics=SessionMetrics("benign"),
        session_id="benign",
    )
    await bridge.handle_event({"type": "error", "error": {"code": "response_cancel_not_active", "message": "x"}})
    await bridge.handle_event({"type": "error", "error": {"code": "rate_limit_exceeded", "message": "slow down"}})
    assert emitted == [{"type": "error", "message": "slow down"}]


@pytest.mark.asyncio
async def test_interrupt_sends_response_cancel(profile_path, dummy_bridge_class):
    server = FakeRealtimeServer(dialect="ga")
    await server.start()
    dummy_bridge_class.upstream_url = server.url
    profile = replace(load_profile(profile_path), greeting="")

    async def emit(_):
        return None

    bridge = dummy_bridge_class(
        profile=profile,
        tools=ToolRegistry.from_profile(profile),
        emit=emit,
        metrics=SessionMetrics("interrupt-session"),
        session_id="interrupt-session",
    )
    try:
        await bridge.connect()
        await bridge.send_text("cancel me")
        await bridge.interrupt()
        await wait_until(lambda: any(event.get("type") == "response.cancel" for event in server.received_events))
    finally:
        await bridge.close()
        await server.stop()
