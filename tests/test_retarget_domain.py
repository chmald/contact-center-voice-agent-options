from __future__ import annotations

import json

import pytest

from voiceagent_core.profile import load_profile
from voiceagent_core.tools import ToolRegistry


@pytest.mark.asyncio
async def test_retargeting_comes_from_profile_and_data_only(tmp_path):
    data_path = tmp_path / "data.json"
    data_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "id": "BK-1",
                        "status": "available",
                        "title": "Example Architecture Handbook",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "assistant_name": "Library Assistant",
                "instructions": "Answer briefly and use tools for availability.",
                "greeting": "How can I help with the catalog?",
                "tools": [
                    {
                        "name": "check_book_availability",
                        "description": "Check whether a book is available by id.",
                        "handler": "record_lookup",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "book_id": {
                                    "type": "string",
                                    "description": "Book identifier"
                                }
                            },
                            "required": ["book_id"],
                        },
                        "handler_config": {
                            "data_file": "data.json",
                            "collection": "records",
                            "key_field": "id",
                            "argument": "book_id",
                        },
                    }
                ],
                "conversation": {"max_history_items": 4},
            }
        ),
        encoding="utf-8",
    )

    profile = load_profile(profile_path)
    registry = ToolRegistry.from_profile(profile)
    definitions = registry.definitions()

    assert profile.assistant_name == "Library Assistant"
    assert definitions[0]["name"] == "check_book_availability"
    assert "Contoso" not in json.dumps(definitions)
    assert "SR-10" not in json.dumps(definitions)

    result = await registry.call("check_book_availability", json.dumps({"book_id": "BK-1"}))
    assert result["found"] is True
    assert result["record"]["title"] == "Example Architecture Handbook"
