"""Storage for executions: one row per step dispatch.

An ``executions`` row is a *dispatch attempt*, not a plan and not a task. That is
what makes ``plan_step_id`` and ``invocation_id`` meaningful: the row says which
step ran, which tool ran it, and which correlation id the provenance graph is
keyed on.

Three properties this module enforces structurally rather than asking callers to
remember:

* **One execution per invocation.** ``invocation_id`` carries a partial unique
  index, and this module refuses a second row for an id that already has one. The
  refusal is here as well as in the schema so the caller gets an execution error
  rather than an ``IntegrityError`` from somewhere deeper.
* **A result is written only where one exists.** :meth:`complete` requires a
  ``result_json``; :meth:`fail` requires an ``error_code``. A row cannot be closed
  with neither, which is what stops "succeeded with nothing produced" from being
  representable.
* **Ownership is not decided here.** No ``user_id`` is accepted, because no
  execution column holds one: ownership is derived through ``tasks.user_id`` by
  :class:`~atlas.storage.owned_resources.OwnedResourceRepo`, and that the caller
  owns the task is checked by the authorization boundary that wraps these calls in
  the same transaction.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping, Sequence

from atlas.storage.task_status import ExecutionStatus
from atlas.util import utcnow_iso

#: ``plans.status`` values an execution may be started against. Phase 11 writes
#: ``validated`` or ``rejected``; Phase 16 marks a plan ``consumed`` once an
#: execution has taken it. Only ``validated`` may run.
EXECUTABLE_PLAN_STATUS = "validated"

#: Where a dispatch came from. Phase 12 writes ``plan_step`` for a planned step.
#: ``recovery`` is Phase 16 re-running a step through the same boundary.
ORIGIN_PLAN_STEP = "plan_step"
ORIGIN_RECOVERY = "recovery"
ORIGINS: frozenset[str] = frozenset({"direct", ORIGIN_PLAN_STEP, ORIGIN_RECOVERY})

MAX_RESULT_CHARS = 1_000_000
MAX_ERROR_CHARS = 2_000

#: Bound on the serialized result written per execution. Generous relative to the
#: dispatcher's own output ceiling because this is the stored copy, but still
#: bounded: a run of twelve steps must not be able to write an unbounded amount
#: into one row.
RESULT_CEILING = 4 * 1024 * 1024


class ExecutionWriteInvalid(ValueError):
    """A caller tried to write an execution the schema could not honestly hold."""


class ExecutionRepo:
    """Writes and reads for ``executions``."""

    def create(
        self,
        conn: sqlite3.Connection,
        *,
        task_id: int,
        plan_id: int | None,
        plan_step_id: int | None,
        tool_id: str | None,
        invocation_id: str | None,
        origin: str,
        attempt: int = 1,
    ) -> int:
        """Open one execution row. ``status`` starts at ``running``.

        ``created_at`` is written rather than left NULL: this build creates every
        row it owns, and the column is nullable only so that a database upgraded
        from v2 can hold legacy rows that genuinely had no creation timestamp.

        ``attempt`` is a parameter rather than a constant because it is the number
        recovery reuses to tell a second dispatch of the same step from a retry.
        Writing a hardcoded 1 would have made the column disagree with the
        ``invocation_id`` that recovery keys on, which is the one column recovery
        actually trusts.
        """

        if origin not in ORIGINS:
            raise ExecutionWriteInvalid(f"origin must be one of {sorted(ORIGINS)}")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            raise ExecutionWriteInvalid("attempt must be a positive integer")
        if invocation_id is not None:
            if not isinstance(invocation_id, str) or not invocation_id.strip():
                raise ExecutionWriteInvalid("invocation_id must be a non-empty string or None")
            if len(invocation_id) > 128:
                raise ExecutionWriteInvalid("invocation_id is longer than 128 characters")
            existing = conn.execute(
                "SELECT 1 FROM executions WHERE invocation_id = ?", (invocation_id,)
            ).fetchone()
            if existing is not None:
                raise ExecutionWriteInvalid(
                    f"invocation_id {invocation_id!r} already has an execution"
                )
        if tool_id is not None and (not isinstance(tool_id, str) or not tool_id):
            raise ExecutionWriteInvalid("tool_id must be a non-empty string or None")

        now = utcnow_iso()
        cursor = conn.execute(
            "INSERT INTO executions "
            "(task_id, attempt, status, plan_id, plan_step_id, tool_id, invocation_id, "
            " origin, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                attempt,
                ExecutionStatus.RUNNING.value,
                plan_id,
                plan_step_id,
                tool_id,
                invocation_id,
                origin,
                now,
            ),
        )
        row_id = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("execution insert returned no row id")
        return int(row_id)

    def complete(
        self, conn: sqlite3.Connection, *, execution_id: int, result: Mapping[str, Any]
    ) -> None:
        """Close an execution as succeeded, with the result it produced."""

        encoded = json.dumps(dict(result), ensure_ascii=True, sort_keys=True, default=str)
        if len(encoded) > min(MAX_RESULT_CHARS, RESULT_CEILING):
            raise ExecutionWriteInvalid("execution result is too large to store")
        _close(conn, execution_id=execution_id, status=ExecutionStatus.SUCCEEDED)
        conn.execute(
            "UPDATE executions SET result_json = ?, finished_at = ? WHERE id = ?",
            (encoded, utcnow_iso(), execution_id),
        )

    def fail(
        self,
        conn: sqlite3.Connection,
        *,
        execution_id: int,
        error_code: str,
        error: str | None = None,
    ) -> None:
        """Close an execution as failed, with a stable code and an operator note."""

        if not isinstance(error_code, str) or not error_code.strip():
            raise ExecutionWriteInvalid("a failed execution requires a stable error_code")
        note = (error or "")[:MAX_ERROR_CHARS]
        _close(conn, execution_id=execution_id, status=ExecutionStatus.FAILED)
        conn.execute(
            "UPDATE executions SET error_code = ?, error = ?, finished_at = ? WHERE id = ?",
            (error_code, note or None, utcnow_iso(), execution_id),
        )

    def get(self, conn: sqlite3.Connection, execution_id: int) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM executions WHERE id = ?", (execution_id,)).fetchone()
        return dict(row) if row is not None else None

    def for_task(self, conn: sqlite3.Connection, task_id: int) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM executions WHERE task_id = ? ORDER BY id ASC", (task_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def in_flight_for_task(
        self, conn: sqlite3.Connection, *, task_id: int, limit: int
    ) -> list[dict[str, Any]]:
        """Executions of ``task_id`` that are still ``running``.

        Counted from storage rather than from a process-local flag so that a second
        ATLAS-X process pointed at the same database sees the same in-flight rows,
        which is the only way ``max_concurrent_executions`` means anything.
        """

        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        rows = conn.execute(
            "SELECT id, plan_id, created_at FROM executions "
            "WHERE task_id = ? AND status = ? ORDER BY id ASC LIMIT ?",
            (task_id, ExecutionStatus.RUNNING.value, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def mark_plan_step(
        self,
        conn: sqlite3.Connection,
        *,
        plan_step_id: int,
        status: str,
        failure_category: str | None = None,
    ) -> None:
        """Record a step's outcome so a re-read of the plan shows what happened."""

        if status not in {"pending", "running", "succeeded", "failed"}:
            raise ExecutionWriteInvalid(f"plan step status {status!r} is not a known status")
        conn.execute(
            "UPDATE plan_steps SET status = ?, failure_category = ?, updated_at = ? WHERE id = ?",
            (status, failure_category, utcnow_iso(), plan_step_id),
        )


def _close(conn: sqlite3.Connection, *, execution_id: int, status: ExecutionStatus) -> None:
    """Move a running execution to a terminal status, or refuse.

    Closing an already-closed execution is refused rather than ignored. A second
    write would mean two conclusions about one dispatch, and which of them the
    audit trail keeps would depend on arrival order.
    """

    row = conn.execute(
        "SELECT status FROM executions WHERE id = ?", (execution_id,)
    ).fetchone()
    if row is None:
        raise ExecutionWriteInvalid(f"no execution with id {execution_id}")
    current = str(row["status"])
    if current != ExecutionStatus.RUNNING.value:
        raise ExecutionWriteInvalid(
            f"execution {execution_id} is already {current!r} and cannot be closed again"
        )
    conn.execute(
        "UPDATE executions SET status = ? WHERE id = ?", (status.value, execution_id)
    )


def step_rows_as_dicts(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Copy a sequence of step rows, so callers cannot mutate storage state."""

    return [dict(row) for row in rows]
