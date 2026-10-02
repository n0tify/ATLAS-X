"""Registration, login, sessions, lockout, and password change — all local."""

from atlas.auth.password import hash_password, verify_password
from atlas.auth.service import (
    AuthenticationFailed,
    AuthError,
    AuthService,
    LoginLockedError,
    UsernameAlreadyExists,
)
from atlas.auth.sessions import SESSION_COOKIE_ATTRIBUTES, generate_session_token, hash_token

__all__ = [
    "AuthError",
    "AuthenticationFailed",
    "LoginLockedError",
    "UsernameAlreadyExists",
    "AuthService",
    "hash_password",
    "verify_password",
    "generate_session_token",
    "hash_token",
    "SESSION_COOKIE_ATTRIBUTES",
]
