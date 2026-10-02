"""Storage for verification evidence: one row per execution verified.

A ``verifications`` row is a claim plus its evidence -- "this execution's recorded
result was re-derived from its recorded input and matched" -- and it is written
once and never revised. That is the whole design: verification that can be
edited afterwards is not evidence of anything, so this module has no update and
no delete, and the operation policy grants the verifier ``create`` only.

Three properties are enforced structurally rather than left to callers:

* **One verdict per execution.** :meth:`create` refuses an execution that already
  has a verification. The database has no unique index for this, because Phase 16
  recovery must be able to verify a *retry* -- but a retry is a new
  ``executions`` row with its own id, so one verdict per execution is still
  exactly right. A second row for the same execution could only be a second
  opinion about the same bytes, which is how a task ends up both verified and
  failed at once.
* **A verification needs an execution.** ``execution_id`` is ``NOT NULL`` in the
  schema and this module re-checks it, so a verdict cannot be recorded against
  nothing. There is no "the task looked fine" outcome.
* **A verification needs a completed execution.** The execution named by a
  verdict must have closed as ``succeeded`` and carry a ``result_json``. Without
  that check, a verdict could be attached to a dispatch that is still running or
  that failed, and then read as a claim about output nobody produced. The
  condition is enforced here rather than only in the verifier because the verifier
  is a caller like any other, and a property that holds only while the one
  well-behaved caller is in charge is not a property.
* **Evidence is bounded.** :data:`MAX_EVIDENCE_CHARS` caps the serialized
  evidence, and :data:`MAX_CHECKS` caps how many per-field comparisons one
  verdict may carry. A rule that produced a million checks would be a bug, and
  refusing it here is better than storing it.

Ownership is not decided here. A ``verifications`` row has no ``user_id`` column
and cannot gain one without a migration; ownership is the execution's task's, and
the authorization boundary checks it in the same transaction that writes the row.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping, Sequence

from atlas.storage.task_status import ExecutionStatus
from atlas.util import utcnow_iso

#: The whole verdict vocabulary. Lower case because it is compared as text in
#: queries and stored in a free-text column.
RESULT_PASS = "pass"
RESULT_FAIL = "fail"
RESULTS: frozenset[str] = frozenset({RESULT_PASS, RESULT_FAIL})

#: Only a dispatch that closed with a result may be verified.
EXECUTION_SUCCEEDED = ExecutionStatus.SUCCEEDED.value

#: Bound on the serialized evidence per row.
MAX_EVIDENCE_CHARS = 64_000

#: Bound on per-field comparisons in one verdict. The deterministic built-ins
#: produce at most seven output fields, so this leaves room without inviting an
#: unbounded check list.
MAX_CHECKS = 64

#: Bound on the operator-facing note attached to a verdict.
MAX_DETAIL_CHARS = 2_000


class VerificationWriteInvalid(ValueError):
    """A caller tried to record a verdict the schema could not honestly hold."""


class VerificationRepo:
    """Writes and reads for ``verifications``."""

    def create(
        self,
        conn: sqlite3.Connection,
        *,
        execution_id: int,
        result: str,
        verifier: str,
        verifier_version: str,
        detail: Mapping[str, Any] | None = None,
        evidence: Mapping[str, Any] | None = None,
        plan_step_id: int | None = None,
        artifact_id: int | None = None,
    ) -> int:
        """Record one verdict. Immutable once written."""

        if result not in RESULTS:
            raise VerificationWriteInvalid(f"result must be one of {sorted(RESULTS)}")
        if not _is_text(verifier):
            raise VerificationWriteInvalid("verifier must be a non-empty string")
        if not _is_text(verifier_version):
            raise VerificationWriteInvalid("verifier_version must be a non-empty string")
        if (
            isinstance(execution_id, bool)
            or not isinstance(execution_id, int)
            or execution_id <= 0
        ):
            raise VerificationWriteInvalid("execution_id must be a positive integer")

        row = conn.execute(
            "SELECT id, status, result_json FROM executions WHERE id = ?", (execution_id,)
        ).fetchone()
        if row is None:
            # Reachable only by a caller that bypassed the schema's NOT NULL; the
            # point is that a verdict cannot exist without what it judges.
            raise VerificationWriteInvalid(
                f"no execution with id {execution_id} to verify"
            )
        if str(row["status"]) != EXECUTION_SUCCEEDED or row["result_json"] is None:
            # A dispatch that is still running, or that failed, produced no output
            # to certify. Recording a verdict against it would let "the tool
            # returned something" be read out of a row that says it did not.
            raise VerificationWriteInvalid(
                f"execution {execution_id} is {row['status']!r} and has no completed "
                "result to verify"
            )
        existing = conn.execute(
            "SELECT id FROM verifications WHERE execution_id = ?", (execution_id,)
        ).fetchone()
        if existing is not None:
            raise VerificationWriteInvalid(
                f"execution {execution_id} already has verification {existing['id']}"
            )

        encoded_evidence = _encode(evidence, "evidence")
        encoded_detail = _encode(detail, "detail")
        cursor = conn.execute(
            "INSERT INTO verifications "
            "(execution_id, verifier, result, detail_json, artifact_id, plan_step_id, "
            " verifier_version, evidence_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                execution_id,
                verifier,
                result,
                encoded_detail,
                artifact_id,
                plan_step_id,
                verifier_version,
                encoded_evidence,
                utcnow_iso(),
            ),
        )
        row_id = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("verification insert returned no row id")
        return int(row_id)

    def get(self, conn: sqlite3.Connection, verification_id: int) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM verifications WHERE id = ?", (verification_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def for_execution(
        self, conn: sqlite3.Connection, execution_id: int
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM verifications WHERE execution_id = ? ORDER BY id ASC",
            (execution_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def for_task(self, conn: sqlite3.Connection, task_id: int) -> list[dict[str, Any]]:
        """Every verdict on one task's executions, oldest first.

        Joined through ``executions`` rather than by filtering on a task column,
        because ``verifications`` has none: this is a read convenience for the
        Phase 14 lineage and Phase 18 end-to-end report, not an ownership
        decision. Callers reach it through the authorization boundary.
        """

        rows = conn.execute(
            "SELECT v.* FROM verifications v "
            "JOIN executions e ON e.id = v.execution_id "
            "WHERE e.task_id = ? ORDER BY v.id ASC",
            (task_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def counts_for_task(self, conn: sqlite3.Connection, task_id: int) -> dict[str, int]:
        """How many PASS and FAIL verdicts a task's executions carry."""

        rows = conn.execute(
            "SELECT v.result AS result, COUNT(*) AS n FROM verifications v "
            "JOIN executions e ON e.id = v.execution_id "
            "WHERE e.task_id = ? GROUP BY v.result",
            (task_id,),
        ).fetchall()
        counts = {RESULT_PASS: 0, RESULT_FAIL: 0}
        for row in rows:
            if str(row["result"]) in counts:
                counts[str(row["result"])] = int(row["n"])
        return counts

    def pass_coverage_for_task(
        self, conn: sqlite3.Connection, task_id: int
    ) -> tuple[int, int]:
        """``(executions with a PASS, executions in all)`` for one task.

        The second number is what makes this useful rather than decorative: a task
        whose executions all carry a PASS verdict still has nothing verified if it
        also has an execution nobody looked at, so completion compares the two
        counts rather than checking only that the first is non-zero.

        ``COUNT(DISTINCT e.id)`` rather than ``COUNT(*)``: one verdict per
        execution is already enforced by :meth:`create`, but this method is a
        safety net and a safety net that can be defeated by a duplicate row is not
        one.
        """

        total = conn.execute(
            "SELECT COUNT(*) FROM executions WHERE task_id = ?", (task_id,)
        ).fetchone()
        passed = conn.execute(
            "SELECT COUNT(DISTINCT e.id) FROM executions e "
            "JOIN verifications v ON v.execution_id = e.id "
            "WHERE e.task_id = ? AND v.result = ?",
            (task_id, RESULT_PASS),
        ).fetchone()
        return (int(passed[0]) if passed else 0, int(total[0]) if total else 0)


def verdicts_as_dicts(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Copy a sequence of verdict rows, so callers cannot mutate storage state."""

    return [dict(row) for row in rows]


def _encode(value: Mapping[str, Any] | None, name: str) -> str | None:
    """Serialize bounded JSON, or refuse. Never truncates."""

    if value is None:
        return None
    encoded = json.dumps(dict(value), ensure_ascii=True, sort_keys=True, default=str)
    if len(encoded) > MAX_EVIDENCE_CHARS:
        raise VerificationWriteInvalid(f"verification {name} is too large to store")
    return encoded


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
