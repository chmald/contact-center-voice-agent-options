"""Retrieval-augmented generation (RAG) tool handler for voice agents.

The ``knowledge_search`` handler grounds spoken answers in a document index.
It is registered in ``tools.HANDLERS`` and configured per tool in the agent
profile, so all three upstream options (and every channel - browser, ACS, Twilio) get the same
retrieval behaviour through the shared bridge's tool-calling path.

Backends:
- **Azure AI Search** when ``AZURE_SEARCH_ENDPOINT`` and ``AZURE_SEARCH_INDEX``
  are set. Authenticates with the app's managed identity (Search Index Data
  Reader) or ``AZURE_SEARCH_API_KEY`` for local experiments. Uses keyword +
  semantic ranking by default, so no embedding deployment (and no extra model
  quota) is needed; set ``handler_config.vector_field`` to add an integrated-
  vectorizer text query when the index has one.
- **Local JSON** (``handler_config.local_file``) otherwise - a small keyword
  scorer so the demo and tests work without any search service.

Voice-specific guardrails: short timeout, few results, and truncated passages
keep the tool round-trip (and the tokens re-sent every turn) small.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from typing import Any

import aiohttp

from .auth import TokenProvider
from .profile import AgentProfile, ToolSpec

SEARCH_SCOPE = "https://search.azure.com/.default"
DEFAULT_SEARCH_API_VERSION = "2024-07-01"
DEFAULT_TOP = 3
DEFAULT_MAX_CHARS = 600
DEFAULT_TIMEOUT_SECONDS = 4.0
_WORD_RE = re.compile(r"[a-z0-9]+")
_STOP_WORDS = {
    "a", "an", "and", "are", "can", "do", "does", "for", "how", "i", "in", "is", "it",
    "my", "of", "on", "or", "the", "to", "what", "when", "where", "which", "with", "you",
}


@dataclass(frozen=True)
class SearchSettings:
    endpoint: str
    index: str
    api_version: str = DEFAULT_SEARCH_API_VERSION
    semantic_configuration: str | None = None
    api_key: str | None = None
    azure_client_id: str | None = None

    @classmethod
    def from_env(cls) -> "SearchSettings | None":
        endpoint = (os.getenv("AZURE_SEARCH_ENDPOINT") or "").strip().rstrip("/")
        index = (os.getenv("AZURE_SEARCH_INDEX") or "").strip()
        if not endpoint or not index:
            return None
        return cls(
            endpoint=endpoint,
            index=index,
            api_version=(os.getenv("AZURE_SEARCH_API_VERSION") or DEFAULT_SEARCH_API_VERSION).strip(),
            semantic_configuration=(os.getenv("AZURE_SEARCH_SEMANTIC_CONFIG") or "").strip() or None,
            api_key=os.getenv("AZURE_SEARCH_API_KEY") or None,
            azure_client_id=os.getenv("AZURE_CLIENT_ID") or None,
        )


class _SearchClient:
    def __init__(self, settings: SearchSettings):
        self.settings = settings
        self._tokens = None if settings.api_key else TokenProvider(settings.azure_client_id)
        self._session: aiohttp.ClientSession | None = None

    async def _headers(self) -> dict[str, str]:
        if self.settings.api_key:
            return {"api-key": self.settings.api_key}
        assert self._tokens is not None
        token = await self._tokens.get_token(SEARCH_SCOPE)
        return {"Authorization": f"Bearer {token}"}

    async def search(self, body: dict[str, Any], timeout: float) -> dict[str, Any]:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        url = (
            f"{self.settings.endpoint}/indexes/{self.settings.index}/docs/search"
            f"?api-version={self.settings.api_version}"
        )
        headers = {"Content-Type": "application/json", **await self._headers()}
        async with self._session.post(
            url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as response:
            if response.status >= 400:
                detail = (await response.text())[:300]
                raise RuntimeError(f"Azure AI Search returned HTTP {response.status}: {detail}")
            return await response.json()

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        if self._tokens is not None:
            await self._tokens.close()


_client: _SearchClient | None = None
_client_settings: SearchSettings | None = None


def _get_client() -> _SearchClient | None:
    global _client, _client_settings
    settings = SearchSettings.from_env()
    if settings is None:
        return None
    if _client is None or settings != _client_settings:
        _client = _SearchClient(settings)
        _client_settings = settings
    return _client


def describe_backend() -> str:
    settings = SearchSettings.from_env()
    return f"azure-ai-search:{settings.index}" if settings else "local"


async def close() -> None:
    global _client, _client_settings
    if _client is not None:
        await _client.close()
    _client = None
    _client_settings = None


def _truncate(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "\u2026"


def _terms(text: str) -> list[str]:
    return [word for word in _WORD_RE.findall(text.lower()) if word not in _STOP_WORDS]


def _int_config(cfg: dict[str, Any], key: str, default: int) -> int:
    value = cfg.get(key, default)
    return value if isinstance(value, int) and value > 0 else default


async def _search_local(query: str, cfg: dict[str, Any], profile: AgentProfile, top: int, max_chars: int) -> dict[str, Any]:
    local_file = cfg.get("local_file")
    if not isinstance(local_file, str) or not local_file:
        return {"error": "knowledge_search needs AZURE_SEARCH_ENDPOINT/AZURE_SEARCH_INDEX or handler_config.local_file"}
    path = (profile.base_dir / local_file).resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"error": f"Knowledge file not found: {path.name}"}
    except json.JSONDecodeError as exc:
        return {"error": f"Knowledge file is not valid JSON: {exc}"}

    collection = data.get(cfg.get("collection", "documents")) if isinstance(data, dict) else data
    if not isinstance(collection, list):
        return {"error": "Knowledge collection is not a list"}

    title_field = cfg.get("title_field", "title")
    content_field = cfg.get("content_field", "content")
    source_field = cfg.get("source_field", "source")
    query_terms = set(_terms(query))
    scored: list[tuple[int, dict[str, Any]]] = []
    for document in collection:
        if not isinstance(document, dict):
            continue
        title_terms = _terms(str(document.get(title_field, "")))
        content_terms = _terms(str(document.get(content_field, "")))
        score = 2 * sum(term in query_terms for term in title_terms) + sum(term in query_terms for term in content_terms)
        if score > 0:
            scored.append((score, document))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    results = [
        {
            "title": str(document.get(title_field, "")),
            "content": _truncate(document.get(content_field, ""), max_chars),
            "source": str(document.get(source_field, "")),
        }
        for _, document in scored[:top]
    ]
    return _result(query, "local", results)


async def _search_azure(
    client: _SearchClient, query: str, cfg: dict[str, Any], top: int, max_chars: int, timeout: float
) -> dict[str, Any]:
    title_field = cfg.get("title_field", "title")
    content_field = cfg.get("content_field", "content")
    source_field = cfg.get("source_field", "source")
    body: dict[str, Any] = {
        "search": query,
        "top": top,
        "select": ",".join(dict.fromkeys([title_field, content_field, source_field])),
    }
    semantic = client.settings.semantic_configuration
    if semantic:
        body["queryType"] = "semantic"
        body["semanticConfiguration"] = semantic
    vector_field = cfg.get("vector_field")
    if isinstance(vector_field, str) and vector_field:
        body["vectorQueries"] = [{"kind": "text", "text": query, "fields": vector_field, "k": top}]

    payload = await client.search(body, timeout)
    results = [
        {
            "title": str(document.get(title_field, "")),
            "content": _truncate(document.get(content_field, ""), max_chars),
            "source": str(document.get(source_field, "")),
        }
        for document in payload.get("value", [])[:top]
        if isinstance(document, dict)
    ]
    return _result(query, f"azure-ai-search:{client.settings.index}", results)


def _result(query: str, backend: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {
            "query": query,
            "backend": backend,
            "results": [],
            "message": "No matching knowledge was found. Say so and offer a human handoff instead of guessing.",
        }
    return {"query": query, "backend": backend, "results": results}


async def knowledge_search(arguments: dict[str, Any], tool: ToolSpec, profile: AgentProfile) -> dict[str, Any]:
    cfg = tool.handler_config
    argument = cfg.get("argument", "query")
    query = str(arguments.get(argument) or "").strip()
    if not query:
        return {"error": f"Missing required argument: {argument}"}
    top = _int_config(cfg, "top", DEFAULT_TOP)
    max_chars = _int_config(cfg, "max_chars", DEFAULT_MAX_CHARS)
    timeout = float(cfg.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))

    client = _get_client()
    if client is None:
        return await _search_local(query, cfg, profile, top, max_chars)
    try:
        return await _search_azure(client, query, cfg, top, max_chars, timeout)
    except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
        return {"error": f"Knowledge search is unavailable right now ({type(exc).__name__}). Offer a human handoff."}
