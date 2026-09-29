"""Agent profile loading and validation.

The profile is the domain retargeting surface. Shared code reads tool names,
descriptions, system instructions, and data-handler configuration from this
file instead of baking workload terms into Python modules.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    handler: str
    parameters: dict[str, Any]
    handler_config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConversationSettings:
    max_history_items: int | None = None


@dataclass(frozen=True)
class AgentProfile:
    assistant_name: str
    instructions: str
    greeting: str
    tools: list[ToolSpec]
    conversation: ConversationSettings
    path: Path

    @property
    def base_dir(self) -> Path:
        return self.path.parent


def _require_string(data: dict[str, Any], key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}.{key} must be a non-empty string")
    return value


def load_profile(path: str | Path) -> AgentProfile:
    """Load and validate an agent profile JSON file."""

    profile_path = Path(path)
    if not profile_path.exists():
        raise FileNotFoundError(f"Agent profile not found: {profile_path}")

    try:
        raw = json.loads(profile_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Agent profile is not valid JSON: {profile_path}") from exc
    if not isinstance(raw, dict):
        raise ValueError("Agent profile root must be an object")

    assistant_name = _require_string(raw, "assistant_name", "profile")
    instructions = _require_string(raw, "instructions", "profile")
    greeting = raw.get("greeting", "")
    if not isinstance(greeting, str):
        raise ValueError("profile.greeting must be a string")

    raw_tools = raw.get("tools")
    if not isinstance(raw_tools, list):
        raise ValueError("profile.tools must be a list")

    from .tools import HANDLERS

    seen: set[str] = set()
    tools: list[ToolSpec] = []
    for index, item in enumerate(raw_tools):
        where = f"profile.tools[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where} must be an object")
        name = _require_string(item, "name", where)
        if not TOOL_NAME_RE.match(name):
            raise ValueError(
                f"{where}.name must match ^[a-zA-Z0-9_-]{{1,64}}$: {name!r}"
            )
        if name in seen:
            raise ValueError(f"Duplicate tool name in profile.tools: {name}")
        seen.add(name)

        description = _require_string(item, "description", where)
        handler = _require_string(item, "handler", where)
        if handler not in HANDLERS:
            known = ", ".join(sorted(HANDLERS))
            raise ValueError(f"{where}.handler is unknown: {handler!r}. Known handlers: {known}")

        parameters = item.get("parameters")
        if not isinstance(parameters, dict):
            raise ValueError(f"{where}.parameters must be an object")
        if parameters.get("type") != "object":
            raise ValueError(f"{where}.parameters.type must be 'object'")
        if not isinstance(parameters.get("properties", {}), dict):
            raise ValueError(f"{where}.parameters.properties must be an object")
        if not isinstance(parameters.get("required", []), list):
            raise ValueError(f"{where}.parameters.required must be a list")

        handler_config = item.get("handler_config", {})
        if not isinstance(handler_config, dict):
            raise ValueError(f"{where}.handler_config must be an object when present")
        tools.append(
            ToolSpec(
                name=name,
                description=description,
                handler=handler,
                parameters=parameters,
                handler_config=handler_config,
            )
        )

    raw_conversation = raw.get("conversation", {})
    if raw_conversation is None:
        raw_conversation = {}
    if not isinstance(raw_conversation, dict):
        raise ValueError("profile.conversation must be an object")
    max_history = raw_conversation.get("max_history_items")
    if max_history is not None:
        if not isinstance(max_history, int) or max_history < 0:
            raise ValueError("profile.conversation.max_history_items must be null or an integer >= 0")

    return AgentProfile(
        assistant_name=assistant_name,
        instructions=instructions,
        greeting=greeting,
        tools=tools,
        conversation=ConversationSettings(max_history_items=max_history),
        path=profile_path,
    )
