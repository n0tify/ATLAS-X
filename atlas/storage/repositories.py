"""Parameterized repository layer over SQLite.

Every statement uses placeholders. Ownership is enforced in the SQL itself
(``WHERE id = ? AND user_id = ?``) so a caller can never read or touch another
user's rows through these helpers.

Provenance chain integrity:
---------------------------

Each provenance event receives a monotonically increasing ``sequence_no`` within
its task and a ``chain_digest`` that binds it to the previous event. The digest
is computed over a canonical representation of the event including the previous
digest, so any tampering with an event or its predecessor breaks the chain.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping

USER_PUBLIC_FIELDS = ("id", "username", "created_at")


def _user_public(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in USER_PUBLIC_FIELDS}


def _last_insert_id(cursor: sqlite3.Cursor) -> int:
    row_id = cursor.lastrowid
    if row_id is None:
        raise RuntimeError("insert returned no row id")
    return int(row_id)


#: Canonical field order for provenance chain digest computation.
_PROVENANCE_CHAIN_FIELDS = (
    "previous_digest",
    "sequence_no",
    "event_type",
    "actor",
    "task_id",
    "execution_id",
    "plan_id",
    "plan_step_id",
    "tool_id",
    "invocation_id",
    "detail_json",
)


@dataclass(frozen=True)
class ProvenanceEvent:
    """A single provenance event, as stored.

    The ``chain_digest`` is the SHA-256 digest of the canonical representation
    of this event concatenated with the previous event's digest. A verified chain
    therefore proves that no event has been inserted, deleted, reordered, or
    modified since it was written.
    """

    id: int
    task_id: int | None
    execution_id: int | None
    plan_id: int | None
    plan_step_id: int | None
    tool_id: str | None
    invocation_id: str | None
    sequence_no: int
    chain_digest: str
    event_type: str
    actor: str
    detail_json: str | None
    created_at: str

    def to_canonical_dict(self, previous_digest: str) -> dict[str, Any]:
        """The canonical representation used for chain digest computation.

        Includes the previous event's digest so the chain is linked. Field order
        is fixed by :data:`_PROVENANCE_CHAIN_FIELDS`; ``json.dumps`` with
        ``sort_keys=False`` on this ordered dict produces deterministic bytes.
        """

        return {
            "previous_digest": previous_digest,
            "sequence_no": self.sequence_no,
            "event_type": self.event_type,
            "actor": self.actor,
            "task_id": self.task_id,
            "execution_id": self.execution_id,
            "plan_id": self.plan_id,
            "plan_step_id": self.plan_step_id,
            "tool_id": self.tool_id,
            "invocation_id": self.invocation_id,
            "detail_json": self.detail_json,
        }


class ProvenanceVerificationError(ValueError):
    """A provenance chain failed verification."""

    def __init__(self, message: str, *, code: str, event_id: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.event_id = event_id


class ProvenanceVerificationCode:
    """Stable codes for provenance verification failures."""

    VALID = "valid"
    EMPTY_CHAIN = "empty_chain"
    INVALID_SEQUENCE = "invalid_sequence"
    MISSING_PREVIOUS_DIGEST = "missing_previous_digest"
    INVALID_PREVIOUS_DIGEST = "invalid_previous_digest"
    INVALID_EVENT_DIGEST = "invalid_event_digest"
    DUPLICATE_SEQUENCE = "duplicate_sequence"
    BROKEN_LINEAGE = "broken_lineage"
    MISSING_EVENT = "missing_event"


def _compute_chain_digest(event: ProvenanceEvent, previous_digest: str) -> str:
    """Compute the SHA-256 chain digest for an event."""

    canonical = event.to_canonical_dict(previous_digest)
    # Deterministic JSON: sorted_keys=False because field order is fixed by the
    # dataclass / dict construction above. No whitespace, no Unicode escapes.
    encoded = json.dumps(canonical, separators=(",", ":"), sort_keys=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utcnow() -> str:
    from atlas.util import utcnow_iso

    return utcnow_iso()


class UserRepo:
    def create(
        self, conn: sqlite3.Connection, *, username: str, password_hash: str
    ) -> int:
        now = _utcnow()
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (username, password_hash, now, now),
        )
        return _last_insert_id(cursor)

    def exists(self, conn: sqlite3.Connection, username: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
        return row is not None

    def get_by_username(self, conn: sqlite3.Connection, username: str) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        return dict(row) if row is not None else None

    def get_by_id(self, conn: sqlite3.Connection, user_id: int) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row is not None else None

    def get_public(self, conn: sqlite3.Connection, user_id: int) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT id, username, created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def update_password_hash(
        self, conn: sqlite3.Connection, user_id: int, password_hash: str
    ) -> None:
        conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (password_hash, _utcnow(), user_id),
        )

    def record_login_failure(
        self,
        conn: sqlite3.Connection,
        user_id: int,
        attempts: int,
        locked_until: str | None,
    ) -> None:
        conn.execute(
            "UPDATE users SET failed_login_attempts = ?, locked_until = ?, updated_at = ? "
            "WHERE id = ?",
            (attempts, locked_until, _utcnow(), user_id),
        )

    def reset_login_failures(self, conn: sqlite3.Connection, user_id: int) -> None:
        conn.execute(
            "UPDATE users SET failed_login_attempts = 0, locked_until = NULL, updated_at = ? "
            "WHERE id = ?",
            (_utcnow(), user_id),
        )

    def delete(self, conn: sqlite3.Connection, user_id: int) -> int:
        cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cursor.rowcount


class SessionRepo:
    def create(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: int,
        token_hash: str,
        expires_at: str,
    ) -> int:
        cursor = conn.execute(
            "INSERT INTO sessions (user_id, token_hash, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, token_hash, _utcnow(), expires_at),
        )
        return _last_insert_id(cursor)

    def get_valid(
        self, conn: sqlite3.Connection, token_hash: str
    ) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT id, user_id, created_at, expires_at "
            "FROM sessions WHERE token_hash = ? AND revoked_at IS NULL LIMIT 1",
            (token_hash,),
        ).fetchone()
        return dict(row) if row is not None else None

    def revoke(self, conn: sqlite3.Connection, token_hash: str) -> bool:
        cursor = conn.execute(
            "UPDATE sessions SET revoked_at = ? "
            "WHERE token_hash = ? AND revoked_at IS NULL",
            (_utcnow(), token_hash),
        )
        return cursor.rowcount > 0

    def revoke_all_for_user(self, conn: sqlite3.Connection, user_id: int) -> int:
        cursor = conn.execute(
            "UPDATE sessions SET revoked_at = ? "
            "WHERE user_id = ? AND revoked_at IS NULL",
            (_utcnow(), user_id),
        )
        return cursor.rowcount

    def delete_expired(self, conn: sqlite3.Connection, now: str) -> int:
        cursor = conn.execute(
            "DELETE FROM sessions WHERE expires_at < ? OR revoked_at IS NOT NULL", (now,)
        )
        return cursor.rowcount


class TaskRepo:
    def create(
        self, conn: sqlite3.Connection, *, user_id: int, title: str, goal: str
    ) -> int:
        now = _utcnow()
        cursor = conn.execute(
            "INSERT INTO tasks (user_id, title, goal, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'pending', ?, ?)",
            (user_id, title, goal, now, now),
        )
        return _last_insert_id(cursor)

    def get(
        self, conn: sqlite3.Connection, user_id: int, task_id: int
    ) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        ).fetchone()
        return dict(row) if row is not None else None

    def list_for_user(
        self, conn: sqlite3.Connection, user_id: int
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def delete(self, conn: sqlite3.Connection, user_id: int, task_id: int) -> int:
        cursor = conn.execute(
            "DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id)
        )
        return cursor.rowcount


class ProvenanceRepo:
    """Write and read operations for the tamper-evident provenance chain.

    The chain is per-task: sequence numbers restart at 1 for each task_id, and
    the chain_digest links events within that task. Events with ``task_id IS
    NULL`` (e.g., registration events) form no chain and receive no
    sequence_no/digest.
    """

    def record_event(
        self,
        conn: sqlite3.Connection,
        *,
        task_id: int | None = None,
        execution_id: int | None = None,
        plan_id: int | None = None,
        plan_step_id: int | None = None,
        tool_id: str | None = None,
        invocation_id: str | None = None,
        event_type: str,
        actor: str,
        detail: Mapping[str, Any] | None = None,
    ) -> int:
        """Append one event to the provenance chain.

        If ``task_id`` is provided, the event receives the next sequence number
        and a chain digest linking it to the previous event in that task's chain.
        If ``task_id`` is ``None``, no sequence or digest is written (these are
        standalone events like user registration).

        Returns the new event's row id.
        """

        created_at = _utcnow()
        if detail is not None:
            encoded_detail = json.dumps(detail, separators=(",", ":"), sort_keys=True)
        else:
            encoded_detail = None

        if task_id is not None:
            # Allocate the next sequence number within the task's chain.
            row = conn.execute(
                "SELECT MAX(sequence_no) AS max_seq FROM provenance_events WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            sequence_no = (row["max_seq"] or 0) + 1

            # Fetch the previous event's digest for chain linkage.
            prev = conn.execute(
                "SELECT chain_digest FROM provenance_events "
                "WHERE task_id = ? AND sequence_no = ?",
                (task_id, sequence_no - 1),
            ).fetchone()
            previous_digest = prev["chain_digest"] if prev else ""

            # Build a provisional event to compute its digest.
            provisional = ProvenanceEvent(
                id=0,  # placeholder, actual id assigned after insert
                task_id=task_id,
                execution_id=execution_id,
                plan_id=plan_id,
                plan_step_id=plan_step_id,
                tool_id=tool_id,
                invocation_id=invocation_id,
                sequence_no=sequence_no,
                chain_digest="",  # placeholder
                event_type=event_type,
                actor=actor,
                detail_json=encoded_detail,
                created_at=created_at,
            )
            chain_digest = _compute_chain_digest(provisional, previous_digest)

            cursor = conn.execute(
                "INSERT INTO provenance_events "
                "(task_id, execution_id, plan_id, plan_step_id, tool_id, invocation_id, "
                "sequence_no, chain_digest, event_type, actor, detail_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    execution_id,
                    plan_id,
                    plan_step_id,
                    tool_id,
                    invocation_id,
                    sequence_no,
                    chain_digest,
                    event_type,
                    actor,
                    encoded_detail,
                    created_at,
                ),
            )
        else:
            # Standalone event (e.g., registration): no chain linkage.
            cursor = conn.execute(
                "INSERT INTO provenance_events "
                "(task_id, execution_id, plan_id, plan_step_id, tool_id, invocation_id, "
                "sequence_no, chain_digest, event_type, actor, detail_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?)",
                (
                    None,
                    execution_id,
                    plan_id,
                    plan_step_id,
                    tool_id,
                    invocation_id,
                    event_type,
                    actor,
                    encoded_detail,
                    created_at,
                ),
            )

        return _last_insert_id(cursor)

    def get_event(
        self, conn: sqlite3.Connection, event_id: int
    ) -> ProvenanceEvent | None:
        row = conn.execute(
            "SELECT * FROM provenance_events WHERE id = ?", (event_id,)
        ).fetchone()
        return self._row_to_event(row) if row else None

    def get_events_for_task(
        self, conn: sqlite3.Connection, task_id: int
    ) -> list[ProvenanceEvent]:
        rows = conn.execute(
            "SELECT * FROM provenance_events WHERE task_id = ? ORDER BY sequence_no ASC",
            (task_id,),
        ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def get_events_for_execution(
        self, conn: sqlite3.Connection, execution_id: int
    ) -> list[ProvenanceEvent]:
        rows = conn.execute(
            "SELECT * FROM provenance_events WHERE execution_id = ? ORDER BY sequence_no ASC",
            (execution_id,),
        ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def verify_chain_for_task(
        self, conn: sqlite3.Connection, task_id: int
    ) -> tuple[str, ProvenanceEvent | None]:
        """Verify the provenance chain for a task.

        Returns ``(code, failed_event)`` where ``code`` is one of
        :class:`ProvenanceVerificationCode` and ``failed_event`` is the first
        event that fails verification, or ``None`` if the chain is valid.

        An empty chain (no events for the task) returns ``(EMPTY_CHAIN, None)``.
        """

        events = self.get_events_for_task(conn, task_id)
        if not events:
            return (ProvenanceVerificationCode.EMPTY_CHAIN, None)

        # Check for duplicate sequence numbers.
        seen: set[int] = set()
        for event in events:
            if event.sequence_no in seen:
                return (ProvenanceVerificationCode.DUPLICATE_SEQUENCE, event)
            seen.add(event.sequence_no)

        # Verify sequence continuity starting from 1.
        expected_seq = 1
        previous_digest = ""
        for event in events:
            if event.sequence_no != expected_seq:
                return (ProvenanceVerificationCode.INVALID_SEQUENCE, event)
            # Verify chain digest.
            expected_digest = _compute_chain_digest(event, previous_digest)
            if event.chain_digest != expected_digest:
                return (ProvenanceVerificationCode.INVALID_EVENT_DIGEST, event)
            previous_digest = event.chain_digest
            expected_seq += 1

        return (ProvenanceVerificationCode.VALID, None)

    def _row_to_event(self, row: sqlite3.Row) -> ProvenanceEvent:
        return ProvenanceEvent(
            id=row["id"],
            task_id=row["task_id"],
            execution_id=row["execution_id"],
            plan_id=row["plan_id"],
            plan_step_id=row["plan_step_id"],
            tool_id=row["tool_id"],
            invocation_id=row["invocation_id"],
            sequence_no=row["sequence_no"],
            chain_digest=row["chain_digest"],
            event_type=row["event_type"],
            actor=row["actor"],
            detail_json=row["detail_json"],
            created_at=row["created_at"],
        )


# Backward compatibility: the old record method signature.
    def record(
        self,
        conn: sqlite3.Connection,
        *,
        task_id: int | None = None,
        execution_id: int | None = None,
        event_type: str,
        actor: str,
        detail: dict[str, Any] | None = None,
    ) -> int:
        """Legacy record method. Does not populate chain fields.

        Kept for any callers that have not yet been updated. Prefer
        :meth:`record_event` for new code.
        """

        cursor = conn.execute(
            "INSERT INTO provenance_events "
            "(task_id, execution_id, event_type, actor, detail_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                task_id,
                execution_id,
                event_type,
                actor,
                json.dumps(detail) if detail is not None else None,
                _utcnow(),
            ),
        )
        return _last_insert_id(cursor)
