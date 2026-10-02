"""Authenticated identity: the only currency authorization accepts.

An :class:`Identity` is derived from a session token that the server itself
issued. No public entry point accepts a bare ``user_id`` from a caller, so a
request cannot nominate the actor it wants to act as.
"""

from __future__ import annotations

from dataclasses import dataclass

from atlas.auth.service import AuthService
from atlas.auth.sessions import hash_token
from atlas.security.errors import Unauthenticated
from atlas.security.policy import DenyReason
from atlas.storage.db import Database
from atlas.storage.repositories import SessionRepo, UserRepo
from atlas.util import is_later_than, utcnow_iso


@dataclass(frozen=True)
class Identity:
    """A verified caller. Treat as opaque; never rebuild it from request data."""

    user_id: int
    username: str
    session_id: int
    expires_at: str


class IdentityResolver:
    """Turns a session token into an :class:`Identity`, or refuses.

    Expiry and revocation are decided by :meth:`AuthService.validate_session`,
    which is the single authoritative authentication check. This resolver only
    attaches session metadata and re-confirms the session is still present, so
    the expiry invariant is not duplicated here.
    """

    def __init__(
        self,
        db: Database,
        auth: AuthService,
        *,
        sessions: SessionRepo | None = None,
        users: UserRepo | None = None,
    ) -> None:
        self._db = db
        self._auth = auth
        self._sessions = sessions or SessionRepo()
        self._users = users or UserRepo()

    def from_session_token(self, session_token: object) -> Identity:
        if not isinstance(session_token, str) or not session_token.strip():
            raise Unauthenticated(DenyReason.MISSING_IDENTITY)

        user = self._auth.validate_session(session_token)
        if user is None:
            raise Unauthenticated(DenyReason.INVALID_IDENTITY)

        user_id = user.get("id")
        username = user.get("username")
        if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
            raise Unauthenticated(DenyReason.INVALID_IDENTITY)
        if not isinstance(username, str) or not username:
            raise Unauthenticated(DenyReason.INVALID_IDENTITY)

        with self._db.transaction() as conn:
            session = self._sessions.get_valid(conn, hash_token(session_token))
            if session is None or not is_later_than(str(session["expires_at"]), utcnow_iso()):
                # Revoked or expired between authentication and this lookup.
                raise Unauthenticated(DenyReason.INVALID_IDENTITY)
            session_id = session["id"]
            expires_at = str(session["expires_at"])
            current = self._users.get_public(conn, user_id)
            if current is None or current.get("username") != username:
                raise Unauthenticated(DenyReason.INVALID_IDENTITY)

        if not isinstance(session_id, int) or isinstance(session_id, bool) or session_id <= 0:
            raise Unauthenticated(DenyReason.INVALID_IDENTITY)
        return Identity(
            user_id=user_id,
            username=username,
            session_id=session_id,
            expires_at=expires_at,
        )
