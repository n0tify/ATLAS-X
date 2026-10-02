"""Authentication service: registration, login, sessions, lockout, password change."""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from atlas.auth.password import hash_password, validate_username, verify_password
from atlas.auth.sessions import generate_session_token, hash_token
from atlas.config.settings import Settings
from atlas.storage.db import Database
from atlas.storage.repositories import SessionRepo, UserRepo
from atlas.util import add_minutes_iso, is_later_than, utcnow_iso


class AuthError(Exception):
    pass


class AuthenticationFailed(AuthError):
    pass


class LoginLockedError(AuthError):
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
        if not validate_username(username):
            raise ValueError("username must be 3-32 characters of letters, digits, '_' or '-'")
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        password_hash = hash_password(password)
        with self._db.transaction() as conn:
            if self._users.exists(conn, username):
                raise UsernameAlreadyExists(f"username '{username}' is already registered")
            user_id = self._users.create(conn, username=username, password_hash=password_hash)
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
        if len(new_password) < 8:
            raise ValueError("new password must be at least 8 characters")
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
