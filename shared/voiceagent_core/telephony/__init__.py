"""Optional phone-network channels for the shared voice bridge.

``mount_telephony`` adds the routes for each provider listed in
``TELEPHONY_PROVIDERS``. Nothing is mounted when it is empty.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from ..sessions import SessionHub
from .settings import SUPPORTED_PROVIDERS, TelephonySettings

__all__ = ["SUPPORTED_PROVIDERS", "TelephonySettings", "mount_telephony"]


def mount_telephony(
    app: FastAPI,
    hub: SessionHub,
    settings: TelephonySettings,
    *,
    acs_client_factory: Any = None,
) -> None:
    if "acs" in settings.providers:
        from .acs import build_acs_router

        app.include_router(build_acs_router(hub, settings, acs_client_factory))
    if "twilio" in settings.providers:
        from .twilio import build_twilio_router

        app.include_router(build_twilio_router(hub, settings))
    if "asterisk" in settings.providers:
        from .asterisk import build_asterisk_router

        app.include_router(build_asterisk_router(hub, settings))
