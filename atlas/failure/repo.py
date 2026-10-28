"""Storage for structured failures: one row per classified failure.

A ``failures`` row is the authoritative record that something went wrong, with a
deterministic classification that later phases (recovery, evaluation) can act on.

Three properties this module enforces structurally rather than leaving to callers:

* **A failure needs an execution.** ``execution_id`` is NOT NULL in the schema
  and this module re-checks it. There is no "the run felt wrong" failure.
* **Classification is mandatory.** Every row carries a category and a code from
  the closed vocabularies. A failure that cannot be classified is INTERNAL_ERROR.
* **Detail is bounded.** :data:`MAX_DETAIL_CHARS` caps the diagnostic text. An
  unbounded failure detail would let a single row become a log sink.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping

from atlas.failure.types import (
    FailureCategory,
    FailureCode,
    FailureWriteInvalid,
    is_recoverable,
    task_failure_category,
)
from atlas.util import utcnow_iso

#: Bound on the operator-facing diagnostic text per failure row.
MAX_DETAIL_CHARS = 2_000

#: Bound on the serialized detail JSON.
MAX_DETAIL_JSON_CHARS = 64_000


@dataclass(frozen=True)
class FailureRecord:
    """One classified failure, as stored."""

    id: int
    execution_id: int
    category: str
    code: str
    detail: str | None
    detail_json: str | None
    plan_step_id: int | None
    invocation_id: str | None
    error_code: str | None
    retryable: int
    created_at: str

    @property
    def retryable_bool(self) -> bool:
        return bool(self.retryable)

    @property
    def category_enum(self) -> str:
        return self.category


class FailureRepo:
    """Writes and reads for ``failures``."""

    def create(
        self,
        conn: sqlite3.Connection,
        *,
        execution_id: int,
        category: str,
        code: str,
        detail: str | None = None,
        detail_json: Mapping[str, Any] | None = None,
        plan_step_id: int | None = None,
        invocation_id: str | None = None,
        error_code: str | None = None,
        retryable: int | None = None,
    ) -> int:
        """Record one classified failure. Immutable once written."""

        valid_categories = [c.value for c in FailureCategory]
        valid_codes = [c.value for c in FailureCode]
        if category not in valid_categories:
            raise FailureWriteInvalid(f"category must be one of {valid_categories}")
        if code not in valid_codes:
            raise FailureWriteInvalid(f"code must be one of {valid_codes}")
        if not _is_positive_int(execution_id):
            raise FailureWriteInvalid("execution_id must be a positive integer")

        # Verify the execution exists.
        row = conn.execute(
            "SELECT id FROM executions WHERE id = ?", (execution_id,)
        ).fetchone()
        if row is None:
            raise FailureWriteInvalid(f"no execution with id {execution_id} to record failure for")

        # The `code` parameter is the failure code stored in error_code column.
        # If `error_code` is also provided, it must match `code`.
        if error_code is not None and error_code != code:
            raise FailureWriteInvalid(
                f"error_code {error_code!r} must match code {code!r}"
            )

        # Determine retryability from category if not explicitly provided.
        if retryable is None:
            cat_enum = (
                FailureCategory(category)
                if category in [c.value for c in FailureCategory]
                else None
            )
            retryable = 1 if cat_enum and is_recoverable(cat_enum) else 0

        encoded_detail = _encode(detail, "detail") if detail is not None else None
        encoded_detail_json = (
            _encode_json(detail_json, "detail_json") if detail_json is not None else None
        )

        cursor = conn.execute(
            "INSERT INTO failures "
            "(execution_id, category, error_code, diagnosis, detail_json, plan_step_id, "
            "invocation_id, retryable, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                execution_id,
                category,
                code,  # failure code stored in error_code column
                encoded_detail,  # detail stored in diagnosis column
                encoded_detail_json,
                plan_step_id,
                invocation_id,
                retryable,
                utcnow_iso(),
            ),
        )
        row_id = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("failure insert returned no row id")
        return int(row_id)

    def get(self, conn: sqlite3.Connection, failure_id: int) -> FailureRecord | None:
        row = conn.execute(
            "SELECT * FROM failures WHERE id = ?", (failure_id,)
        ).fetchone()
        return self._row_to_failure(row) if row else None

    def for_execution(
        self, conn: sqlite3.Connection, execution_id: int
    ) -> list[FailureRecord]:
        rows = conn.execute(
            "SELECT * FROM failures WHERE execution_id = ? ORDER BY id ASC",
            (execution_id,),
        ).fetchall()
        return [self._row_to_failure(row) for row in rows]

    def for_task(self, conn: sqlite3.Connection, task_id: int) -> list[FailureRecord]:
        rows = conn.execute(
            "SELECT f.* FROM failures f "
            "JOIN executions e ON e.id = f.execution_id "
            "WHERE e.task_id = ? ORDER BY f.id ASC",
            (task_id,),
        ).fetchall()
        return [self._row_to_failure(row) for row in rows]

    def latest_for_execution(
        self, conn: sqlite3.Connection, execution_id: int
    ) -> FailureRecord | None:
        row = conn.execute(
            "SELECT * FROM failures WHERE execution_id = ? ORDER BY id DESC LIMIT 1",
            (execution_id,),
        ).fetchone()
        return self._row_to_failure(row) if row else None

    def _row_to_failure(self, row: sqlite3.Row) -> FailureRecord:
        # The database has 'error_code' column; 'code' is an alias for it in the record.
        code = row["code"] if "code" in row.keys() else row["error_code"]
        # The database has 'diagnosis' column; 'detail' is an alias for it in the record.
        detail = row["detail"] if "detail" in row.keys() else row["diagnosis"]
        return FailureRecord(
            id=row["id"],
            execution_id=row["execution_id"],
            category=row["category"],
            code=code,
            detail=detail,
            detail_json=row["detail_json"],
            plan_step_id=row["plan_step_id"],
            invocation_id=row["invocation_id"],
            error_code=row["error_code"],
            retryable=row["retryable"],
            created_at=row["created_at"],
        )


def _encode(value: str, name: str) -> str:
    if len(value) > MAX_DETAIL_CHARS:
        raise FailureWriteInvalid(f"failure {name} is too large to store")
    return value


def _encode_json(value: Mapping[str, Any] | None, name: str) -> str | None:
    if value is None:
        return None
    encoded = json.dumps(dict(value), ensure_ascii=True, sort_keys=True, default=str)
    if len(encoded) > MAX_DETAIL_JSON_CHARS:
        raise FailureWriteInvalid(f"failure {name} is too large to store")
    return encoded


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def derive_task_failure_category(
    conn: sqlite3.Connection, task_id: int
) -> tuple[str, int]:
    """Derive the task's failure category from its recorded failures.

    Returns a tuple of (category, failure_count).

    Uses :func:`atlas.failure.types.task_failure_category` for the priority logic.
    """

    repo = FailureRepo()
    failures = repo.for_task(conn, task_id)
    if not failures:
        return "internal_error", 0

    categories = [f.category for f in failures]
    category = task_failure_category(categories)
    return category, len(failures)


def derive_task_failure_categories(
    conn: sqlite3.Connection, task_id: int
) -> list[dict[str, Any]]:
    """Get all failure records for a task, for recovery eligibility checks.

    Returns a list of dicts with category and code for each failure.
    """

    repo = FailureRepo()
    failures = repo.for_task(conn, task_id)
    return [
        {"category": f.category, "code": f.code, "id": f.id}
        for f in failures
    ]
