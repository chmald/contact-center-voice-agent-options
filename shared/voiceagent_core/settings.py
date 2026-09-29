"""Environment-backed settings shared by both example applications."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _default_profile_path() -> Path:
    local = Path.cwd() / "config" / "agent-profile.json"
    return local if local.exists() else Path("/app/config/agent-profile.json")


def _default_static_dir() -> Path:
    local = Path(__file__).resolve().parents[1] / "static"
    return local if local.exists() else Path("/app/static")


@dataclass(frozen=True)
class CommonSettings:
    """Configuration common to the three example apps."""

    agent_profile_path: Path
    max_concurrent_sessions: int = 20
    log_level: str = "INFO"
    azure_client_id: str | None = None
    static_dir: Path = _default_static_dir()

    @classmethod
    def from_env(cls) -> "CommonSettings":
        """Build settings from environment variables."""

        raw_max = os.getenv("MAX_CONCURRENT_SESSIONS", "20")
        try:
            max_sessions = int(raw_max)
        except ValueError as exc:
            raise ValueError("MAX_CONCURRENT_SESSIONS must be an integer") from exc
        if max_sessions < 0:
            raise ValueError("MAX_CONCURRENT_SESSIONS must be 0 or greater")

        return cls(
            agent_profile_path=Path(os.getenv("AGENT_PROFILE_PATH") or _default_profile_path()),
            max_concurrent_sessions=max_sessions,
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            azure_client_id=os.getenv("AZURE_CLIENT_ID") or None,
            static_dir=Path(os.getenv("STATIC_DIR") or _default_static_dir()),
        )
