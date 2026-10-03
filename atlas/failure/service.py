"""Phase 15: failure recording service integrated with provenance.

This is the only component that writes a ``failures`` row, and it does so
atomically with a provenance event so the failure graph is never disconnected
from the evidence.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING, Any

from atlas.failure import FailureRecord, FailureRepo
from atlas.failure.classify import FailureClassifier
from atlas.security.policy import DenyReason, Operation, Resource
from atlas.storage.repositories import ProvenanceRepo

if TYPE_CHECKING:
    from atlas.security.service import AuthorizationService

logger = logging.getLogger(__name__)

MAX_DETAIL_CHARS = 2_000


class FailureService:
    """Records a classified failure and its provenance event in one transaction."""

    def __init__(
        self,
        authorization: "AuthorizationService",
        *,
        classifier: FailureClassifier | None = None,
        provenance: ProvenanceRepo | None = None,
    ) -> None:
        self._auth = authorization
        self._classifier = classifier or FailureClassifier()
        self._provenance = provenance or ProvenanceRepo()
        self._failures = FailureRepo()

    def record_failure(
        self,
        session_token: object,
        *,
        execution_id: int,
        exc: BaseException,
        plan_step_id: int | None = None,
        invocation_id: str | None = None,
        error_code: str | None = None,
    ) -> int:
        """Classify and record a failure, then append a provenance event.

        Returns the failure row id.
        """

        identity = self._auth.authenticate(session_token)
        eid = self._auth._as_id(execution_id, Resource.EXECUTION)

        with self._auth._db.transaction() as conn:
            # Verify ownership of the execution's task.
            exec_row = self._auth._executions.get(conn, eid)
            if exec_row is None:
                self._auth._deny(
                    identity, Resource.EXECUTION, Operation.CREATE, DenyReason.RESOURCE_NOT_OWNED
                )
            task_id = int(exec_row["task_id"])
            self._auth._require_owned_task(
                conn,
                identity,
                task_id,
                resource=Resource.FAILURE,
                operation=Operation.CREATE,
            )

            # Classify the exception.
            classification = self._classifier.classify(
                exc,
                execution_id=eid,
                plan_step_id=plan_step_id,
                invocation_id=invocation_id,
                error_code=error_code,
            )

            # Write the failure row.
            failure_id = self._failures.create(
                conn,
                execution_id=eid,
                category=classification["category"],
                code=classification["code"],
                detail=classification["detail"],
                detail_json=classification["detail_json"],
                plan_step_id=plan_step_id,
                invocation_id=invocation_id,
                error_code=classification["error_code"],
                retryable=classification["retryable"],
            )

            # Append a provenance event for the failure.
            self._provenance.record_event(
                conn,
                task_id=task_id,
                execution_id=eid,
                plan_id=None,
                plan_step_id=plan_step_id,
                tool_id=None,
                invocation_id=invocation_id,
                event_type="failure_recorded",
                actor="failure_classifier",
                detail={
                    "failure_id": failure_id,
                    "category": classification["category"],
                    "code": classification["code"],
                    "retryable": bool(classification["retryable"]),
                },
            )

            logger.info(
                "failure recorded user_id=%s task_id=%s execution_id=%s "
                "category=%s code=%s retryable=%s",
                identity.user_id,
                task_id,
                eid,
                classification["category"],
                classification["code"],
                classification["retryable"],
            )
            return failure_id

    def get_failure(
        self, session_token: object, failure_id: int
    ) -> dict[str, Any] | None:
        """Read one failure by id, enforcing ownership."""

        identity = self._auth.authenticate(session_token)
        fid = self._auth._as_id(failure_id, Resource.FAILURE)

        with self._auth._db.transaction() as conn:
            failure = self._failures.get(conn, fid)
            if failure is None:
                return None
            # Verify ownership via execution -> task.
            exec_row = self._auth._executions.get(conn, failure.execution_id)
            if exec_row is None:
                self._auth._deny(
                    identity, Resource.FAILURE, Operation.READ, DenyReason.RESOURCE_NOT_OWNED
                )
            self._auth._require_owned_task(
                conn,
                identity,
                int(exec_row["task_id"]),
                resource=Resource.FAILURE,
                operation=Operation.READ,
            )
            return self._failure_to_dict(failure)

    def get(
        self, conn: sqlite3.Connection, failure_id: int
    ) -> "FailureRecord" | None:
        """Read a failure by id from a connection, without ownership checks.

        This is for internal use by the recovery service, which already
        performs its own ownership checks.
        """

        return self._failures.get(conn, failure_id)

    def failures_for_task(
        self, session_token: object, task_id: int
    ) -> list[dict[str, Any]]:
        """All failures for a task the caller owns."""

        identity = self._auth.authenticate(session_token)
        tid = self._auth._as_id(task_id, Resource.TASK)

        with self._auth._db.transaction() as conn:
            self._auth._require_owned_task(
                conn,
                identity,
                tid,
                resource=Resource.FAILURE,
                operation=Operation.READ,
            )
            failures = self._failures.for_task(conn, tid)
            return [self._failure_to_dict(f) for f in failures]

    def failures_for_execution(
        self, session_token: object, execution_id: int
    ) -> list[dict[str, Any]]:
        """All failures for an execution the caller owns."""

        identity = self._auth.authenticate(session_token)
        eid = self._auth._as_id(execution_id, Resource.EXECUTION)

        with self._auth._db.transaction() as conn:
            exec_row = self._auth._executions.get(conn, eid)
            if exec_row is None:
                self._auth._deny(
                    identity, Resource.FAILURE, Operation.READ, DenyReason.RESOURCE_NOT_OWNED
                )
            self._auth._require_owned_task(
                conn,
                identity,
                int(exec_row["task_id"]),
                resource=Resource.FAILURE,
                operation=Operation.READ,
            )
            failures = self._failures.for_execution(conn, eid)
            return [self._failure_to_dict(f) for f in failures]

    def latest_failure_for_execution(
        self, session_token: object, execution_id: int
    ) -> dict[str, Any] | None:
        """The most recent failure for an execution, if any."""

        identity = self._auth.authenticate(session_token)
        eid = self._auth._as_id(execution_id, Resource.EXECUTION)

        with self._auth._db.transaction() as conn:
            exec_row = self._auth._executions.get(conn, eid)
            if exec_row is None:
                self._auth._deny(
                    identity, Resource.FAILURE, Operation.READ, DenyReason.RESOURCE_NOT_OWNED
                )
            self._auth._require_owned_task(
                conn,
                identity,
                int(exec_row["task_id"]),
                resource=Resource.FAILURE,
                operation=Operation.READ,
            )
            failure = self._failures.latest_for_execution(conn, eid)
            return self._failure_to_dict(failure) if failure else None

    @staticmethod
    def _failure_to_dict(failure: "FailureRecord") -> dict[str, Any]:
        return {
            "id": failure.id,
            "execution_id": failure.execution_id,
            "category": failure.category,
            "code": failure.code,
            "detail": failure.detail,
            "detail_json": failure.detail_json,
            "plan_step_id": failure.plan_step_id,
            "invocation_id": failure.invocation_id,
            "error_code": failure.error_code,
            "retryable": bool(failure.retryable),
            "created_at": failure.created_at,
        }
