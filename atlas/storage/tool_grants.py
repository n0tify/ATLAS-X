"""The real tool grant source: explicit, scoped, revocable, owner-scoped reads.

Phase 08 shipped :class:`atlas.security.policy.ToolGrantSource` as a protocol and
:class:`~atlas.security.policy.NoToolGrants` as its only implementation, so
every tool decision denied. This module supplies the implementation the policy
was written for.

Design constraints, all of them load-bearing:

* **A grant names a capability, a user, a scope, and an active flag.** Nothing
  else. There is no role column, no wildcard, no "all tools" row, and no
  implicit grant: absence of a row is the denial, and it is the only denial the
  policy needs.
* **Reads are owner-scoped.** ``grants_for`` takes the user id the authorization
  boundary resolved from a session and filters on it in SQL, so a grant for one
  user can never be returned for another. This is the same rule the rest of the
  storage layer follows, and it is why a grant is not a shared-secret token.
* **Scope is a closed vocabulary.** ``NULL`` means the user's own resources;
  ``task:<id>`` narrows the grant to one task. A stored scope outside that
  vocabulary is *ignored on read* rather than repaired, because guessing what a
  malformed scope was meant to authorize is exactly the failure mode a security
  decision must not have.
* **No secrets.** A grant row holds a capability name and a scope. There is no
  token, key, or password column, and none may be added: a grant must be
  readable by anyone auditing the database without becoming a credential.

Writes are the operator's, not the user's. :meth:`ToolGrantRepo.grant` is
deliberately not reachable from any session-token path — see
``docs/TOOL_REGISTRY_REVIEW.md`` §5 — and there is no method that grants a
capability to "whoever is asking".

On the import direction: this module imports :mod:`atlas.security.policy` because
it must produce the ``ToolGrant`` values that protocol declares, and duplicating
that type here would create a second grant representation that could drift from
the one the policy authorizes against. ``policy`` itself imports no storage, so
this does not close a cycle on its own. The cycle is real at *package* level,
though: ``atlas.security.identity`` imports ``atlas.auth.service``, which imports
``atlas.storage``. Importing this module from ``atlas/storage/__init__.py``
therefore breaks depending on load order, which is why it is not re-exported
there. The rest of ``atlas.storage`` does not import ``atlas.security``, and
should not.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Iterable, Literal, Sequence

from atlas.security.policy import MAX_RESOURCE_ID, ToolGrant, normalize_tool_name
from atlas.storage.db import Database
from atlas.util import utcnow_iso

MAX_GRANTED_BY_LENGTH = 64
_SCOPE_PATTERN = re.compile(r"^task:(\d+)$")


def task_scope(task_id: int) -> str:
    """Build a task-scoped grant scope, or refuse an unusable task id."""

    if isinstance(task_id, bool) or not isinstance(task_id, int):
        raise TypeError("task id must be an integer")
    if not 0 < task_id <= MAX_RESOURCE_ID:
        raise ValueError("task id must be a positive row id")
    return f"task:{task_id}"


def parse_scope(scope: object) -> str | None | Literal[False]:
    """Classify a stored scope.

    Returns the scope string, ``None`` for a global grant, or ``False`` when the
    stored value is outside the closed vocabulary. ``False`` is deliberately not
    a valid scope: it cannot be confused with the global sentinel, and a caller
    that ignores the distinction still fails the grant closed.
    """

    if scope is None:
        return None
    if not isinstance(scope, str):
        return False
    match = _SCOPE_PATTERN.fullmatch(scope)
    if match is None:
        return False
    task_id = int(match.group(1))
    if not 0 < task_id <= MAX_RESOURCE_ID:
        return False
    return scope


class ToolGrantRepo:
    """Persist and read tool grants. Implements the Phase 08 grant protocol."""

    def __init__(self, db: Database, *, registry_ready: bool) -> None:
        self._db = db
        self._registry_ready = registry_ready

    @property
    def registry_ready(self) -> bool:
        """Whether a tool registry exists for grants to refer to.

        The policy denies with ``TOOL_NO_REGISTRY`` when this is False, which is
        the correct answer for a deployment that has no tool set: a grant for a
        capability nothing implements must not read as permission.
        """

        return self._registry_ready

    def grants_for(self, user_id: int) -> Sequence[ToolGrant]:
        """Active grants for exactly this user. Never another user's."""

        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
            # An unusable identity yields no grants. The policy has already
            # denied by the time this could be called with a bad id; returning
            # nothing keeps that true even if a future caller does not.
            return ()
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT tool_name, scope FROM tool_permissions "
                "WHERE user_id = ? AND active = 1 AND revoked_at IS NULL",
                (user_id,),
            ).fetchall()
        return _to_grants(rows)

    def grant(
        self,
        *,
        user_id: int,
        tool_name: str,
        granted_by: str,
        scope: str | None = None,
    ) -> int:
        """Record one grant. Operator path; not reachable from a session.

        Re-granting an identical capability replaces the existing row's
        ``granted_by`` rather than accumulating duplicates, so the table stays a
        record of the current grant rather than a history this phase cannot
        interpret.
        """

        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
            raise ValueError("user_id must be a positive row id")
        normalized = normalize_tool_name(tool_name)
        if normalized is None:
            raise ValueError("tool_name must be a usable capability name")
        if not isinstance(granted_by, str) or not granted_by.strip():
            raise ValueError("granted_by must name who made the grant")
        granted_by = granted_by.strip()[:MAX_GRANTED_BY_LENGTH]
        if scope is not None and parse_scope(scope) is False:
            raise ValueError("scope must be null or 'task:<id>'")

        now = utcnow_iso()
        with self._db.transaction() as conn:
            _require_user(conn, user_id)
            existing = conn.execute(
                "SELECT id FROM tool_permissions "
                "WHERE user_id = ? AND tool_name = ? AND IFNULL(scope, '') = IFNULL(?, '')",
                (user_id, tool_name, scope),
            ).fetchone()
            if existing is not None:
                conn.execute(
                    "UPDATE tool_permissions SET granted_by = ?, active = 1, "
                    "revoked_at = NULL WHERE id = ?",
                    (granted_by, existing["id"]),
                )
                return int(existing["id"])
            cursor = conn.execute(
                "INSERT INTO tool_permissions "
                "(user_id, tool_name, scope, granted_by, active, created_at) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                (user_id, tool_name, scope, granted_by, now),
            )
            row_id = cursor.lastrowid
            if row_id is None:
                raise RuntimeError("grant insert returned no row id")
            return int(row_id)

    def revoke(self, *, user_id: int, grant_id: int) -> bool:
        """Deactivate one grant. Returns whether a row changed."""

        if isinstance(grant_id, bool) or not isinstance(grant_id, int) or grant_id <= 0:
            raise ValueError("grant_id must be a positive row id")
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE tool_permissions SET active = 0, revoked_at = ? "
                "WHERE id = ? AND user_id = ? AND active = 1",
                (utcnow_iso(), grant_id, user_id),
            )
            return cursor.rowcount > 0

    def list_for_user(self, user_id: int) -> Sequence[dict[str, object]]:
        """Every grant row for one user, including inactive ones. Audit view."""

        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT id, tool_name, scope, granted_by, active, created_at, revoked_at "
                "FROM tool_permissions WHERE user_id = ? ORDER BY id ASC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def capabilities_for(self, user_id: int) -> frozenset[str]:
        """Normalized capability names this user currently holds, any scope."""

        return frozenset(
            normalize_tool_name(grant.tool_name) or "" for grant in self.grants_for(user_id)
        )


def _to_grants(rows: Iterable[sqlite3.Row]) -> tuple[ToolGrant, ...]:
    grants: list[ToolGrant] = []
    for row in rows:
        tool_name = row["tool_name"]
        if normalize_tool_name(tool_name) is None:
            continue
        scope = parse_scope(row["scope"])
        if scope is False:
            # A scope outside the vocabulary is not narrowed, it is meaningless.
            # Dropping the grant is the only safe reading.
            continue
        grants.append(ToolGrant(tool_name=str(tool_name), scope=scope))
    return tuple(grants)


def _require_user(conn: sqlite3.Connection, user_id: int) -> None:
    row = conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise ValueError("cannot grant a capability to a user that does not exist")
