"""Failure classification: maps exceptions to deterministic failure codes.

This is the single point where exceptions become structured failures. Every
path that records a failure must pass through this module, so the taxonomy
cannot drift.

The classifier never raises: an exception it cannot recognize becomes
INTERNAL_ERROR with the exception type and message bounded.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any

from atlas.executor.errors import (
    DuplicateExecution,
    ExecutionBudgetExceeded,
    ExecutionError,
    PlanNotExecutable,
    StepFailed,
)
from atlas.failure import (
    FailureCategory,
    FailureCode,
    category_for_code,
    is_recoverable_code,
)
from atlas.planner.errors import (
    ModelTimeout,
    ModelUnavailable,
    PlanError,
    PlanOutputInvalid,
    PlanRejected,
)
from atlas.sandbox.errors import (
    SandboxError,
    SandboxWorkspaceFailure,
    violation_code,
)
from atlas.security.errors import (
    AuthorizationError,
    InvalidAuthorizationRequest,
    PermissionDenied,
    ResultUnpublishable,
    Unauthenticated,
)
from atlas.tools.errors import (
    MalformedToolId,
    SandboxViolation,
    ToolError,
    ToolErrorCode,
    ToolExecutionFailed,
    ToolInputInvalid,
    ToolInputTooLarge,
    ToolOutputInvalid,
    ToolOutputTooLarge,
    ToolUnsupported,
    UnknownTool,
)
from atlas.verifier.errors import (
    VerificationErrorCode,
    VerificationRefused,
)

logger = logging.getLogger(__name__)

#: Bound on a failure detail string.
MAX_DETAIL_CHARS = 2_000


class FailureClassifier:
    """Classify an exception into a deterministic failure code."""

    def __init__(self) -> None:
        pass

    def classify(
        self,
        exc: BaseException,
        *,
        execution_id: int,
        plan_step_id: int | None = None,
        invocation_id: str | None = None,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        """Map an exception to a failure record dict.

        Returns a dict with keys: category, code, detail, detail_json,
        plan_step_id, invocation_id, error_code, retryable.
        """

        category, code, detail, extra = self._classify_exc(exc, error_code)

        # Build the detail_json for structured evidence.
        detail_json: dict[str, Any] = {
            "exception_type": type(exc).__name__,
            "exception_message": str(exc)[:MAX_DETAIL_CHARS],
        }
        detail_json.update(extra)

        # Truncate detail if needed.
        if len(detail) > MAX_DETAIL_CHARS:
            detail = detail[:MAX_DETAIL_CHARS - 3] + "..."

        return {
            "category": category,
            "code": code,
            "detail": detail,
            "detail_json": detail_json,
            "plan_step_id": plan_step_id,
            "invocation_id": invocation_id,
            "error_code": code,
            "retryable": 1 if is_recoverable_code(code) else 0,
        }

    def _classify_exc(
        self, exc: BaseException, provided_code: str | None
    ) -> tuple[str, str, str, dict[str, Any]]:
        """Core classification logic. Returns (category, code, detail, extra_json)."""

        # Authorization errors — never retried.
        if isinstance(exc, Unauthenticated):
            return (
                FailureCategory.AUTHORIZATION_DENIED.value,
                FailureCode.MISSING_IDENTITY.value,
                "authentication required or session invalid",
                {"reason": getattr(exc, "reason", "missing_identity")},
            )
        if isinstance(exc, InvalidAuthorizationRequest):
            return (
                FailureCategory.AUTHORIZATION_DENIED.value,
                FailureCode.UNKNOWN_RESOURCE.value,
                "authorization request malformed",
                {"reason": getattr(exc, "reason", "malformed_resource_id")},
            )
        if isinstance(exc, PermissionDenied):
            return (
                FailureCategory.AUTHORIZATION_DENIED.value,
                FailureCode.RESOURCE_NOT_OWNED.value,
                "access denied",
                {"reason": getattr(exc, "reason", "resource_not_owned")},
            )
        if isinstance(exc, ResultUnpublishable):
            return (
                FailureCategory.AUTHORIZATION_DENIED.value,
                FailureCode.OPERATION_NOT_PERMITTED.value,
                "result withheld for want of verification evidence",
                {"reason": getattr(exc, "reason", "operation_not_permitted")},
            )
        if isinstance(exc, AuthorizationError):
            # Fallback for any other AuthorizationError subclass.
            return (
                FailureCategory.AUTHORIZATION_DENIED.value,
                FailureCode.OPERATION_NOT_PERMITTED.value,
                "authorization denied",
                {"reason": getattr(exc, "reason", "operation_not_permitted")},
            )

        # Planner errors — non-recoverable except model unavailability.
        if isinstance(exc, ModelUnavailable):
            if isinstance(exc, ModelTimeout):
                return (
                    FailureCategory.PLAN_INVALID.value,
                    FailureCode.MODEL_TIMEOUT.value,
                    "local model timeout",
                    {},
                )
            return (
                FailureCategory.PLAN_INVALID.value,
                FailureCode.MODEL_UNAVAILABLE.value,
                "local model unavailable",
                {},
            )
        if isinstance(exc, PlanOutputInvalid):
            return (
                FailureCategory.PLAN_INVALID.value,
                FailureCode.MODEL_OUTPUT_INVALID.value,
                "model output is not a valid plan document",
                {},
            )
        if isinstance(exc, PlanRejected):
            return (
                FailureCategory.PLAN_INVALID.value,
                FailureCode.PLAN_REJECTED.value,
                "plan rejected by validator",
                {},
            )
        if isinstance(exc, PlanError):
            return (
                FailureCategory.PLAN_INVALID.value,
                FailureCode.PLAN_REJECTED.value,
                "planning failed",
                {},
            )

        # Executor errors.
        if isinstance(exc, PlanNotExecutable):
            return (
                FailureCategory.PLAN_STATE_MISMATCH.value,
                FailureCode.PLAN_NOT_VALIDATED.value,
                "plan is not validated and cannot be executed",
                {},
            )
        if isinstance(exc, DuplicateExecution):
            return (
                FailureCategory.RESOURCE_LIMIT.value,
                FailureCode.CONCURRENT_LIMIT.value,
                "task already has an execution in flight",
                {},
            )
        if isinstance(exc, ExecutionBudgetExceeded):
            return (
                FailureCategory.RESOURCE_LIMIT.value,
                FailureCode.CALL_BUDGET_EXCEEDED.value,
                "execution budget exceeded",
                {},
            )
        if isinstance(exc, StepFailed):
            return (
                FailureCategory.TOOL_EXECUTION_FAILED.value,
                FailureCode.TOOL_RAISED.value,
                f"step {exc.step_key} failed: {exc.error_code}",
                {"step_key": exc.step_key, "tool_error_code": exc.error_code},
            )
        if isinstance(exc, ExecutionError):
            return (
                FailureCategory.TOOL_EXECUTION_FAILED.value,
                FailureCode.TOOL_RAISED.value,
                "execution error",
                {"exec_code": getattr(exc, "code", "unknown")},
            )

        # Verifier refusals.
        if isinstance(exc, VerificationRefused):
            code_map = {
                VerificationErrorCode.TASK_NOT_EXECUTED: FailureCode.RESULT_UNREADABLE,
                VerificationErrorCode.NO_EXECUTION: FailureCode.RESULT_MISSING,
                VerificationErrorCode.EXECUTION_INCOMPLETE: FailureCode.RESULT_MISSING,
                VerificationErrorCode.PLAN_NOT_EXECUTABLE: FailureCode.PLAN_NOT_VALIDATED,
                VerificationErrorCode.RESULT_MISSING: FailureCode.RESULT_MISSING,
                VerificationErrorCode.RESULT_UNREADABLE: FailureCode.RESULT_NOT_JSON,
VerificationErrorCode.STEP_UNREADABLE: FailureCode.MALFORMED_INPUT,
            VerificationErrorCode.ALREADY_VERIFIED: FailureCode.MALFORMED_RESULT,
            VerificationErrorCode.EXECUTION_NOT_RECONCILED: (
                FailureCode.EXECUTION_NOT_RECONCILED
            ),
        }
            code_val = getattr(exc, "code", None)
            if isinstance(code_val, str):
                code = code_map.get(code_val, FailureCode.MALFORMED_RESULT)
            else:
                code = FailureCode.MALFORMED_RESULT
            return (
                FailureCategory.VERIFICATION_FAILED.value,
                code.value,
                str(exc)[:MAX_DETAIL_CHARS],
                {"verification_code": getattr(exc, "code", "unknown")},
            )

        # Tool errors (dispatcher/sandbox layer).
        if isinstance(exc, MalformedToolId):
            return (
                FailureCategory.TOOL_INPUT_INVALID.value,
                FailureCode.INVALID_ARGUMENTS.value,
                "malformed tool id",
                {},
            )
        if isinstance(exc, UnknownTool):
            return (
                FailureCategory.TOOL_INPUT_INVALID.value,
                FailureCode.INVALID_ARGUMENTS.value,
                "unknown tool",
                {},
            )
        if isinstance(exc, ToolInputInvalid):
            return (
                FailureCategory.TOOL_INPUT_INVALID.value,
                FailureCode.INVALID_ARGUMENTS.value,
                "tool input invalid",
                {},
            )
        if isinstance(exc, ToolInputTooLarge):
            return (
                FailureCategory.TOOL_INPUT_INVALID.value,
                FailureCode.INPUT_TOO_LARGE.value,
                "tool input too large",
                {},
            )
        if isinstance(exc, ToolOutputInvalid):
            return (
                FailureCategory.TOOL_OUTPUT_INVALID.value,
                FailureCode.INVALID_OUTPUT.value,
                "tool output invalid",
                {},
            )
        if isinstance(exc, ToolOutputTooLarge):
            return (
                FailureCategory.TOOL_OUTPUT_INVALID.value,
                FailureCode.OUTPUT_TOO_LARGE.value,
                "tool output too large",
                {},
            )
        if isinstance(exc, ToolUnsupported):
            return (
                FailureCategory.TOOL_EXECUTION_FAILED.value,
                FailureCode.TOOL_RAISED.value,
                "tool unsupported",
                {},
            )
        if isinstance(exc, ToolExecutionFailed):
            return (
                FailureCategory.TOOL_EXECUTION_FAILED.value,
                FailureCode.TOOL_RAISED.value,
                "tool execution failed",
                {},
            )
        # Sandbox violations must be checked before generic ToolError
        if isinstance(exc, SandboxViolation):
            # The violation code is embedded in the exception message.
            # Use the violation_code helper if available.
            vcode = violation_code(exc)
            code_map = {
                "network_access": FailureCode.VIOLATION_NETWORK,
                "filesystem_escape": FailureCode.VIOLATION_FS_ESCAPE,
                "host_path_access": FailureCode.VIOLATION_HOST_PATH,
                "project_tree_access": FailureCode.VIOLATION_PROJECT_TREE,
                "secret_access": FailureCode.VIOLATION_SECRET,
                "database_access": FailureCode.VIOLATION_DATABASE,
                "privilege_escalation": FailureCode.VIOLATION_PRIVILEGE,
                "process_limit": FailureCode.VIOLATION_PROCESS_LIMIT,
                "memory_limit": FailureCode.VIOLATION_MEMORY_LIMIT,
                "cpu_limit": FailureCode.VIOLATION_CPU_LIMIT,
                "output_limit": FailureCode.VIOLATION_OUTPUT_LIMIT,
                "artifact_limit": FailureCode.VIOLATION_ARTIFACT_LIMIT,
            }
            code = code_map.get(vcode, FailureCode.VIOLATION_NETWORK)
            return (
                FailureCategory.SANDBOX_VIOLATION.value,
                code.value,
                f"sandbox control violated: {vcode}",
                {"violation": vcode},
            )
        if isinstance(exc, SandboxWorkspaceFailure):
            return (
                FailureCategory.TOOL_EXECUTION_FAILED.value,
                FailureCode.SANDBOX_WORKSPACE_FAILED.value,
                "sandbox workspace failed",
                {},
            )
        if isinstance(exc, SandboxError):
            return (
                FailureCategory.TOOL_EXECUTION_FAILED.value,
                FailureCode.SANDBOX_UNAVAILABLE.value,
                "sandbox error",
                {},
            )
        if isinstance(exc, ToolError):
            # Generic ToolError fallback.
            return (
                FailureCategory.TOOL_EXECUTION_FAILED.value,
                FailureCode.TOOL_RAISED.value,
                "tool error",
                {"tool_code": getattr(exc, "code", ToolErrorCode.EXECUTION_FAILED)},
            )

        # If we have a provided error code (e.g., from sandbox envelope), use it.
        if provided_code:
            category = category_for_code(provided_code)
            return (
                category,
                provided_code,
                f"classified from provided code: {provided_code}",
                {"provided_code": provided_code},
            )

        # Unknown exception — bounded INTERNAL_ERROR.
        logger.warning(
            "unclassified exception type=%s msg=%s",
            type(exc).__name__,
            str(exc)[:200],
        )
        return (
            FailureCategory.INTERNAL_ERROR.value,
            FailureCode.UNEXPECTED_EXCEPTION.value,
            f"unclassified exception: {type(exc).__name__}",
            {
                "exception_type": type(exc).__name__,
                "traceback": "".join(traceback.format_tb(exc.__traceback__))[:MAX_DETAIL_CHARS],
            },
        )


def classify_exception(
    exc: BaseException,
    *,
    execution_id: int,
    plan_step_id: int | None = None,
    invocation_id: str | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    """Convenience function for callers that don't need a classifier instance."""

    return FailureClassifier().classify(
        exc,
        execution_id=execution_id,
        plan_step_id=plan_step_id,
        invocation_id=invocation_id,
        error_code=error_code,
    )
