from __future__ import annotations

import asyncio
from typing import Any

from voiceagent_core.profile import load_profile
from voiceagent_core.sessions import SessionHub, pump
from voiceagent_core.tools import ToolRegistry


class _NeverEndingBridge:
    def __init__(self):
        self.cancelled = False

    async def run(self) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def _hub(profile_path, max_sessions: int) -> SessionHub:
    profile = load_profile(profile_path)
    return SessionHub(lambda *args: None, profile, ToolRegistry.from_profile(profile), max_sessions)  # type: ignore[arg-type]


async def test_reservations_are_atomic_claimable_and_expire(profile_path):
    hub = _hub(profile_path, max_sessions=1)
    results = await asyncio.gather(hub.reserve("a", 30), hub.reserve("b", 30))
    assert sorted(results) == [False, True]
    assert hub.active == 1

    winner = "a" if results[0] else "b"
    assert await hub.claim(winner) is True
    assert hub.active == 1
    await hub.release()
    assert hub.active == 0

    assert await hub.reserve("c", 0.01)
    await asyncio.sleep(0.05)
    assert await hub.try_acquire() is True  # expired reservation freed its slot
    assert hub.active == 1

    await hub.release()
    assert await hub.reserve("d", 30)
    await hub.cancel_reservation("d")
    assert hub.active == 0


async def test_pump_cancels_both_readers_when_itself_cancelled():
    bridge = _NeverEndingBridge()
    inbound_cancelled = asyncio.Event()

    async def inbound() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            inbound_cancelled.set()
            raise

    task = asyncio.create_task(pump(inbound(), bridge))  # type: ignore[arg-type]
    await asyncio.sleep(0.01)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert bridge.cancelled
    assert inbound_cancelled.is_set()


async def test_pump_returns_first_error_and_cancels_the_other():
    bridge = _NeverEndingBridge()

    async def inbound() -> Any:
        raise RuntimeError("caller hung up")

    errors = await pump(inbound(), bridge)  # type: ignore[arg-type]
    assert [type(e) for e in errors] == [RuntimeError]
    assert bridge.cancelled
