"""Composio webhook verification (Standard Webhooks scheme) and normalization."""
import base64
import hashlib
import hmac
import json
import time
from typing import Mapping, Optional

from .. import config
from ..errors import InvalidWebhook
from .base import BackendEvent

_KINDS = {
    "composio.connected_account.created": "connected",
    "composio.connected_account.active": "connected",
    "composio.connected_account.expired": "expired",
    "composio.connected_account.deleted": "removed",
}


def _secret_bytes(secret: str) -> bytes:
    if secret.startswith("whsec_"):
        return base64.b64decode(secret[len("whsec_"):])
    return secret.encode()


def sign(secret: str, msg_id: str, timestamp: str, body: bytes) -> str:
    signed = f"{msg_id}.{timestamp}.".encode() + body
    digest = hmac.new(_secret_bytes(secret), signed, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode()


def verify(headers: Mapping[str, str], body: bytes, secret: str, now: Optional[float] = None) -> None:
    if not secret:
        raise InvalidWebhook("webhook secret not configured")
    msg_id = headers.get("webhook-id", "")
    timestamp = headers.get("webhook-timestamp", "")
    sig_header = headers.get("webhook-signature", "")
    if not (msg_id and timestamp and sig_header):
        raise InvalidWebhook("missing signature headers")
    try:
        age = abs((now if now is not None else time.time()) - int(timestamp))
    except ValueError:
        raise InvalidWebhook("bad timestamp")
    if age > config.WEBHOOK_MAX_AGE_SECONDS:
        raise InvalidWebhook("stale timestamp")
    expected = sign(secret, msg_id, timestamp, body)
    if not any(hmac.compare_digest(expected, candidate) for candidate in sig_header.split(" ")):
        raise InvalidWebhook("signature mismatch")


def parse(headers: Mapping[str, str], body: bytes, secret: str) -> Optional[BackendEvent]:
    verify(headers, body, secret)
    try:
        payload = json.loads(body)
    except ValueError:
        raise InvalidWebhook("invalid JSON")
    kind = _KINDS.get(payload.get("type", ""))
    data = payload.get("data") or {}
    conn_id = data.get("id") or data.get("connected_account_id") or data.get("nanoid")
    if not kind or not conn_id:
        return None  # an event type we don't act on
    toolkit = (data.get("toolkit") or {}).get("slug") if isinstance(data.get("toolkit"), dict) else data.get("toolkit")
    return BackendEvent(
        event_id=headers["webhook-id"], kind=kind, backend_connection_id=str(conn_id),
        user_id=data.get("user_id"), toolkit_slug=toolkit, timestamp=int(headers["webhook-timestamp"]),
    )
