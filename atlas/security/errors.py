"""Authorization exceptions with a stable internal classification.

Every failure carries a machine-readable :class:`~atlas.security.policy.DenyReason`
for internal diagnostics and audit, but the message a caller sees is always the
same string. A caller therefore cannot distinguish "you are not permitted" from
"that resource does not exist", which is what keeps a denied lookup from
becoming a resource-existence oracle.
"""

from __future__ import annotations

from atlas.security.policy import DenyReason

#: The single externally visible authorization failure message.
GENERIC_DENIAL_MESSAGE = "access denied"


class AuthorizationError(Exception):
    """Base class for every authorization failure. Always fails closed."""

    def __init__(self, reason: DenyReason) -> None:
        self.reason = reason
        super().__init__(GENERIC_DENIAL_MESSAGE)

    @property
    def external_message(self) -> str:
        """The only text that may cross a process or network boundary."""

        return GENERIC_DENIAL_MESSAGE


class Unauthenticated(AuthorizationError):
    """No usable identity was established: absent, malformed, expired, revoked."""

    def __init__(self, reason: DenyReason = DenyReason.MISSING_IDENTITY) -> None:
        super().__init__(reason)


class InvalidAuthorizationRequest(AuthorizationError):
    """The request could not be evaluated: unknown resource/operation or bad id."""

    def __init__(self, reason: DenyReason = DenyReason.MALFORMED_RESOURCE_ID) -> None:
        super().__init__(reason)


class PermissionDenied(AuthorizationError):
    """The actor is authenticated but the operation is not permitted.

    Raised for a resource the actor does not own as well as for one that does
    not exist, so the reason cannot be used to probe for protected rows.
    """

    def __init__(
        self, reason: DenyReason = DenyReason.RESOURCE_NOT_OWNED
    ) -> None:
        super().__init__(reason)


class ResultUnpublishable(AuthorizationError):
    """A successful task result was asked for without the proof that entitles it.

    Separate from :class:`PermissionDenied` because the actor is not the problem:
    the caller owns the task and holds ``TASK.UPDATE``. What is missing is a
    recorded PASS verdict for every execution of the task, which
    :meth:`~atlas.security.service.AuthorizationService.finish_verified_task`
    checks before it writes anything.

    It exists as its own type so that "the result was withheld for want of
    evidence" cannot be confused with "you may not", which would otherwise push a
    caller towards reporting a verification gap as an access-control problem.
    """

    def __init__(
        self, reason: DenyReason = DenyReason.OPERATION_NOT_PERMITTED
    ) -> None:
        super().__init__(reason)


class RecoveryNotPermitted(AuthorizationError):
    """Recovery was attempted but the task/failure is not eligible.

    Raised when a caller attempts to recover from a failure that is not
    recoverable (e.g., sandbox violation, authorization denied) or when
    the recovery limit has been exhausted.
    """

    def __init__(
        self, reason: DenyReason = DenyReason.OPERATION_NOT_PERMITTED
    ) -> None:
        super().__init__(reason)


class FailureCategoryNotDerived(AuthorizationError):
    """A caller tried to set a task's status to 'failed' directly.

    The failure category must be derived from recorded failures, not supplied.
    """
