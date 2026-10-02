"""Execution failure taxonomy.

An execution fails in ways that a caller, the failure classifier (Phase 15), and
recovery (Phase 16) each need to tell apart, so the distinctions are classes
rather than message text. Two boundaries matter most:

* **A refusal and a step failure are different.** :class:`PlanNotExecutable` means
  ATLAS-X declined to start -- an unvalidated plan, a duplicate run, a spent
  budget. :class:`StepFailed` means the run started and a tool call did not
  succeed. Recovery may retry the second and must never retry the first.
* **An authorization denial is not an execution failure.** It raises
  :class:`~atlas.security.errors.AuthorizationError` from
  :class:`~atlas.security.service.AuthorizationService` and is deliberately not
  wrapped here, for the same reason the dispatcher does not wrap it: a caller that
  cannot tell "you may not" from "the tool broke" cannot fail closed on the first.

No execution failure is converted into a successful result, and no step's output
is reported for a step that did not produce one.
"""

from __future__ import annotations


class ExecutionErrorCode:
    """Stable programmatic classifications for execution failures."""

    PLAN_NOT_EXECUTABLE = "plan_not_executable"
    DUPLICATE_EXECUTION = "duplicate_execution"
    STEP_FAILED = "step_failed"
    BUDGET_EXCEEDED = "budget_exceeded"
    EXECUTION_UNAVAILABLE = "execution_unavailable"


class ExecutionError(Exception):
    """Base class for every execution failure. Never an authorization failure."""

    code = ExecutionErrorCode.STEP_FAILED

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class PlanNotExecutable(ExecutionError):
    """The plan may not be run, so no execution was started.

    The most common cause by design: Phase 11 persists plans it *rejected* as
    well as plans it accepted, and only the latter carry ``validated = 1``. A
    rejected plan is a record of what the model proposed, not a program, so this
    is refused before any tool is named.

    Recovery never retries this. There is nothing to recover: the plan itself is
    the problem.
    """

    code = ExecutionErrorCode.PLAN_NOT_EXECUTABLE


class DuplicateExecution(ExecutionError):
    """Another execution of this task is already in flight.

    Refused rather than queued. Two runs of the same plan would produce two sets
    of executions for one task, and which of them "the" result is would be
    decided by whichever finished last rather than by anything recorded.
    """

    code = ExecutionErrorCode.DUPLICATE_EXECUTION


class ExecutionBudgetExceeded(ExecutionError):
    """A configured bound -- calls, steps, or wall clock -- stopped the run."""

    code = ExecutionErrorCode.BUDGET_EXCEEDED


class StepFailed(ExecutionError):
    """A step's tool call did not succeed, so the run stopped there.

    Carries the step key and the tool's own error code, because "the plan failed"
    is not actionable and ``text_statistics:invalid_input`` is. The tool's code is
    recorded, never its message: the message is for an operator and may name
    internals the caller has no business seeing.
    """

    code = ExecutionErrorCode.STEP_FAILED

    def __init__(self, message: str, *, step_key: str, error_code: str) -> None:
        super().__init__(message)
        self.step_key = step_key
        self.error_code = error_code
