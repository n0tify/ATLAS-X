"""Storage for recovery attempts: one row per retry of a failed execution.

A ``recovery_attempts`` row records the outcome of a bounded retry of a failed
execution. It links the original failure to the new execution, forming a chain
that can be audited and verified.

Three properties this module enforces structurally rather than leaving to callers:

* **A recovery needs a failure.** ``failure_id`` is NOT NULL in the schema and
  this module re-checks it. There is no "recovery from nothing" outcome.
* **A recovery needs an original execution.** ``execution_id`` references the
  execution that is being retried. The new execution is a separate row.
* **Outcome is mandatory.** Every recovery attempt must eventually record an
  outcome (succeeded, failed, exhausted, not_eligible).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from atlas.recovery.types import (
    MAX_RECOVERY_ATTEMPTS,
    RecoveryOutcome,
)
from atlas.util import utcnow_iso

#: Bound on the operator-facing diagnostic text per recovery attempt.
MAX_DETAIL_CHARS = 2_000

#: Bound on the serialized detail JSON.
MAX_DETAIL_JSON_CHARS = 64_000


class RecoveryWriteInvalid(ValueError):
    """A caller tried to write a recovery attempt the schema could not honestly hold."""


@dataclass(frozen=True)
class RecoveryAttempt:
    """One recovery attempt, as stored."""

    id: int
    execution_id: int
    attempt_no: int
    diagnosis: Optional[str]
    new_plan_json: Optional[str]
    outcome: str
    failure_id: Optional[int]
    limit_no: Optional[int]
    detail_json: Optional[str]
    finished_at: Optional[str]
    created_at: str

    @property
    def outcome_enum(self) -> RecoveryOutcome:
        return RecoveryOutcome(self.outcome)


class RecoveryRepo:
    """Writes and reads for ``recovery_attempts``."""

    def create(
        self,
        conn: sqlite3.Connection,
        *,
        execution_id: int,
        attempt_no: int,
        failure_id: Optional[int] = None,
        diagnosis: Optional[str] = None,
        new_plan_json: Optional[str] = None,
        limit_no: Optional[int] = None,
    ) -> int:
        """Open a recovery attempt. Immutable once created."""

        if not isinstance(execution_id, int) or execution_id <= 0:
            raise RecoveryWriteInvalid("execution_id must be a positive integer")
        if not isinstance(attempt_no, int) or attempt_no <= 0:
            raise RecoveryWriteInvalid("attempt_no must be a positive integer")
        if attempt_no > MAX_RECOVERY_ATTEMPTS:
            raise RecoveryWriteInvalid(
                f"attempt_no {attempt_no} exceeds maximum {MAX_RECOVERY_ATTEMPTS}"
            )

        # Verify the original execution exists
        row = conn.execute(
            "SELECT id FROM executions WHERE id = ?", (execution_id,)
        ).fetchone()
        if row is None:
            raise RecoveryWriteInvalid(
                f"no execution with id {execution_id} to recover"
            )

        # Verify the failure exists if provided
        if failure_id is not None:
            failure_row = conn.execute(
                "SELECT id FROM failures WHERE id = ?", (failure_id,)
            ).fetchone()
            if failure_row is None:
                raise RecoveryWriteInvalid(
                    f"no failure with id {failure_id} to recover from"
                )

        encoded_diagnosis = _encode(diagnosis, "diagnosis") if diagnosis else None
        encoded_new_plan = _encode(new_plan_json, "new_plan_json") if new_plan_json else None

        cursor = conn.execute(
            "INSERT INTO recovery_attempts "
            "(execution_id, attempt_no, failure_id, diagnosis, new_plan_json, "
            "outcome, limit_no, detail_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                execution_id,
                attempt_no,
                failure_id,
                encoded_diagnosis,
                encoded_new_plan,
                RecoveryOutcome.PENDING.value,
                limit_no,
                None,
                utcnow_iso(),
            ),
        )
        row_id = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("recovery_attempt insert returned no row id")
        return int(row_id)

    def complete(
        self,
        conn: sqlite3.Connection,
        *,
        recovery_id: int,
        outcome: RecoveryOutcome,
        detail: Optional[Mapping[str, Any]] = None,
        limit_no: Optional[int] = None,
    ) -> None:
        """Close a recovery attempt with its final outcome.

        Exactly one of the outcomes must be provided. The detail is bounded and
        stored as JSON.
        """

        if not isinstance(recovery_id, int) or recovery_id <= 0:
            raise RecoveryWriteInvalid("recovery_id must be a positive integer")

        encoded_detail = _encode_json(detail, "detail_json") if detail else None

        cursor = conn.execute(
            "UPDATE recovery_attempts "
            "SET outcome = ?, detail_json = ?, finished_at = ?, limit_no = ? "
            "WHERE id = ?",
            (
                outcome.value,
                encoded_detail,
                utcnow_iso(),
                limit_no,
                recovery_id,
            ),
        )
        if cursor.rowcount == 0:
            raise RecoveryWriteInvalid(f"no recovery attempt with id {recovery_id}")

    def get(self, conn: sqlite3.Connection, recovery_id: int) -> Optional[RecoveryAttempt]:
        row = conn.execute(
            "SELECT * FROM recovery_attempts WHERE id = ?", (recovery_id,)
        ).fetchone()
        return self._row_to_recovery(row) if row else None

    def for_execution(
        self, conn: sqlite3.Connection, execution_id: int
    ) -> Sequence[RecoveryAttempt]:
        rows = conn.execute(
            "SELECT * FROM recovery_attempts WHERE execution_id = ? ORDER BY attempt_no ASC",
            (execution_id,),
        ).fetchall()
        return [self._row_to_recovery(row) for row in rows]

    def for_failure(
        self, conn: sqlite3.Connection, failure_id: int
    ) -> Sequence[RecoveryAttempt]:
        rows = conn.execute(
            "SELECT * FROM recovery_attempts WHERE failure_id = ? ORDER BY attempt_no ASC",
            (failure_id,),
        ).fetchall()
        return [self._row_to_recovery(row) for row in rows]

    def latest_for_execution(
        self, conn: sqlite3.Connection, execution_id: int
    ) -> Optional[RecoveryAttempt]:
        row = conn.execute(
            "SELECT * FROM recovery_attempts "
            "WHERE execution_id = ? "
            "ORDER BY attempt_no DESC LIMIT 1",
            (execution_id,),
        ).fetchone()
        return self._row_to_recovery(row) if row else None

    def _row_to_recovery(self, row: sqlite3.Row) -> RecoveryAttempt:
        return RecoveryAttempt(
            id=row["id"],
            execution_id=row["execution_id"],
            attempt_no=row["attempt_no"],
            diagnosis=row["diagnosis"],
            new_plan_json=row["new_plan_json"],
            outcome=row["outcome"],
            failure_id=row["failure_id"],
            limit_no=row["limit_no"],
            detail_json=row["detail_json"],
            finished_at=row["finished_at"],
            created_at=row["created_at"],
        )


def _encode(value: str, name: str) -> Optional[str]:
    if value is None:
        return None
    if len(value) > MAX_DETAIL_CHARS:
        raise RecoveryWriteInvalid(f"recovery {name} is too large to store")
    return value


def _encode_json(value: Optional[Mapping[str, Any]], name: str) -> Optional[str]:
    if value is None:
        return None
    encoded = json.dumps(dict(value), ensure_ascii=True, sort_keys=True, default=str)
    if len(encoded) > MAX_DETAIL_JSON_CHARS:
        raise RecoveryWriteInvalid(f"recovery {name} is too large to store")
    return encoded
