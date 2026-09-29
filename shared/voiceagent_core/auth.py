"""Authentication helpers for Azure-hosted realtime APIs."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from azure.identity.aio import DefaultAzureCredential


@dataclass
class _CachedToken:
    token: str
    expires_on: int


class TokenProvider:
    """Async Azure token provider with simple per-scope caching."""

    def __init__(self, azure_client_id: str | None = None):
        kwargs = {}
        if azure_client_id:
            kwargs["managed_identity_client_id"] = azure_client_id
        self._credential = DefaultAzureCredential(**kwargs)
        self._cache: dict[str, _CachedToken] = {}
        self._lock = asyncio.Lock()

    async def get_token(self, scope: str) -> str:
        async with self._lock:
            cached = self._cache.get(scope)
            if cached and cached.expires_on - time.time() > 300:
                return cached.token
            token = await self._credential.get_token(scope)
            self._cache[scope] = _CachedToken(token=token.token, expires_on=token.expires_on)
            return token.token

    async def close(self) -> None:
        await self._credential.close()


async def build_auth_headers(api_key: str | None, scope: str, provider: TokenProvider) -> dict[str, str]:
    """Build API-key headers for local development or bearer auth for managed identity."""

    if api_key:
        return {"api-key": api_key}
    return {"Authorization": f"Bearer {await provider.get_token(scope)}"}
