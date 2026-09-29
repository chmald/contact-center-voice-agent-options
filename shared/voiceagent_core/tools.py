"""Config-driven tool registry for realtime voice agents.

Add custom handlers by registering callables in ``HANDLERS`` before loading the
agent profile. A handler receives ``(arguments, tool, profile)`` and may return
a dict directly or an awaitable dict. This keeps retargeting structural: most
workloads only edit the profile and data file, while advanced workloads can add
handlers in the API-specific example package without changing shared core code.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .profile import AgentProfile, ToolSpec
from .rag import knowledge_search

Handler = Callable[[dict[str, Any], ToolSpec, AgentProfile], dict[str, Any] | Awaitable[dict[str, Any]]]


async def _record_lookup(
    arguments: dict[str, Any], tool: ToolSpec, profile: AgentProfile
) -> dict[str, Any]:
    cfg = tool.handler_config
    for key in ("data_file", "collection", "key_field", "argument"):
        if not isinstance(cfg.get(key), str) or not cfg[key]:
            return {"error": f"record_lookup handler_config.{key} must be a non-empty string"}

    data_path = (profile.base_dir / cfg["data_file"]).resolve()
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"error": f"Data file not found: {data_path}"}
    except json.JSONDecodeError as exc:
        return {"error": f"Data file is not valid JSON: {exc}"}

    collection = data.get(cfg["collection"])
    if not isinstance(collection, list):
        return {"error": f"Data collection is not a list: {cfg['collection']}"}

    lookup_value = arguments.get(cfg["argument"])
    if lookup_value in (None, ""):
        return {"error": f"Missing required argument: {cfg['argument']}"}

    key_field = cfg["key_field"]
    for record in collection:
        if isinstance(record, dict) and str(record.get(key_field)) == str(lookup_value):
            return {"found": True, "record": record}
    return {"found": False, "key": lookup_value, "message": "No matching record was found."}


async def _current_time(
    arguments: dict[str, Any], tool: ToolSpec, profile: AgentProfile
) -> dict[str, Any]:
    requested = arguments.get("timezone") or "UTC"
    note = None
    try:
        zone = ZoneInfo(str(requested))
        zone_key = zone.key
    except ZoneInfoNotFoundError:
        zone = timezone.utc
        zone_key = "UTC"
        note = f"Unknown timezone {requested!r}; returned UTC."

    now = datetime.now(zone)
    result = {
        "timezone": zone_key,
        "iso_time": now.isoformat(timespec="seconds"),
        "utc_offset": now.strftime("%z"),
    }
    if note:
        result["note"] = note
    return result


HANDLERS: dict[str, Handler] = {
    "record_lookup": _record_lookup,
    "current_time": _current_time,
    "knowledge_search": knowledge_search,
}


class ToolRegistry:
    """Lookup, describe, and invoke tools declared by an agent profile."""

    def __init__(self, profile: AgentProfile, tools: dict[str, ToolSpec]):
        self.profile = profile
        self._tools = tools

    @classmethod
    def from_profile(cls, profile: AgentProfile) -> "ToolRegistry":
        return cls(profile=profile, tools={tool.name: tool for tool in profile.tools})

    def definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI realtime function-tool definitions."""

        return [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in self._tools.values()
        ]

    async def call(self, name: str, arguments_json_str: str | None) -> dict[str, Any]:
        """Call a tool and convert every failure into an error dict."""

        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"Unknown tool: {name}"}
        handler = HANDLERS.get(tool.handler)
        if handler is None:
            return {"error": f"No handler registered for: {tool.handler}"}

        try:
            arguments = json.loads(arguments_json_str or "{}")
        except json.JSONDecodeError as exc:
            return {"error": f"Tool arguments are not valid JSON: {exc}"}
        if not isinstance(arguments, dict):
            return {"error": "Tool arguments must be a JSON object"}

        try:
            result = handler(arguments, tool, self.profile)
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, dict):
                return {"error": "Tool handler returned a non-object result"}
            return result
        except Exception as exc:  # Tool boundary: return errors to the model instead of crashing the session.
            return {"error": f"{type(exc).__name__}: {exc}"}
