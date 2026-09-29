from __future__ import annotations

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from voiceagent_core import rag
from voiceagent_core.profile import load_profile
from voiceagent_core.tools import ToolRegistry


@pytest.fixture(autouse=True)
async def _reset_rag(monkeypatch):
    for name in ("AZURE_SEARCH_ENDPOINT", "AZURE_SEARCH_INDEX", "AZURE_SEARCH_SEMANTIC_CONFIG", "AZURE_SEARCH_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    await rag.close()
    yield
    await rag.close()


async def test_local_knowledge_search_ranks_and_truncates(profile_path):
    registry = ToolRegistry.from_profile(load_profile(profile_path))

    result = await registry.call("search_knowledge_base", json.dumps({"query": "How do I reset my password?"}))
    assert result["backend"] == "local"
    assert result["results"][0]["source"] == "kb/password-reset"
    assert len(result["results"]) <= 3
    assert all(len(item["content"]) <= 600 for item in result["results"])

    empty = await registry.call("search_knowledge_base", json.dumps({"query": "zzzz qqqq"}))
    assert empty["results"] == [] and "human handoff" in empty["message"]

    missing = await registry.call("search_knowledge_base", json.dumps({}))
    assert "Missing required argument" in missing["error"]
    assert rag.describe_backend() == "local"


async def test_azure_ai_search_backend_sends_semantic_query(profile_path, monkeypatch):
    captured: dict = {}

    async def handler(request: web.Request) -> web.Response:
        captured["path"] = request.path
        captured["query"] = dict(request.query)
        captured["headers"] = dict(request.headers)
        captured["body"] = await request.json()
        return web.json_response(
            {
                "value": [
                    {"title": "Support hours", "content": "Open 7 to 7. " * 100, "source": "kb/hours", "@search.score": 3.2},
                ]
            }
        )

    app = web.Application()
    app.router.add_post("/indexes/{index}/docs/search", handler)
    server = TestServer(app)
    await server.start_server()
    try:
        monkeypatch.setenv("AZURE_SEARCH_ENDPOINT", str(server.make_url("")).rstrip("/"))
        monkeypatch.setenv("AZURE_SEARCH_INDEX", "knowledge")
        monkeypatch.setenv("AZURE_SEARCH_SEMANTIC_CONFIG", "default")
        monkeypatch.setenv("AZURE_SEARCH_API_KEY", "local-test-only")
        registry = ToolRegistry.from_profile(load_profile(profile_path))

        result = await registry.call("search_knowledge_base", json.dumps({"query": "support hours"}))
    finally:
        await rag.close()
        await server.close()

    assert result["backend"] == "azure-ai-search:knowledge"
    assert result["results"][0]["title"] == "Support hours"
    assert len(result["results"][0]["content"]) <= 600
    assert captured["path"] == "/indexes/knowledge/docs/search"
    assert captured["query"]["api-version"] == rag.DEFAULT_SEARCH_API_VERSION
    assert captured["body"]["queryType"] == "semantic"
    assert captured["body"]["semanticConfiguration"] == "default"
    assert captured["body"]["top"] == 3
    assert captured["body"]["select"] == "title,content,source"


async def test_azure_ai_search_errors_become_tool_errors(profile_path, monkeypatch):
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"error": {"message": "Forbidden"}}, status=403)

    app = web.Application()
    app.router.add_post("/indexes/{index}/docs/search", handler)
    server = TestServer(app)
    await server.start_server()
    try:
        monkeypatch.setenv("AZURE_SEARCH_ENDPOINT", str(server.make_url("")).rstrip("/"))
        monkeypatch.setenv("AZURE_SEARCH_INDEX", "knowledge")
        monkeypatch.setenv("AZURE_SEARCH_API_KEY", "local-test-only")
        registry = ToolRegistry.from_profile(load_profile(profile_path))
        result = await registry.call("search_knowledge_base", json.dumps({"query": "vpn"}))
    finally:
        await rag.close()
        await server.close()

    assert "HTTP 403" in result["error"]
