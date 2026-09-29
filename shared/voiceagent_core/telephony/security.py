"""Security helpers for telephony webhooks and media WebSockets.

- Webhooks that cannot carry a per-call token (the Event Grid ``IncomingCall``
  subscription) are protected by a shared secret in the query string.
- Everything the app hands to the phone platform for a specific call (ACS
  callback URL, ACS media transport URL, Twilio ``<Stream>`` parameter) carries
  a short-lived HMAC token bound to the provider and call id, so a leaked URL
  cannot be replayed later or against another provider.
- Twilio webhooks are validated with the documented ``X-Twilio-Signature``
  scheme (HMAC-SHA1 over the full URL plus sorted POST parameters).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from collections.abc import Mapping


def secrets_match(expected: str, provided: str | None) -> bool:
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected.encode("utf-8"), provided.encode("utf-8"))


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: str, message: str) -> str:
    return _b64url(hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest())


def mint_call_token(secret: str, provider: str, call_id: str, ttl_seconds: int = 300, now: float | None = None) -> str:
    expires = int((now if now is not None else time.time()) + ttl_seconds)
    encoded_call = _b64url(call_id.encode("utf-8"))
    signature = _sign(secret, f"{provider}:{encoded_call}:{expires}")
    return f"{encoded_call}.{expires}.{signature}"


def verify_call_token(secret: str, provider: str, token: str | None, now: float | None = None) -> str | None:
    """Return the call id when the token is valid for ``provider`` and unexpired, else ``None``."""

    if not secret or not token or token.count(".") != 2:
        return None
    encoded_call, raw_expires, signature = token.split(".")
    try:
        expires = int(raw_expires)
    except ValueError:
        return None
    if expires < (now if now is not None else time.time()):
        return None
    expected = _sign(secret, f"{provider}:{encoded_call}:{expires}")
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        return _b64url_decode(encoded_call).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def twilio_signature(auth_token: str, url: str, params: Mapping[str, str]) -> str:
    payload = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    digest = hmac.new(auth_token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def verify_twilio_signature(auth_token: str, url: str, params: Mapping[str, str], signature: str | None) -> bool:
    if not auth_token or not signature:
        return False
    return hmac.compare_digest(twilio_signature(auth_token, url, params), signature)
