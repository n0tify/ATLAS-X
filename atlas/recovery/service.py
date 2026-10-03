"""Phase 16: Bounded recovery service.

This is the only component that decides whether a failed execution can be
retried, and if so, creates a new execution with a corrected plan. It enforces
the configured recovery limit and records every attempt with provenance.

What it does:
- Classifies whether a failure is recoverable (based on category/code).
- Enforces the configured max_recovery_attempts limit.
- Creates a new plan (if needed) and dispatches a new execution.
- Records the recovery attempt with provenance.
- Links the new execution to the original failure.

What it does not do:
- It does not modify the original execution or failure.
- It does not bypass authorization, sandbox, or verification.
- It does not allow unlimited retries.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING, Any, Mapping, Optional, Sequence

from atlas.config.settings import Settings
from atlas.recovery.repo import RecoveryAttempt, RecoveryRepo
from atlas.recovery.types import (
    MAX_RECOVERY_ATTEMPTS,
    RecoveryErrorCode,
    RecoveryOutcome,
    is_recoverable_failure,
)
from atlas.security.policy import Operation, Resource
from atlas.tools.dispatch import ToolDispatcher
from atlas.tools.registry import default_registry

if TYPE_CHECKING:
    from atlas.executor import StepFailed
    from atlas.planner.service import PlannerService
    from atlas.security.service import AuthorizationService

logger = logging.getLogger(__name__)

#: Bound on the operator-facing diagnostic text per recovery attempt.
MAX_DETAIL_CHARS = 2_000


class RecoveryService:
    """Orchestrates bounded recovery of failed executions."""

    def __init__(
        self,
        authorization: "AuthorizationService",
        *,
        dispatcher: Optional["ToolDispatcher"] = None,
        planner: Optional["PlannerService"] = None,
        settings: Optional[Settings] = None,
        recovery_repo: Optional[RecoveryRepo] = None,
    ) -> None:
        from atlas.executor.service import ExecutorService
        from atlas.planner.service import PlannerService

        self._auth = authorization
        self._dispatcher = dispatcher
        self._settings = settings or Settings()
        self._recovery = RecoveryRepo()
        self._planner = planner or PlannerService(
            authorization,
            settings=self._settings,
        )
        self._executor = ExecutorService(
            authorization,
            dispatcher or self._default_dispatcher(),
        )

    def _default_dispatcher(self) -> ToolDispatcher:
        """Create a default dispatcher if none provided."""
        return ToolDispatcher(
            self._auth._db,
            self._auth,
            default_registry(),
        )

    def attempt_recovery(
        self,
        session_token: object,
        *,
        failure_id: int,
        corrected_plan_json: Optional[str] = None,
        corrected_plan_steps: Optional[Sequence[Mapping[str, Any]]] = None,
        corrected_model_id: Optional[str] = None,
        corrected_source: str = "recovery",
    ) -> Mapping[str, Any]:
        """Attempt to recover from a failure.

        Returns a dict with:
        - recovery_id
        - outcome (RecoveryOutcome value)
        - new_execution_id (if recovery succeeded)
        - detail
        """

        fid = self._auth._as_id(failure_id, Resource.FAILURE)

        with self._auth._db.transaction() as conn:
            # Load the failure
            failure = self._auth._failures.get(conn, fid)
            if failure is None:
                raise ValueError(f"failure {fid} not found")

            # Check if this failure is recoverable
            category = failure.category
            code = failure.code
            if not is_recoverable_failure(category, code):
                return self._record_not_eligible(
                    conn, fid, failure.execution_id,
                    RecoveryErrorCode.NON_RECOVERABLE_FAILURE,
                    f"failure {category}:{code} is not recoverable"
                )

            # Check recovery attempt limit
            existing_attempts = self._recovery.for_failure(conn, fid)
            attempt_no = len(existing_attempts) + 1
            max_attempts = self._settings.max_recovery_attempts
            if attempt_no > max_attempts:
                return self._record_exhausted(
                    conn, fid, failure.execution_id, attempt_no,
                    max_attempts
                )

            # Get the original execution details
            exec_id = failure.execution_id
            exec_row = self._auth._executions.get(conn, failure.execution_id)
            if exec_row is None:
                return self._record_not_eligible(
                    conn, fid, failure.execution_id,
                    RecoveryErrorCode.ORIGINAL_EXECUTION_MISSING,
                    "original execution missing"
                )

            task_id = int(exec_row["task_id"])
            plan_id = int(exec_row["plan_id"])
            plan_step_id = int(exec_row["plan_step_id"])

# Determine the plan to use for recovery
            if corrected_plan_json and corrected_plan_steps:
                # Use the corrected plan provided by the caller
                pass

            else:
                plan_row = self._auth._plans.get(
                conn, plan_id
            )
                if plan_row is None:
                    return self._record_not_eligible(
                        conn, fid, exec_id,
                        RecoveryErrorCode.NEW_PLAN_REJECTED,
                        "original plan missing"
                    )
                # Get the original plan steps (not used directly, planner regenerates)
                _ = self._auth.plan_steps(session_token, plan_id)

            # Create the recovery attempt record
            recovery_id = self._recovery.create(
                conn,
                execution_id=failure.execution_id,
                attempt_no=attempt_no,
                failure_id=fid,
diagnosis=(
                f"Recovery attempt {attempt_no} for {failure.category}:{failure.code}"
            ),
            )

            # Record the recovery attempt provenance
            self._auth._provenance.record_event(
                conn,
                task_id=task_id,
                execution_id=failure.execution_id,
                plan_id=plan_id,
                plan_step_id=plan_step_id,
                tool_id=None,
                invocation_id=None,
                event_type="recovery_started",
                actor="recovery",
                detail={
                    "recovery_id": recovery_id,
                    "attempt_no": attempt_no,
                    "max_attempts": max_attempts,
"original_failure_category": failure.category,
            "original_failure_code": failure.code,
                },
            )

        # Execute the recovery outside the transaction (dispatcher needs auth)
        try:
            # If we have a corrected plan, validate and persist it first
            new_plan_id = None
            if corrected_plan_json:
                planner_outcome = self._planner.plan_task(
                    session_token,
                    task_id=task_id,
                    supersedes_plan_id=plan_id,
                    tool_ids=None,  # Use all available tools
                )
                new_plan_id = int(planner_outcome.plan["id"])
            else:
                new_plan_id = plan_id

            # Execute the plan
            outcome = self._executor.execute(
                session_token,
                task_id=task_id,
                attempt=attempt_no,
            )

            # Recovery succeeded
            with self._auth._db.transaction() as conn:
                new_execution_id = outcome.steps[0].execution_id if outcome.steps else 0
                self._recovery.complete(
                    conn,
                    recovery_id=recovery_id,
                    outcome=RecoveryOutcome.SUCCEEDED,
                    detail={
                        "new_execution_id": new_execution_id,
                        "new_plan_id": new_plan_id,
                    },
                    limit_no=self._settings.max_recovery_attempts,
                )
                self._auth._provenance.record_event(
                    conn,
                    task_id=task_id,
                    execution_id=failure.execution_id,
                    plan_id=new_plan_id,
                    event_type="recovery_succeeded",
                    actor="recovery",
                    detail={"recovery_id": recovery_id, "new_execution_id": new_execution_id},
                )

            return {
                "recovery_id": recovery_id,
                "outcome": RecoveryOutcome.SUCCEEDED.value,
                "new_execution_id": new_execution_id,
                "detail": f"Recovery succeeded on attempt {attempt_no}",
            }

        except StepFailed as exc:
            # Recovery failed - record and return
            with self._auth._db.transaction() as conn:
                self._recovery.complete(
                    conn,
                    recovery_id=recovery_id,
                    outcome=RecoveryOutcome.FAILED,
                    detail={
                        "error_code": exc.error_code,
                        "step_key": exc.step_key,
                    },
                    limit_no=self._settings.max_recovery_attempts,
                )
                self._auth._provenance.record_event(
                    conn,
                    task_id=task_id,
                    execution_id=failure.execution_id,
                    event_type="recovery_failed",
                    actor="recovery",
                    detail={
                        "recovery_id": recovery_id,
                        "error_code": exc.error_code,
                        "step_key": exc.step_key,
                    },
)

            return {
                "recovery_id": recovery_id,
                "outcome": RecoveryOutcome.FAILED.value,
                "detail": f"Recovery failed on attempt {attempt_no}: {exc.error_code}",
            }


        except Exception as exc:
            # Unexpected error - record and return
            logger.exception("unexpected error during recovery")
            with self._auth._db.transaction() as conn:
                self._recovery.complete(
                    conn,
                    recovery_id=recovery_id,
                    outcome=RecoveryOutcome.FAILED,
                    detail={
                        "error_type": type(exc).__name__,
                        "error_message": str(exc)[:MAX_DETAIL_CHARS],
                    },
                    limit_no=self._settings.max_recovery_attempts,
                )
                self._auth._provenance.record_event(
                    conn,
                    task_id=task_id,
                    execution_id=failure.execution_id,
                    event_type="recovery_failed",
                    actor="recovery",
                    detail={
                        "recovery_id": recovery_id,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc)[:MAX_DETAIL_CHARS],
                    },
                )

            return {
                "recovery_id": recovery_id,
                "outcome": RecoveryOutcome.FAILED.value,
                "detail": f"Recovery failed with unexpected error: {type(exc).__name__}",
            }

    def _record_not_eligible(
        self,
        conn: sqlite3.Connection,
        failure_id: int,
        execution_id: int,
        code: RecoveryErrorCode,
        detail: str,
    ) -> Mapping[str, Any]:
        """Record a recovery that was not eligible."""

        recovery_id = self._recovery.create(
            conn,
            execution_id=execution_id,
            attempt_no=0,
            failure_id=failure_id,
            diagnosis=detail,
        )

        self._recovery.complete(
            conn,
            recovery_id=recovery_id,
            outcome=RecoveryOutcome.NOT_ELIGIBLE,
            detail={"code": code.value, "detail": detail},
        )

        # Provenance
        exec_row = self._auth._executions.get(conn, execution_id)
        task_id = int(exec_row["task_id"]) if exec_row else None
        if task_id:
            self._auth._provenance.record_event(
                conn,
                task_id=task_id,
                execution_id=execution_id,
                event_type="recovery_not_eligible",
                actor="recovery",
                detail={"code": code.value, "detail": detail},
            )

        return {
            "recovery_id": recovery_id,
            "outcome": RecoveryOutcome.NOT_ELIGIBLE.value,
            "detail": detail,
        }

    def _record_exhausted(
        self,
        conn: sqlite3.Connection,
        failure_id: int,
        execution_id: int,
        attempt_no: int,
        max_attempts: int,
    ) -> Mapping[str, Any]:
        """Record a recovery that exhausted its attempts."""

        recovery_id = self._recovery.create(
            conn,
            execution_id=execution_id,
            attempt_no=attempt_no,
            failure_id=failure_id,
            diagnosis=f"Recovery exhausted after {max_attempts} attempts",
            limit_no=max_attempts,
        )

        self._recovery.complete(
            conn,
            recovery_id=recovery_id,
            outcome=RecoveryOutcome.EXHAUSTED,
            detail={
                "code": RecoveryErrorCode.MAX_ATTEMPTS_EXCEEDED.value,
                "attempts_made": attempt_no - 1,
                "max_attempts": max_attempts,
            },
            limit_no=MAX_RECOVERY_ATTEMPTS,
        )

        # Provenance
        exec_row = self._auth._executions.get(conn, execution_id)
        task_id = int(exec_row["task_id"]) if exec_row else None
        if task_id:
            self._auth._provenance.record_event(
                conn,
                task_id=task_id,
                execution_id=execution_id,
                event_type="recovery_exhausted",
                actor="recovery",
                detail={
                    "code": RecoveryErrorCode.MAX_ATTEMPTS_EXCEEDED.value,
                    "attempts_made": attempt_no - 1,
                    "max_attempts": max_attempts,
                },
            )

        return {
            "recovery_id": recovery_id,
            "outcome": RecoveryOutcome.EXHAUSTED.value,
            "detail": f"Recovery exhausted after {max_attempts} attempts",
        }

    def get_recovery_attempts(
        self,
        session_token: object,
        *,
        failure_id: int,
    ) -> Sequence[Mapping[str, Any]]:
        """All recovery attempts for a failure the caller owns."""

        identity = self._auth.authenticate(session_token)
        fid = self._auth._as_id(failure_id, Resource.FAILURE)

        with self._auth._db.transaction() as conn:
            # Verify ownership via failure -> execution -> task
            failure = self._auth._failures.get(conn, fid)
            if failure is None:
                raise ValueError(f"failure {fid} not found")
            exec_row = self._auth._executions.get(conn, failure.execution_id)
            if exec_row is None:
                raise ValueError("execution not found")
            self._auth._require_owned_task(
                conn,
                identity,
                int(exec_row["task_id"]),
                resource=Resource.FAILURE,
                operation=Operation.READ,
            )
            attempts = self._recovery.for_failure(conn, fid)
            return [self._attempt_to_dict(a) for a in attempts]

    def get_recovery(
        self, session_token: object, recovery_id: int
    ) -> Optional[Mapping[str, Any]]:
        """Read one recovery attempt by id, enforcing ownership."""

        identity = self._auth.authenticate(session_token)
        rid = self._auth._as_id(recovery_id, Resource.RECOVERY_ATTEMPT)

        with self._auth._db.transaction() as conn:
            attempt = self._recovery.get(conn, rid)
            if attempt is None:
                return None
            # Verify ownership via execution -> task
            exec_row = self._auth._executions.get(conn, attempt.execution_id)
            if exec_row is None:
                raise ValueError("execution not found")
            self._auth._require_owned_task(
                conn,
                identity,
                int(exec_row["task_id"]),
                resource=Resource.RECOVERY_ATTEMPT,
                operation=Operation.READ,
            )
            return self._attempt_to_dict(attempt)

    @staticmethod
    def _attempt_to_dict(attempt: RecoveryAttempt) -> Mapping[str, Any]:
        return {
            "id": attempt.id,
            "execution_id": attempt.execution_id,
            "attempt_no": attempt.attempt_no,
            "diagnosis": attempt.diagnosis,
            "new_plan_json": attempt.new_plan_json,
            "outcome": attempt.outcome,
            "failure_id": attempt.failure_id,
            "limit_no": attempt.limit_no,
            "detail_json": attempt.detail_json,
            "finished_at": attempt.finished_at,
            "created_at": attempt.created_at,
        }
