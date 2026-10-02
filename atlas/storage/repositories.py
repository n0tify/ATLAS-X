"""Parameterized repository layer over SQLite.

Every statement uses placeholders. Ownership is enforced in the SQL itself
(``WHERE id = ? AND user_id = ?``) so a caller can never read or touch another
user's rows through these helpers.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

USER_PUBLIC_FIELDS = ("id", "username", "created_at")


def _user_public(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in USER_PUBLIC_FIELDS}


def _last_insert_id(cursor: sqlite3.Cursor) -> int:
    row_id = cursor.lastrowid
    if row_id is None:
        raise RuntimeError("insert returned no row id")
    return int(row_id)


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


def _utcnow() -> str:
    from atlas.util import utcnow_iso

    return utcnow_iso()
