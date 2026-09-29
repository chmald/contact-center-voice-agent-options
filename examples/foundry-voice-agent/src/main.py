from __future__ import annotations

import logging

from voiceagent_core.auth import TokenProvider
from voiceagent_core.server import create_app
from voiceagent_core.settings import CommonSettings

from voice_agent_bridge import VoiceAgentBridge, VoiceAgentSettings

common = CommonSettings.from_env()
voice_agent = VoiceAgentSettings.from_env()

logging.basicConfig(
    level=getattr(logging, common.log_level.upper(), logging.INFO),
    format="%(message)s",
)

token_provider = TokenProvider(common.azure_client_id)


def bridge_factory(profile, tools, emit, metrics, session_id):
    return VoiceAgentBridge(
        profile,
        tools,
        emit,
        metrics,
        session_id,
        settings=voice_agent,
        token_provider=token_provider,
    )


app = create_app(bridge_factory, common)
app.router.on_shutdown.append(token_provider.close)
