"""Owner-scoped data access for task-descendant resources.

The rule this module exists to make structural: **there is no way to read a
task-descendant row without naming an owner.** Every statement joins to
``tasks.user_id`` and carries that predicate. A caller that knows only a row id
cannot obtain the row, and a caller that is not the owner receives the same
empty result as a caller asking for a row that does not exist, so the
repository cannot be used as an existence oracle either.

These are data-access helpers, not policy. They express *which rows belong to
whom*; they do not decide whether an operation is permitted. That decision lives
in :mod:`atlas.security.policy` and is enforced once, at
:class:`atlas.security.service.AuthorizationService`.

SQL text is assembled only from the frozen :data:`_OWNED_TABLES` registry below.
No caller-supplied value ever reaches the SQL string; ids are bound parameters.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from atlas.util import utcnow_iso


def _resource_key(resource: object) -> str | None:
    """Return the string key for a resource, or None if it is not one.

    Accepts a plain string or a ``str``-based enum member. This module
    deliberately does not import :mod:`atlas.security`: storage must not depend
    on the policy layer. ``tests/test_authorization.py`` asserts the two
    vocabularies stay identical.
    """

    if isinstance(resource, str):
        value = getattr(resource, "value", None)
        if isinstance(value, str):
            return value
        return resource
    return None



@dataclass(frozen=True)
class OwnedTable:
    """Fixed SQL shape for one owner-scoped resource."""

    table: str
    from_clause: str
    owner_predicate: str
    task_link: str
    parent_link: str | None = None


_OWNED_TABLES: MappingProxyType[str, OwnedTable] = MappingProxyType(
    {
        "plan": OwnedTable(
            table="plans",
            from_clause="plans AS r JOIN tasks AS t ON t.id = r.task_id",
            owner_predicate="t.user_id = ?",
            task_link="r.task_id",
        ),
        "plan_step": OwnedTable(
            table="plan_steps",
            from_clause=(
                "plan_steps AS r JOIN plans AS p ON p.id = r.plan_id "
                "JOIN tasks AS t ON t.id = p.task_id"
            ),
            owner_predicate="t.user_id = ?",
            task_link="p.task_id",
            parent_link="p.id",
        ),
        "execution": OwnedTable(
            table="executions",
            from_clause="executions AS r JOIN tasks AS t ON t.id = r.task_id",
            owner_predicate="t.user_id = ?",
            task_link="r.task_id",
        ),
        "artifact": OwnedTable(
            table="artifacts",
            from_clause=(
                "artifacts AS r JOIN executions AS e ON e.id = r.execution_id "
                "JOIN tasks AS t ON t.id = e.task_id"
            ),
            owner_predicate="t.user_id = ?",
            task_link="e.task_id",
            parent_link="e.id",
        ),
        "verification": OwnedTable(
            table="verifications",
            from_clause=(
                "verifications AS r JOIN executions AS e ON e.id = r.execution_id "
                "JOIN tasks AS t ON t.id = e.task_id"
            ),
            owner_predicate="t.user_id = ?",
            task_link="e.task_id",
            parent_link="e.id",
        ),
        "failure": OwnedTable(
            table="failures",
            from_clause=(
                "failures AS r JOIN executions AS e ON e.id = r.execution_id "
                "JOIN tasks AS t ON t.id = e.task_id"
            ),
            owner_predicate="t.user_id = ?",
            task_link="e.task_id",
            parent_link="e.id",
        ),
        "recovery_attempt": OwnedTable(
            table="recovery_attempts",
            from_clause=(
                "recovery_attempts AS r JOIN executions AS e ON e.id = r.execution_id "
                "JOIN tasks AS t ON t.id = e.task_id"
            ),
            owner_predicate="t.user_id = ?",
            task_link="e.task_id",
            parent_link="e.id",
        ),
        "provenance_event": OwnedTable(
            table="provenance_events",
            from_clause=(
                "provenance_events AS r "
                "LEFT JOIN tasks AS t ON t.id = r.task_id "
                "LEFT JOIN executions AS e ON e.id = r.execution_id "
                "LEFT JOIN tasks AS t2 ON t2.id = e.task_id"
            ),
            owner_predicate="COALESCE(t.user_id, t2.user_id) = ?",
            task_link="COALESCE(r.task_id, e.task_id)",
        ),
    }
)


class UnsupportedOwnedResource(LookupError):
    """Raised for a resource kind that has no owner-scoped table definition."""


def owned_table_for(resource: object) -> OwnedTable:
    """Resolve a resource kind to its SQL shape, or refuse.

    ``Resource.TASK`` is intentionally absent: tasks carry their own
    ``user_id`` column and are served by :class:`~atlas.storage.repositories.TaskRepo`.
    ``Resource.EVALUATION_RUN`` is intentionally absent: the schema gives it no
    owner at all, so there is no predicate to enforce and the decision about its
    ownership is deferred.
    """

    key = _resource_key(resource)
    if key is None or key not in _OWNED_TABLES:
        raise UnsupportedOwnedResource(f"no owner-scoped definition for {resource!r}")
    return _OWNED_TABLES[key]


class OwnedResourceRepo:
    """Owner-scoped reads for every task-descendant resource.

    ``user_id`` is supplied by the authorization boundary, never by a request.
    """

    def __init__(self) -> None:
        self._tables = _OWNED_TABLES

    def owned_table_names(self) -> frozenset[str]:
        return frozenset(spec.table for spec in self._tables.values())

    def get_owned(
        self, conn: sqlite3.Connection, *, resource: object, user_id: int, resource_id: int
    ) -> dict[str, Any] | None:
        """Return the row only if ``user_id`` owns it, else None."""

        spec = owned_table_for(resource)
        row = conn.execute(
            f"SELECT r.* FROM {spec.from_clause} WHERE r.id = ? AND {spec.owner_predicate}",
            (resource_id, user_id),
        ).fetchone()
        return dict(row) if row is not None else None

    def list_owned_for_task(
        self,
        conn: sqlite3.Connection,
        *,
        resource: object,
        user_id: int,
        task_id: int,
        parent_id: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """List owned rows reachable from a task the caller owns.

        ``parent_id`` narrows to the direct parent of the resource (the plan for
        a plan step, the execution for an artifact, verification, failure, or
        recovery attempt). It is optional because every resource below a task is
        owned through the task itself.

        ``limit`` is pushed into the query rather than applied by the caller, so
        a bounded read never materializes the full result set first.
        """

        spec = owned_table_for(resource)
        clauses = [f"{spec.task_link} = ?", spec.owner_predicate]
        params: list[Any] = [task_id, user_id]
        if parent_id is not None:
            if spec.parent_link is None:
                raise UnsupportedOwnedResource(f"{resource!r} has no direct-parent filter")
            clauses.append(f"{spec.parent_link} = ?")
            params.append(parent_id)
        sql = (
            f"SELECT r.* FROM {spec.from_clause} "
            f"WHERE {' AND '.join(clauses)} ORDER BY r.id ASC"
        )
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
                raise ValueError("limit must be a positive integer when provided")
            # Bound by an int parameter, never by formatting a caller value.
            sql += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def count_owned_for_task(
        self,
        conn: sqlite3.Connection,
        *,
        resource: object,
        user_id: int,
        task_id: int,
    ) -> int:
        """Count owned rows of ``resource`` under ``task_id``.

        Counted, not paged: a caller that wants a count must not have to read
        every row to get it, and the owner predicate is applied exactly as in
        :meth:`list_owned_for_task`.
        """

        spec = owned_table_for(resource)
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM {spec.from_clause} "
            f"WHERE {spec.task_link} = ? AND {spec.owner_predicate}",
            (task_id, user_id),
        ).fetchone()
        return int(row["n"]) if row is not None else 0

    def task_id_for(
        self, conn: sqlite3.Connection, *, resource: object, resource_id: int
    ) -> int | None:
        """Resolve which task a resource hangs from, or None if unresolvable.

        Used to derive ownership context for an append instead of trusting a
        caller-supplied task id. Ownership of that task is checked separately.
        """

        spec = owned_table_for(resource)
        row = conn.execute(
            f"SELECT {spec.task_link} AS task_id FROM {spec.from_clause} WHERE r.id = ?",
            (resource_id,),
        ).fetchone()
        if row is None or row["task_id"] is None:
            return None
        task_id = row["task_id"]
        return int(task_id) if isinstance(task_id, int) else None

    def record_provenance(
        self,
        conn: sqlite3.Connection,
        *,
        task_id: int | None = None,
        execution_id: int | None = None,
        event_type: str,
        actor: str,
        detail: dict[str, Any] | None = None,
    ) -> int:
        """Append one event. Callers must have authorized the target first.

        No owner predicate is possible on a write: this is the internal append
        path shared with registration, which legitimately records an event with
        no task. Every task- or execution-scoped append must pass through
        :class:`~atlas.security.service.AuthorizationService`, which verifies
        ownership of the target and derives ``task_id`` itself.
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
                utcnow_iso(),
            ),
        )
        return _last_insert_id(cursor)


def _last_insert_id(cursor: sqlite3.Cursor) -> int:
    row_id = cursor.lastrowid
    if row_id is None:
        raise RuntimeError("insert returned no row id")
    return int(row_id)
