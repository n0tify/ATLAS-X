"""Phase 16: Bounded recovery types and constants.

This module contains only the core type definitions and has no dependencies
on other recovery modules, making it safe to import from anywhere in the
recovery package without circular imports.
"""

from __future__ import annotations

from enum import Enum


class RecoveryOutcome(str, Enum):
    """Outcome of a recovery attempt."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXHAUSTED = "exhausted"
    NOT_ELIGIBLE = "not_eligible"


class RecoveryErrorCode(str, Enum):
    """Stable codes for why a recovery was not attempted or failed."""

    NON_RECOVERABLE_FAILURE = "non_recoverable_failure"
    MAX_ATTEMPTS_EXCEEDED = "max_attempts_exceeded"
    NO_FAILURE_TO_RECOVER = "no_failure_to_recover"
    ORIGINAL_EXECUTION_MISSING = "original_execution_missing"
    NEW_PLAN_REJECTED = "new_plan_rejected"
    DISPATCH_FAILED = "dispatch_failed"
    VERIFICATION_FAILED = "verification_failed"
    INTERNAL_ERROR = "internal_error"


#: Maximum recovery attempts (must match Settings.max_recovery_attempts bounds).
MAX_RECOVERY_ATTEMPTS = 10


def is_recoverable_failure(category: str, code: str) -> bool:
    """Determine if a failure is eligible for recovery based on its category and code.

    Only failures with these categories/codes are eligible for automatic recovery:
    - TOOL_EXECUTION_FAILED (all codes)
    - RESOURCE_LIMIT (all codes)
    - TOOL_INPUT_INVALID (all codes)
    """

    from atlas.failure.types import FailureCategory, FailureCode

    recoverable_categories = {
        FailureCategory.TOOL_EXECUTION_FAILED.value,
        FailureCategory.RESOURCE_LIMIT.value,
        FailureCategory.TOOL_INPUT_INVALID.value,
    }

    # Quick category check first
    if category in recoverable_categories:
        return True

    # Specific codes that are recoverable even if category isn't broadly recoverable
    recoverable_codes = {
        FailureCode.TOOL_RAISED.value,
        FailureCode.SANDBOX_UNAVAILABLE.value,
        FailureCode.SANDBOX_TIMEOUT.value,
        FailureCode.SANDBOX_WORKSPACE_FAILED.value,
        FailureCode.INVALID_ARGUMENTS.value,
        FailureCode.INPUT_TOO_LARGE.value,
        FailureCode.CALL_BUDGET_EXCEEDED.value,
        FailureCode.WALL_CLOCK_EXCEEDED.value,
        FailureCode.CONCURRENT_LIMIT.value,
    }

    return code in recoverable_codes


__all__ = [
    "RecoveryOutcome",
    "RecoveryErrorCode",
    "MAX_RECOVERY_ATTEMPTS",
    "is_recoverable_failure",
]
