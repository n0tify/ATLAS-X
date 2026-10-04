"""Authentication service: registration, login, sessions, lockout, password change."""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from atlas.auth.password import (
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
from atlas.auth.sessions import generate_session_token, hash_token
from atlas.config.settings import Settings
from atlas.storage.db import Database
from atlas.storage.repositories import SessionRepo, UserRepo
from atlas.util import add_minutes_iso, is_later_than, utcnow_iso

# Policy failures carry their own wording so the caller can show the exact
# reason. Every string below is safe to put in front of a person: none of them
# quotes the rejected value back, names the rule that caught it, or states a
# constraint the schema does not actually enforce.
_USERNAME_MESSAGES: dict[UsernameProblem, str] = {
    UsernameProblem.NOT_TEXT: "Username must be text.",
    UsernameProblem.EMPTY: "Enter a username.",
    UsernameProblem.NOT_PRINTABLE: "Username may only contain printable characters.",
    UsernameProblem.SURROUNDING_WHITESPACE: "Username must not start or end with whitespace.",
    UsernameProblem.TOO_SHORT: f"Username must be at least {USERNAME_MIN_LENGTH} characters.",
    UsernameProblem.TOO_LONG: f"Username must be at most {USERNAME_MAX_LENGTH} characters.",
}

_PASSWORD_MESSAGES: dict[PasswordProblem, str] = {
    PasswordProblem.NOT_TEXT: "Password must be text.",
    PasswordProblem.EMPTY: "Enter a password.",
    PasswordProblem.NOT_PRINTABLE: "Password may only contain printable characters.",
    PasswordProblem.TOO_SHORT: f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
    PasswordProblem.TOO_LONG: "Password is too long.",
}

DUPLICATE_USERNAME_MESSAGE = "That username is already in use."


class AuthError(Exception):
    pass


class AuthenticationFailed(AuthError):
    pass


class LoginLockedError(AuthError):
    pass


class UsernameRejected(AuthError):
    # Username breaks the registration identifier policy. The message is the
    # safe external reason; the underlying UsernameProblem stays internal.
    pass


class PasswordRejected(AuthError):
    # Password breaks the registration credential policy. Same contract.
    pass


class UsernameAlreadyExists(AuthError):
    pass


class AuthService:
    def __init__(
        self,
        db: Database,
        settings: Settings,
        user_repo: UserRepo | None = None,
        session_repo: SessionRepo | None = None,
    ) -> None:
        self._db = db
        self._settings = settings
        self._users = user_repo or UserRepo()
        self._sessions = session_repo or SessionRepo()

    def bootstrap(self) -> None:
        self._db.initialize()

    def register(self, username: str, password: str) -> dict[str, Any]:
        username_fault = username_problem(username)
        if username_fault is not None:
            raise UsernameRejected(_USERNAME_MESSAGES[username_fault])
        password_fault = password_problem(password)
        if password_fault is not None:
            raise PasswordRejected(_PASSWORD_MESSAGES[password_fault])
        password_hash = hash_password(password)
        with self._db.transaction() as conn:
            if self._users.exists(conn, username):
                raise UsernameAlreadyExists(DUPLICATE_USERNAME_MESSAGE)
            try:
                user_id = self._users.create(
                    conn, username=username, password_hash=password_hash
                )
            except sqlite3.IntegrityError as exc:
                # Two registrations can pass the exists() check before either
                # inserts. The unique index is the real guarantee, so its
                # rejection is reported the same way instead of surfacing as an
                # opaque SQL error.
                raise UsernameAlreadyExists(DUPLICATE_USERNAME_MESSAGE) from exc
            self._record_registration(conn, user_id)
            return self._public_user(conn, user_id)

    def login(self, username: str, password: str) -> dict[str, Any]:
        with self._db.transaction() as conn:
            user = self._users.get_by_username(conn, username)
        if user is None:
            self._sleep_delay()
            raise AuthenticationFailed("invalid username or password")
        if user["locked_until"] and is_later_than(user["locked_until"], utcnow_iso()):
            raise LoginLockedError("account temporarily locked")
        if not verify_password(user["password_hash"], password):
            attempts = int(user["failed_login_attempts"]) + 1
            locked_until = None
            if attempts >= self._settings.auth_max_login_attempts:
                locked_until = add_minutes_iso(
                    utcnow_iso(), self._settings.auth_lockout_minutes
                )
            with self._db.transaction() as conn:
                self._users.record_login_failure(
                    conn, int(user["id"]), attempts, locked_until
                )
            self._sleep_delay()
            raise AuthenticationFailed("invalid username or password")
        with self._db.transaction() as conn:
            self._users.reset_login_failures(conn, int(user["id"]))
            token = generate_session_token()
            expires_at = add_minutes_iso(
                utcnow_iso(), self._settings.auth_session_ttl_minutes
            )
            self._sessions.create(
                conn,
                user_id=int(user["id"]),
                token_hash=hash_token(token),
                expires_at=expires_at,
            )
            return {"token": token, "user": self._public_user(conn, int(user["id"]))}

    def validate_session(self, token: str) -> dict[str, Any] | None:
        with self._db.transaction() as conn:
            self._sessions.delete_expired(conn, utcnow_iso())
            session = self._sessions.get_valid(conn, hash_token(token))
            if session is None:
                return None
            now = utcnow_iso()
            if not is_later_than(session["expires_at"], now):
                return None
            return self._public_user(conn, int(session["user_id"]))

    def logout(self, token: str) -> bool:
        with self._db.transaction() as conn:
            return self._sessions.revoke(conn, hash_token(token))

    def change_password(
        self, user_id: int, current_password: str, new_password: str
    ) -> None:
        password_fault = password_problem(new_password)
        if password_fault is not None:
            raise PasswordRejected(_PASSWORD_MESSAGES[password_fault])
        with self._db.transaction() as conn:
            user = self._users.get_by_id(conn, user_id)
            if user is None:
                raise AuthenticationFailed("invalid username or password")
            if not verify_password(user["password_hash"], current_password):
                raise AuthenticationFailed("invalid username or password")
            self._users.update_password_hash(conn, user_id, hash_password(new_password))
            self._sessions.revoke_all_for_user(conn, user_id)

    def _public_user(self, conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
        user = self._users.get_public(conn, user_id)
        if user is None:
            raise AuthError("user record missing")
        return user

    def _record_registration(self, conn: sqlite3.Connection, user_id: int) -> None:
        from atlas.storage.repositories import ProvenanceRepo

        ProvenanceRepo().record(
            conn,
            task_id=None,
            execution_id=None,
            event_type="user.registered",
            actor="auth",
            detail={"user_id": user_id},
        )

    def _sleep_delay(self) -> None:
        time.sleep(self._settings.auth_failure_delay_seconds)
