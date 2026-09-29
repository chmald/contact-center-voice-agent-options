from __future__ import annotations

import json

import pytest

from voiceagent_core.profile import load_profile
from voiceagent_core.tools import ToolRegistry


@pytest.mark.asyncio
async def test_load_profile_and_call_configured_tools(profile_path):
    profile = load_profile(profile_path)
    registry = ToolRegistry.from_profile(profile)

    definitions = registry.definitions()
    assert [tool["name"] for tool in definitions] == [
        "lookup_request_status",
        "get_current_time",
        "search_knowledge_base",
    ]

    found = await registry.call("lookup_request_status", json.dumps({"request_id": "SR-1001"}))
    assert found["found"] is True
    assert found["record"]["id"] == "SR-1001"

    missing = await registry.call("lookup_request_status", json.dumps({"request_id": "SR-9999"}))
    assert missing == {
        "found": False,
        "key": "SR-9999",
        "message": "No matching record was found.",
    }

    clock = await registry.call("get_current_time", json.dumps({"timezone": "Not/AZone"}))
    assert clock["timezone"] == "UTC"
    assert "note" in clock


def test_profile_validation_rejects_duplicate_tool_names(tmp_path, profile_path):
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    data["tools"].append(dict(data["tools"][0]))
    path = tmp_path / "bad-profile.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate tool name"):
        load_profile(path)


def test_profile_validation_rejects_unknown_handler(tmp_path, profile_path):
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    data["tools"][0]["handler"] = "missing_handler"
    path = tmp_path / "bad-profile.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown"):
        load_profile(path)
