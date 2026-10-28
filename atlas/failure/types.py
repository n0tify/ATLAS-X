"""Core failure types: enums, constants, and type definitions.

This module contains only the core type definitions and has no dependencies
on other failure modules, making it safe to import from anywhere in the
failure package without circular imports.
"""

from __future__ import annotations

from enum import Enum
from types import MappingProxyType


class FailureCategory(str, Enum):
    """The stable vocabulary of failure categories.

    These are the ONLY categories. Do not add dynamic categories.
    Each maps to a deterministic retryability decision.
    """

    # Authorization and security
    AUTHORIZATION_DENIED = "authorization_denied"
    SECURITY_BLOCKED = "security_blocked"

    # Planning
    PLAN_INVALID = "plan_invalid"
    PLAN_STATE_MISMATCH = "plan_state_mismatch"
    DEPENDENCY_INVALID = "dependency_invalid"

    # Tool execution
    TOOL_INPUT_INVALID = "tool_input_invalid"
    TOOL_EXECUTION_FAILED = "tool_execution_failed"
    TOOL_OUTPUT_INVALID = "tool_output_invalid"

    # Sandbox
    SANDBOX_VIOLATION = "sandbox_violation"
    RESOURCE_LIMIT = "resource_limit"

    # Verification
    RESULT_UNREADABLE = "result_unreadable"
    VERIFICATION_FAILED = "verification_failed"

    # Artifacts
    ARTIFACT_FAILED = "artifact_failed"

    # Recovery
    RECOVERY_EXHAUSTED = "recovery_exhausted"

    # Fallback
    INTERNAL_ERROR = "internal_error"


#: Failure categories that are potentially recoverable through a bounded retry
#: or correction. All others are NON-RECOVERABLE and must not be retried.
RECOVERABLE_CATEGORIES: frozenset[FailureCategory] = frozenset({
    FailureCategory.TOOL_EXECUTION_FAILED,
    FailureCategory.RESOURCE_LIMIT,
    FailureCategory.TOOL_INPUT_INVALID,
})

#: Failure categories that are NEVER recoverable. The presence of one means
#: the task is permanently stopped for this run; recovery must not be attempted.
NON_RECOVERABLE_CATEGORIES: frozenset[FailureCategory] = frozenset({
    FailureCategory.AUTHORIZATION_DENIED,
    FailureCategory.SECURITY_BLOCKED,
    FailureCategory.PLAN_INVALID,
    FailureCategory.PLAN_STATE_MISMATCH,
    FailureCategory.DEPENDENCY_INVALID,
    FailureCategory.TOOL_OUTPUT_INVALID,
    FailureCategory.SANDBOX_VIOLATION,
    FailureCategory.RESULT_UNREADABLE,
    FailureCategory.VERIFICATION_FAILED,
    FailureCategory.ARTIFACT_FAILED,
    FailureCategory.RECOVERY_EXHAUSTED,
    FailureCategory.INTERNAL_ERROR,
})

#: All categories, as a sanity check.
ALL_CATEGORIES: frozenset[FailureCategory] = (
    RECOVERABLE_CATEGORIES | NON_RECOVERABLE_CATEGORIES
)

assert RECOVERABLE_CATEGORIES.isdisjoint(NON_RECOVERABLE_CATEGORIES)
assert len(ALL_CATEGORIES) == len(FailureCategory)


class FailureCode(str, Enum):
    """Stable programmatic codes for failures.

    Each category may have multiple codes. The code is the machine-readable
    classification; the category is the retryability group.
    """

    # AUTHORIZATION_DENIED
    MISSING_IDENTITY = "missing_identity"
    INVALID_IDENTITY = "invalid_identity"
    RESOURCE_NOT_OWNED = "resource_not_owned"
    OPERATION_NOT_PERMITTED = "operation_not_permitted"
    UNKNOWN_RESOURCE = "unknown_resource"
    UNKNOWN_OPERATION = "unknown_operation"

    # SECURITY_BLOCKED
    NETWORK_ACCESS = "network_access"
    FILESYSTEM_ESCAPE = "filesystem_escape"
    HOST_PATH_ACCESS = "host_path_access"
    PROJECT_TREE_ACCESS = "project_tree_access"
    SECRET_ACCESS = "secret_access"
    DATABASE_ACCESS = "database_access"
    PRIVILEGE_ESCALATION = "privilege_escalation"

    # PLAN_INVALID
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_TIMEOUT = "model_timeout"
    MODEL_OUTPUT_INVALID = "model_output_invalid"
    PLAN_REJECTED = "plan_rejected"

    # PLAN_STATE_MISMATCH
    PLAN_NOT_VALIDATED = "plan_not_validated"
    PLAN_CONSUMED = "plan_consumed"

    # DEPENDENCY_INVALID
    CYCLE_DETECTED = "cycle_detected"
    MISSING_DEPENDENCY = "missing_dependency"

    # TOOL_INPUT_INVALID
    INVALID_ARGUMENTS = "invalid_arguments"
    INPUT_TOO_LARGE = "input_too_large"

    # TOOL_EXECUTION_FAILED
    TOOL_RAISED = "tool_raised"
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"
    SANDBOX_TIMEOUT = "sandbox_timeout"
    SANDBOX_WORKSPACE_FAILED = "sandbox_workspace_failed"

    # TOOL_OUTPUT_INVALID
    INVALID_OUTPUT = "invalid_output"
    OUTPUT_TOO_LARGE = "output_too_large"

    # SANDBOX_VIOLATION
    VIOLATION_NETWORK = "violation_network"
    VIOLATION_FS_ESCAPE = "violation_fs_escape"
    VIOLATION_HOST_PATH = "violation_host_path"
    VIOLATION_PROJECT_TREE = "violation_project_tree"
    VIOLATION_SECRET = "violation_secret"
    VIOLATION_DATABASE = "violation_database"
    VIOLATION_PRIVILEGE = "violation_privilege"
    VIOLATION_PROCESS_LIMIT = "violation_process_limit"
    VIOLATION_MEMORY_LIMIT = "violation_memory_limit"
    VIOLATION_CPU_LIMIT = "violation_cpu_limit"
    VIOLATION_OUTPUT_LIMIT = "violation_output_limit"
    VIOLATION_ARTIFACT_LIMIT = "violation_artifact_limit"

    # RESOURCE_LIMIT
    CALL_BUDGET_EXCEEDED = "call_budget_exceeded"
    WALL_CLOCK_EXCEEDED = "wall_clock_exceeded"
    CONCURRENT_LIMIT = "concurrent_limit"

    # RESULT_UNREADABLE
    RESULT_MISSING = "result_missing"
    RESULT_NOT_JSON = "result_not_json"
    RESULT_TRUNCATED = "result_truncated"

    # VERIFICATION_FAILED
    FIELD_MISMATCH = "field_mismatch"
    MISSING_FIELD = "missing_field"
    UNEXPECTED_FIELD = "unexpected_field"
    MALFORMED_RESULT = "malformed_result"
    MALFORMED_INPUT = "malformed_input"
    NO_RULE = "no_rule"
    RESULT_UNREADABLE = "result_unreadable"
    TOOL_MISMATCH = "tool_mismatch"
    EXECUTION_NOT_RECONCILED = "execution_not_reconciled"

    # ARTIFACT_FAILED
    ARTIFACT_CORRUPT = "artifact_corrupt"
    ARTIFACT_TOO_LARGE = "artifact_too_large"
    ARTIFACT_PATH_INVALID = "artifact_path_invalid"
    ARTIFACT_OVERWRITE = "artifact_overwrite"

    # RECOVERY_EXHAUSTED
    MAX_ATTEMPTS = "max_attempts"

    # INTERNAL_ERROR
    UNEXPECTED_EXCEPTION = "unexpected_exception"


#: Code -> Category mapping. Single source of truth for retryability.
CODE_TO_CATEGORY: MappingProxyType[str, str] = MappingProxyType({
    # AUTHORIZATION_DENIED
    FailureCode.MISSING_IDENTITY.value: "authorization_denied",
    FailureCode.INVALID_IDENTITY.value: "authorization_denied",
    FailureCode.RESOURCE_NOT_OWNED.value: "authorization_denied",
    FailureCode.OPERATION_NOT_PERMITTED.value: "authorization_denied",
    FailureCode.UNKNOWN_RESOURCE.value: "authorization_denied",
    FailureCode.UNKNOWN_OPERATION.value: "authorization_denied",

    # SECURITY_BLOCKED
    FailureCode.NETWORK_ACCESS.value: "security_blocked",
    FailureCode.FILESYSTEM_ESCAPE.value: "security_blocked",
    FailureCode.HOST_PATH_ACCESS.value: "security_blocked",
    FailureCode.PROJECT_TREE_ACCESS.value: "security_blocked",
    FailureCode.SECRET_ACCESS.value: "security_blocked",
    FailureCode.DATABASE_ACCESS.value: "security_blocked",
    FailureCode.PRIVILEGE_ESCALATION.value: "security_blocked",

    # PLAN_INVALID
    FailureCode.MODEL_UNAVAILABLE.value: "plan_invalid",
    FailureCode.MODEL_TIMEOUT.value: "plan_invalid",
    FailureCode.MODEL_OUTPUT_INVALID.value: "plan_invalid",
    FailureCode.PLAN_REJECTED.value: "plan_invalid",

    # PLAN_STATE_MISMATCH
    FailureCode.PLAN_NOT_VALIDATED.value: "plan_state_mismatch",
    FailureCode.PLAN_CONSUMED.value: "plan_state_mismatch",

    # DEPENDENCY_INVALID
    FailureCode.CYCLE_DETECTED.value: "dependency_invalid",
    FailureCode.MISSING_DEPENDENCY.value: "dependency_invalid",

    # TOOL_INPUT_INVALID
    FailureCode.INVALID_ARGUMENTS.value: "tool_input_invalid",
    FailureCode.INPUT_TOO_LARGE.value: "tool_input_invalid",

    # TOOL_EXECUTION_FAILED
    FailureCode.TOOL_RAISED.value: "tool_execution_failed",
    FailureCode.SANDBOX_UNAVAILABLE.value: "tool_execution_failed",
    FailureCode.SANDBOX_TIMEOUT.value: "tool_execution_failed",
    FailureCode.SANDBOX_WORKSPACE_FAILED.value: "tool_execution_failed",

    # TOOL_OUTPUT_INVALID
    FailureCode.INVALID_OUTPUT.value: "tool_output_invalid",
    FailureCode.OUTPUT_TOO_LARGE.value: "tool_output_invalid",

    # SANDBOX_VIOLATION
    FailureCode.VIOLATION_NETWORK.value: "sandbox_violation",
    FailureCode.VIOLATION_FS_ESCAPE.value: "sandbox_violation",
    FailureCode.VIOLATION_HOST_PATH.value: "sandbox_violation",
    FailureCode.VIOLATION_PROJECT_TREE.value: "sandbox_violation",
    FailureCode.VIOLATION_SECRET.value: "sandbox_violation",
    FailureCode.VIOLATION_DATABASE.value: "sandbox_violation",
    FailureCode.VIOLATION_PRIVILEGE.value: "sandbox_violation",
    FailureCode.VIOLATION_PROCESS_LIMIT.value: "sandbox_violation",
    FailureCode.VIOLATION_MEMORY_LIMIT.value: "sandbox_violation",
    FailureCode.VIOLATION_CPU_LIMIT.value: "sandbox_violation",
    FailureCode.VIOLATION_OUTPUT_LIMIT.value: "sandbox_violation",
    FailureCode.VIOLATION_ARTIFACT_LIMIT.value: "sandbox_violation",

    # RESOURCE_LIMIT
    FailureCode.CALL_BUDGET_EXCEEDED.value: "resource_limit",
    FailureCode.WALL_CLOCK_EXCEEDED.value: "resource_limit",
    FailureCode.CONCURRENT_LIMIT.value: "resource_limit",

    # RESULT_UNREADABLE
    FailureCode.RESULT_MISSING.value: "result_unreadable",
    FailureCode.RESULT_NOT_JSON.value: "result_unreadable",
    FailureCode.RESULT_TRUNCATED.value: "result_unreadable",

    # VERIFICATION_FAILED
    FailureCode.FIELD_MISMATCH.value: "verification_failed",
    FailureCode.MISSING_FIELD.value: "verification_failed",
    FailureCode.UNEXPECTED_FIELD.value: "verification_failed",
    FailureCode.MALFORMED_RESULT.value: "verification_failed",
    FailureCode.MALFORMED_INPUT.value: "verification_failed",
    FailureCode.NO_RULE.value: "verification_failed",
    FailureCode.RESULT_UNREADABLE.value: "verification_failed",
    FailureCode.TOOL_MISMATCH.value: "verification_failed",
    FailureCode.EXECUTION_NOT_RECONCILED.value: "verification_failed",

    # ARTIFACT_FAILED
    FailureCode.ARTIFACT_CORRUPT.value: "artifact_failed",
    FailureCode.ARTIFACT_TOO_LARGE.value: "artifact_failed",
    FailureCode.ARTIFACT_PATH_INVALID.value: "artifact_failed",
    FailureCode.ARTIFACT_OVERWRITE.value: "artifact_failed",

    # RECOVERY_EXHAUSTED
    FailureCode.MAX_ATTEMPTS.value: "recovery_exhausted",

    # INTERNAL_ERROR
    FailureCode.UNEXPECTED_EXCEPTION.value: "internal_error",
})

assert len(CODE_TO_CATEGORY) == len(FailureCode)


def is_recoverable(category: str) -> bool:
    """Whether a failure category is potentially recoverable."""

    return category in {
        "tool_execution_failed",
        "resource_limit",
        "tool_input_invalid",
    }


def is_recoverable_code(code: str) -> bool:
    """Whether a failure code maps to a recoverable category."""

    category = CODE_TO_CATEGORY.get(code)
    if category is None:
        return False
    return is_recoverable(category)


def category_for_code(code: str) -> str:
    """The category for a failure code, or INTERNAL_ERROR if unknown."""

    return CODE_TO_CATEGORY.get(code, "internal_error")


def task_failure_category(categories: list[str]) -> str:
    """Derive the overall task failure category from a list of failure categories.

    Priority order (highest first):
    1. security_blocked (includes sandbox_violation)
    2. authorization_denied
    3. plan_invalid
    4. plan_state_mismatch
    5. dependency_invalid
    6. tool_output_invalid
    7. result_unreadable
    8. verification_failed
    9. artifact_failed
    10. recovery_exhausted
    11. tool_execution_failed
    12. resource_limit
    13. tool_input_invalid
    14. internal_error (fallback)

    This matches the ordering in NON_RECOVERABLE_CATEGORIES and
    RECOVERABLE_CATEGORIES, with non-recoverable taking precedence.
    """

    priority = [
        "security_blocked",
        "sandbox_violation",
        "authorization_denied",
        "plan_invalid",
        "plan_state_mismatch",
        "dependency_invalid",
        "tool_output_invalid",
        "result_unreadable",
        "verification_failed",
        "artifact_failed",
        "recovery_exhausted",
        "tool_execution_failed",
        "resource_limit",
        "tool_input_invalid",
        "internal_error",
    ]

    for cat in priority:
        if cat in categories:
            return cat
    return "internal_error"


class FailureWriteInvalid(ValueError):
    """A caller tried to write a failure the schema could not honestly hold."""
