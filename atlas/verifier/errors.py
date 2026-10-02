"""Why a verification could not proceed.

Distinct from a FAIL verdict, and the distinction matters:

* A **FAIL verdict** is an answer. The verifier ran, reached a verdict, and stored
  the evidence. :class:`~atlas.verifier.service.VerifierService.verify_task`
  returns it as a report rather than raising.
* A **refusal** is the absence of an answer. The task was not in a state that can
  be verified, or a required record was missing, or a stored row could not be
  read. Raising here is what stops the caller from treating "could not check" as
  "checked and fine".

An authorization denial is deliberately *not* in this module. It arrives as
:class:`~atlas.security.errors.AuthorizationError` straight from the authorization
boundary and propagates unchanged, for the same reason the dispatcher does not
wrap it: a caller that cannot tell "you may not" from "the tool broke" cannot fail
closed on the first.
"""

from __future__ import annotations


class VerificationErrorCode:
    """Stable programmatic classifications for refusals."""

    TASK_NOT_EXECUTED = "task_not_executed"
    NO_EXECUTION = "no_execution"
    EXECUTION_INCOMPLETE = "execution_incomplete"
    PLAN_NOT_EXECUTABLE = "plan_not_executable"
    RESULT_MISSING = "result_missing"
    RESULT_UNREADABLE = "result_unreadable"
    STEP_UNREADABLE = "step_unreadable"
    ALREADY_VERIFIED = "already_verified"
    EXECUTION_NOT_RECONCILED = "execution_not_reconciled"


class VerificationRefused(Exception):
    """The verifier declined to produce a verdict. Never a PASS, never a FAIL."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code or VerificationErrorCode.TASK_NOT_EXECUTED
