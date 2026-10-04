"""Registration, login, sessions, lockout, and password change — all local."""

from atlas.auth.password import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    USERNAME_MAX_LENGTH,
    USERNAME_MIN_LENGTH,
    PasswordProblem,
    UsernameProblem,
    hash_password,
    password_problem,
    username_problem,
    verify_password,
)
from atlas.auth.service import (
    DUPLICATE_USERNAME_MESSAGE,
    AuthenticationFailed,
    AuthError,
    AuthService,
    LoginLockedError,
    PasswordRejected,
    UsernameAlreadyExists,
    UsernameRejected,
)
from atlas.auth.sessions import SESSION_COOKIE_ATTRIBUTES, generate_session_token, hash_token

__all__ = [
    "AuthError",
    "AuthenticationFailed",
    "LoginLockedError",
    "PasswordRejected",
    "UsernameAlreadyExists",
    "UsernameRejected",
    "AuthService",
    "DUPLICATE_USERNAME_MESSAGE",
    "MIN_PASSWORD_LENGTH",
    "MAX_PASSWORD_LENGTH",
    "USERNAME_MIN_LENGTH",
    "USERNAME_MAX_LENGTH",
    "PasswordProblem",
    "UsernameProblem",
    "hash_password",
    "password_problem",
    "username_problem",
    "verify_password",
    "generate_session_token",
    "hash_token",
    "SESSION_COOKIE_ATTRIBUTES",
]
