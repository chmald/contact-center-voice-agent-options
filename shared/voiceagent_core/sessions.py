"""Channel-agnostic session plumbing shared by the browser and telephony adapters.

A ``SessionHub`` owns the single admission-control counter, so browser tabs,
ACS calls, and Twilio calls all count against the same
``MAX_CONCURRENT_SESSIONS`` cap - exactly like one contact-center bridge in
front of one AI endpoint.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from .bridge import RealtimeStyleBridge
from .metrics import SessionMetrics
from .profile import AgentProfile
from .tools import ToolRegistry

LOGGER = logging.getLogger("voiceagent.sessions")

Emit = Callable[[dict[str, Any]], Awaitable[None]]
BridgeFactory = Callable[
    [AgentProfile, ToolRegistry, Emit, SessionMetrics, str],
    RealtimeStyleBridge,
]

BUSY_MESSAGE = "All agents are busy. Please try again shortly or use the human queue."


async def _noop_emit(_: dict[str, Any]) -> None:
    return None


class SessionHub:
    """Admission control, bridge construction, and session logging for every channel.

    Phone calls reserve a slot when the call arrives (webhook) and claim it when media
    connects, so concurrent arrivals get the configured busy/overflow treatment instead
    of being answered and then dropped. Unclaimed reservations expire.
    """

    def __init__(
        self,
        bridge_factory: BridgeFactory,
        profile: AgentProfile,
        tools: ToolRegistry,
        max_sessions: int,
    ):
        self.bridge_factory = bridge_factory
        self.profile = profile
        self.tools = tools
        self.max_sessions = max_sessions
        self.active = 0
        self._reservations: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def has_capacity(self) -> bool:
        return self.max_sessions <= 0 or self.active < self.max_sessions

    def _expire_reservations(self) -> None:
        now = time.monotonic()
        for key in [key for key, deadline in self._reservations.items() if deadline <= now]:
            del self._reservations[key]
            self.active = max(0, self.active - 1)

    async def try_acquire(self) -> bool:
        async with self._lock:
            self._expire_reservations()
            if not self.has_capacity():
                return False
            self.active += 1
            return True

    async def reserve(self, key: str, ttl_seconds: float) -> bool:
        """Atomically hold a slot for a call that has not connected media yet."""

        async with self._lock:
            self._expire_reservations()
            if key in self._reservations:
                self._reservations[key] = time.monotonic() + ttl_seconds
                return True
            if not self.has_capacity():
                return False
            self.active += 1
            self._reservations[key] = time.monotonic() + ttl_seconds
            return True

    async def claim(self, key: str) -> bool:
        """Turn a reservation into a live session, or acquire a fresh slot if none exists."""

        async with self._lock:
            self._expire_reservations()
            if self._reservations.pop(key, None) is not None:
                return True
            if not self.has_capacity():
                return False
            self.active += 1
            return True

    async def cancel_reservation(self, key: str) -> None:
        async with self._lock:
            if self._reservations.pop(key, None) is not None:
                self.active = max(0, self.active - 1)

    async def release(self) -> None:
        async with self._lock:
            self.active = max(0, self.active - 1)

    def info(self) -> dict[str, Any]:
        bridge = self.bridge_factory(self.profile, self.tools, _noop_emit, SessionMetrics("info"), "info")
        return {
            "api": bridge.api_name,
            "model": bridge.model_label(),
            "voice": bridge.voice_label(),
            "assistant_name": self.profile.assistant_name,
            "active_sessions": self.active,
            "max_sessions": self.max_sessions,
        }

    def new_session(self, emit: Emit) -> tuple[RealtimeStyleBridge, SessionMetrics, str]:
        session_id = str(uuid.uuid4())
        metrics = SessionMetrics(session_id=session_id)
        bridge = self.bridge_factory(self.profile, self.tools, emit, metrics, session_id)
        return bridge, metrics, session_id

    @staticmethod
    def log_start(session_id: str, api_name: str, channel: str, **extra: Any) -> None:
        LOGGER.info(
            json.dumps(
                {"event": "voice_session_start", "session_id": session_id, "api": api_name, "channel": channel, **extra},
                separators=(",", ":"),
                sort_keys=True,
            )
        )

    @staticmethod
    def log_end(session_id: str, api_name: str, channel: str, metrics: SessionMetrics, **extra: Any) -> None:
        LOGGER.info(
            json.dumps(
                {
                    "event": "voice_session_end",
                    "session_id": session_id,
                    "api": api_name,
                    "channel": channel,
                    "session": metrics.session_summary(),
                    **extra,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )


async def pump(inbound: Awaitable[None], bridge: RealtimeStyleBridge) -> list[BaseException]:
    """Run the channel->bridge reader and the bridge->channel reader until either ends.

    Returns exceptions raised by the task(s) that finished first so the caller can
    decide whether to report them (disconnects are normal for phone hang-ups).
    """

    inbound_task = asyncio.ensure_future(inbound)
    bridge_task = asyncio.ensure_future(bridge.run())
    try:
        done, _ = await asyncio.wait({inbound_task, bridge_task}, return_when=asyncio.FIRST_COMPLETED)
        return [task.exception() for task in done if not task.cancelled() and task.exception() is not None]
    finally:
        # Also runs when pump() itself is cancelled, so neither reader is ever orphaned.
        for task in (inbound_task, bridge_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(inbound_task, bridge_task, return_exceptions=True)
