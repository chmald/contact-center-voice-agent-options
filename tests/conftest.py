from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from voiceagent_core.bridge import RealtimeStyleBridge


@pytest.fixture
def repo_root() -> Path:
    return ROOT


@pytest.fixture
def profile_path(repo_root: Path) -> Path:
    return repo_root / "config" / "agent-profile.json"


class DummyBridge(RealtimeStyleBridge):
    api_name = "dummy"
    upstream_url = ""

    async def build_url(self) -> str:
        return self.upstream_url

    async def build_headers(self) -> dict[str, str]:
        return {"x-test-header": "yes"}

    def build_session_update(self) -> dict[str, Any]:
        return {
            "type": "session.update",
            "session": {
                "instructions": self.profile.instructions,
                "tools": self.tools.definitions(),
            },
        }

    def model_label(self) -> str:
        return "dummy-model"

    def voice_label(self) -> str:
        return "dummy-voice"


@pytest.fixture
def dummy_bridge_class():
    return DummyBridge


async def wait_until(predicate, timeout: float = 3.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        value = predicate()
        if value:
            return value
        await asyncio.sleep(0.01)
    raise TimeoutError("Timed out waiting for condition")
