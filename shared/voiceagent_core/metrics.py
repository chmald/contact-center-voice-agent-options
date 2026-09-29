"""Turn and session metrics for voice-agent latency and token usage."""

from __future__ import annotations

import json
import logging
import statistics
import time
from dataclasses import dataclass, field
from typing import Any

LOGGER = logging.getLogger("voiceagent.metrics")

_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cached_tokens",
    "input_text_tokens",
    "input_audio_tokens",
    "output_text_tokens",
    "output_audio_tokens",
)


def _nested_int(data: dict[str, Any], path: tuple[str, ...]) -> int:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return 0
        current = current.get(key, 0)
    return current if isinstance(current, int) else 0


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


@dataclass
class SessionMetrics:
    session_id: str
    session_started_at: float = field(default_factory=time.monotonic)
    turn_started_at: float | None = None
    _current_ttfa_ms: float | None = None
    _last_turn: dict[str, Any] = field(default_factory=dict)
    _ttfa_values: list[float] = field(default_factory=list)
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    input_text_tokens: int = 0
    input_audio_tokens: int = 0
    output_text_tokens: int = 0
    output_audio_tokens: int = 0
    _turn_usage: dict[str, int] = field(default_factory=dict)
    def mark_turn_start(self) -> None:
        self.turn_started_at = time.monotonic()
        self._current_ttfa_ms = None

    def mark_first_audio(self) -> None:
        if self.turn_started_at is not None and self._current_ttfa_ms is None:
            self._current_ttfa_ms = (time.monotonic() - self.turn_started_at) * 1000

    def add_usage(self, response_done_event: dict[str, Any]) -> None:
        """Accumulate one response's usage into the open turn and the session.

        A tool-calling turn spans two responses (function call, then spoken
        answer); both are summed into the same turn by ``finish_turn``.
        """

        usage = response_done_event.get("response", {}).get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        input_tokens = _nested_int(usage, ("input_tokens",))
        output_tokens = _nested_int(usage, ("output_tokens",))
        values = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": _nested_int(usage, ("total_tokens",)) or input_tokens + output_tokens,
            "cached_tokens": _nested_int(usage, ("input_token_details", "cached_tokens")),
            "input_text_tokens": _nested_int(usage, ("input_token_details", "text_tokens")),
            "input_audio_tokens": _nested_int(usage, ("input_token_details", "audio_tokens")),
            "output_text_tokens": _nested_int(usage, ("output_token_details", "text_tokens")),
            "output_audio_tokens": _nested_int(usage, ("output_token_details", "audio_tokens")),
        }
        for key, value in values.items():
            self._turn_usage[key] = self._turn_usage.get(key, 0) + value
            setattr(self, key, getattr(self, key) + value)

    def finish_turn(self, response_done_event: dict[str, Any]) -> dict[str, Any]:
        now = time.monotonic()
        response_ms = None
        if self.turn_started_at is not None:
            response_ms = (now - self.turn_started_at) * 1000

        self.add_usage(response_done_event)
        usage = {key: self._turn_usage.get(key, 0) for key in _USAGE_KEYS}
        self._turn_usage = {}

        self.turns += 1
        if self._current_ttfa_ms is not None:
            self._ttfa_values.append(self._current_ttfa_ms)

        self._last_turn = {
            "session_id": self.session_id,
            "turn_index": self.turns,
            "ttfa_ms": round(self._current_ttfa_ms, 2) if self._current_ttfa_ms is not None else None,
            "response_ms": round(response_ms, 2) if response_ms is not None else None,
            **usage,
        }
        self.turn_started_at = None
        self._current_ttfa_ms = None
        return self.turn_summary()

    def turn_summary(self) -> dict[str, Any]:
        return dict(self._last_turn)

    def session_summary(self) -> dict[str, Any]:
        elapsed_seconds = max(time.monotonic() - self.session_started_at, 1.0)
        elapsed_minutes = elapsed_seconds / 60
        p50 = _percentile(self._ttfa_values, 0.5)
        p90 = _percentile(self._ttfa_values, 0.9)
        return {
            "session_id": self.session_id,
            "turns": self.turns,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cached_tokens": self.cached_tokens,
            "input_text_tokens": self.input_text_tokens,
            "input_audio_tokens": self.input_audio_tokens,
            "output_text_tokens": self.output_text_tokens,
            "output_audio_tokens": self.output_audio_tokens,
            "tokens_per_minute": round(self.total_tokens / elapsed_minutes, 2),
            "ttfa_p50_ms": round(p50, 2) if p50 is not None else None,
            "ttfa_p90_ms": round(p90, 2) if p90 is not None else None,
            "elapsed_seconds": round(elapsed_seconds, 2),
        }

    def log_turn(self, api_name: str) -> None:
        payload = {
            "event": "voice_turn",
            "api": api_name,
            **self.turn_summary(),
            "session": self.session_summary(),
        }
        LOGGER.info(json.dumps(payload, separators=(",", ":"), sort_keys=True))
