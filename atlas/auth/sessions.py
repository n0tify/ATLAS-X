"""Opaque session tokens. Only digests are persisted."""

from __future__ import annotations

import hashlib
import secrets

SESSION_COOKIE_ATTRIBUTES: tuple[str, ...] = (
    "HttpOnly",
    "SameSite=Lax",
    "Path=/",
)


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def cookie_attributes(secure: bool) -> tuple[str, ...]:
    attrs = list(SESSION_COOKIE_ATTRIBUTES)
    if secure:
        attrs.append("Secure")
    return tuple(attrs)
