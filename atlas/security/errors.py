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
