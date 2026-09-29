"""Environment-backed telephony settings."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from ..sessions import BUSY_MESSAGE

SUPPORTED_PROVIDERS = frozenset({"acs", "twilio"})
E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")
MIN_SECRET_LENGTH = 16


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class TelephonySettings:
    """Which phone channels are enabled and how they authenticate.

    ``TELEPHONY_PROVIDERS`` is a comma list of ``acs`` and/or ``twilio``; empty
    (the default) mounts no telephony routes, so the browser-only demo is unchanged.
    ``TELEPHONY_WEBHOOK_SECRET`` signs per-call tokens and never leaves the app;
    ``ACS_EVENTGRID_SECRET`` is the separate value placed in the Event Grid endpoint URL.
    Media tokens are short-lived (``TELEPHONY_TOKEN_TTL_SECONDS``); ACS callback tokens
    last for the maximum call length (``TELEPHONY_CALLBACK_TTL_SECONDS``).
    """

    providers: frozenset[str] = field(default_factory=frozenset)
    webhook_secret: str = ""
    acs_eventgrid_secret: str = ""
    public_base_url: str | None = None
    acs_endpoint: str | None = None
    acs_connection_string: str | None = None
    twilio_auth_token: str | None = None
    twilio_skip_signature_validation: bool = False
    overflow_number: str | None = None
    busy_message: str = BUSY_MESSAGE
    token_ttl_seconds: int = 300
    callback_token_ttl_seconds: int = 14400
    reservation_ttl_seconds: int = 30
    handshake_timeout_seconds: float = 10.0
    max_pending_handshakes: int = 50
    azure_client_id: str | None = None

    def __post_init__(self) -> None:
        unknown = set(self.providers) - SUPPORTED_PROVIDERS
        if unknown:
            allowed = ", ".join(sorted(SUPPORTED_PROVIDERS))
            raise ValueError(f"TELEPHONY_PROVIDERS has unknown values {sorted(unknown)}; allowed: {allowed}")
        if not self.providers:
            return
        if len(self.webhook_secret) < MIN_SECRET_LENGTH:
            raise ValueError(
                f"TELEPHONY_WEBHOOK_SECRET must be at least {MIN_SECRET_LENGTH} characters when telephony is enabled"
            )
        if "acs" in self.providers:
            if not (self.acs_endpoint or self.acs_connection_string):
                raise ValueError("ACS telephony needs ACS_ENDPOINT (managed identity) or ACS_CONNECTION_STRING (local only)")
            # The Event Grid secret travels in a URL; keep it separate from the call-token signing key
            # so exposing the subscription endpoint cannot be used to forge media/callback tokens.
            if len(self.acs_eventgrid_secret) < MIN_SECRET_LENGTH:
                raise ValueError(f"ACS_EVENTGRID_SECRET must be at least {MIN_SECRET_LENGTH} characters")
            if self.acs_eventgrid_secret == self.webhook_secret:
                raise ValueError("ACS_EVENTGRID_SECRET must differ from TELEPHONY_WEBHOOK_SECRET")
        if "twilio" in self.providers and not self.twilio_auth_token and not self.twilio_skip_signature_validation:
            raise ValueError(
                "Twilio telephony needs TWILIO_AUTH_TOKEN to validate X-Twilio-Signature "
                "(TWILIO_SKIP_SIGNATURE_VALIDATION=true is for local tunnels only)"
            )
        if self.overflow_number and not E164_RE.match(self.overflow_number):
            raise ValueError("TELEPHONY_OVERFLOW_NUMBER must be an E.164 number such as +15555550100")
        if self.public_base_url and not self.public_base_url.startswith(("https://", "http://")):
            raise ValueError("PUBLIC_BASE_URL must start with https:// (or http:// for local tests)")

    @property
    def enabled(self) -> bool:
        return bool(self.providers)

    @classmethod
    def from_env(cls) -> "TelephonySettings":
        providers = frozenset(
            item.strip().lower() for item in (os.getenv("TELEPHONY_PROVIDERS") or "").split(",") if item.strip()
        )
        raw_ttl = os.getenv("TELEPHONY_TOKEN_TTL_SECONDS", "300")
        raw_callback_ttl = os.getenv("TELEPHONY_CALLBACK_TTL_SECONDS", "14400")
        try:
            ttl = int(raw_ttl)
            callback_ttl = int(raw_callback_ttl)
        except ValueError as exc:
            raise ValueError("TELEPHONY_TOKEN_TTL_SECONDS and TELEPHONY_CALLBACK_TTL_SECONDS must be integers") from exc
        return cls(
            providers=providers,
            webhook_secret=(os.getenv("TELEPHONY_WEBHOOK_SECRET") or "").strip(),
            acs_eventgrid_secret=(os.getenv("ACS_EVENTGRID_SECRET") or "").strip(),
            public_base_url=((os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/") or None),
            acs_endpoint=(os.getenv("ACS_ENDPOINT") or "").strip() or None,
            acs_connection_string=os.getenv("ACS_CONNECTION_STRING") or None,
            twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN") or None,
            twilio_skip_signature_validation=_truthy(os.getenv("TWILIO_SKIP_SIGNATURE_VALIDATION")),
            overflow_number=(os.getenv("TELEPHONY_OVERFLOW_NUMBER") or "").strip() or None,
            busy_message=(os.getenv("TELEPHONY_BUSY_MESSAGE") or BUSY_MESSAGE).strip(),
            token_ttl_seconds=max(30, ttl),
            callback_token_ttl_seconds=max(ttl, callback_ttl),
            azure_client_id=os.getenv("AZURE_CLIENT_ID") or None,
        )
