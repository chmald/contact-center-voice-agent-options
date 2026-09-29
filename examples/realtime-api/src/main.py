from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from voiceagent_core.auth import TokenProvider
from voiceagent_core.server import create_app
from voiceagent_core.settings import CommonSettings

from realtime_api_bridge import RealtimeApiBridge, RealtimeApiSettings

common = CommonSettings.from_env()
realtime_api = RealtimeApiSettings.from_env()

logging.basicConfig(
    level=getattr(logging, common.log_level.upper(), logging.INFO),
    format="%(message)s",
)

token_provider = TokenProvider(common.azure_client_id)


def bridge_factory(profile, tools, emit, metrics, session_id):
    return RealtimeApiBridge(
        profile,
        tools,
        emit,
        metrics,
        session_id,
        settings=realtime_api,
        token_provider=token_provider,
    )


app = create_app(bridge_factory, common)
_base_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _lifespan(app_instance):
    async with _base_lifespan(app_instance):
        try:
            yield
        finally:
            await token_provider.close()


app.router.lifespan_context = _lifespan
