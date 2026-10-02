"""Sandbox failures, expressed in the platform's existing tool error taxonomy.

Every failure mode in this subsystem is one of two things, and the distinction
is the one the audit log cares about: either the sandbox *held* and the tool body
itself failed, or a control was *crossed*. Conflating the two would make
"the tool raised" and "the tool tried to open a socket" look the same in
``provenance_events``, which is exactly the distinction an incident review needs.

So there are no new top-level exception families here. Every sandbox failure
subclasses :class:`atlas.tools.errors.ToolError`, which means the dispatcher's
existing failure path, its failure recording, and its error codes keep working
unchanged, and an operator reading the audit log sees one consistent set of
codes. A sandbox error is never an authorization error: by the time anything
here is raised, authorization has already succeeded.

The one failure this module refuses to disguise is unavailability. If the guest
is not provisioned, or the launcher cannot be started, the invocation fails. It
does not fall back to running the tool in-process, because "the sandbox was
missing so we ran it unsandboxed" is precisely the trusted bypass Phase 10B
exists to remove.
"""

from __future__ import annotations

from typing import Any, Final, Mapping

# ``atlas.tools.errors`` is imported as a module rather than by name. The
# package initializer for ``atlas.tools`` re-exports the dispatcher, and the
# dispatcher imports the supervisor, which imports this module — so reaching for
# ``atlas.tools.errors`` attributes during a cold ``import atlas.sandbox``
# would find that package only half-initialized. Importing the leaf module
# directly breaks the cycle without depending on import order.
from atlas.sandbox.protocol import ProtocolError, Status, ViolationKind
from atlas.tools.errors import (
    MalformedToolId,
    SandboxUnavailable,
    SandboxViolation,
    ToolError,
    ToolErrorCode,
    ToolExecutionFailed,
    ToolInputInvalid,
    ToolInputTooLarge,
    ToolLimitExceeded,
    ToolOutputInvalid,
    ToolOutputTooLarge,
    ToolUnsupported,
    UnknownTool,
)

#: Platform error code -> the exception class a caller expects for it. Used to
#: rebuild the worker's own classification on this side of the process boundary.
#:
#: Two codes map to more than one class (``invalid_input`` is raised both by a
#: malformed definition and by a rejected argument), so the table resolves to the
#: one a *sandboxed* tool can actually produce. Codes with no entry fall back to
#: :class:`ToolExecutionFailed`, which is the honest answer for a code this
#: process does not know about rather than a crash.
_TOOL_ERROR_TYPES: Final[Mapping[str, type[ToolError]]] = {
    ToolErrorCode.INVALID_INPUT: ToolInputInvalid,
    ToolErrorCode.INPUT_TOO_LARGE: ToolInputTooLarge,
    ToolErrorCode.OUTPUT_TOO_LARGE: ToolOutputTooLarge,
    ToolErrorCode.INVALID_OUTPUT: ToolOutputInvalid,
    ToolErrorCode.LIMIT_EXCEEDED: ToolLimitExceeded,
    ToolErrorCode.EXECUTION_FAILED: ToolExecutionFailed,
    ToolErrorCode.UNSUPPORTED: ToolUnsupported,
    ToolErrorCode.UNKNOWN_TOOL: UnknownTool,
    ToolErrorCode.MALFORMED_TOOL_ID: MalformedToolId,
}

__all__ = [
    "SandboxError",
    "SandboxLauncherMissing",
    "SandboxProtocolFailure",
    "SandboxTimeout",
    "SandboxWorkspaceFailure",
    "VIOLATION_CODES",
    "classify_envelope",
    "exception_for",
]

#: Violation kinds that mean "a control was crossed" rather than "the tool
#: misbehaved within the sandbox". These get a violation code in the audit log.
CROSSED_CONTROL: Final = frozenset(
    {
        ViolationKind.NETWORK_ACCESS,
        ViolationKind.FILESYSTEM_ESCAPE,
        ViolationKind.HOST_PATH_ACCESS,
        ViolationKind.PROJECT_TREE_ACCESS,
        ViolationKind.SECRET_ACCESS,
        ViolationKind.DATABASE_ACCESS,
        ViolationKind.PRIVILEGE_ESCALATION,
    }
)

#: Violation kinds that are resource bounds rather than access violations.
CROSSED_BOUND: Final = frozenset(
    {
        ViolationKind.PROCESS_LIMIT,
        ViolationKind.MEMORY_LIMIT,
        ViolationKind.CPU_LIMIT,
        ViolationKind.OUTPUT_LIMIT,
        ViolationKind.ARTIFACT_LIMIT,
    }
)

#: Maps a violation label onto the stable audit code recorded for it. Every
#: violation gets a distinct code, so "attempted network access" is
#: distinguishable from "read the project tree" after the fact.
VIOLATION_CODES: Final[Mapping[ViolationKind, str]] = {
    ViolationKind.NETWORK_ACCESS: "network_access",
    ViolationKind.FILESYSTEM_ESCAPE: "filesystem_escape",
    ViolationKind.HOST_PATH_ACCESS: "host_path_access",
    ViolationKind.PROJECT_TREE_ACCESS: "project_tree_access",
    ViolationKind.SECRET_ACCESS: "secret_access",
    ViolationKind.DATABASE_ACCESS: "database_access",
    ViolationKind.PRIVILEGE_ESCALATION: "privilege_escalation",
    ViolationKind.PROCESS_LIMIT: "process_limit",
    ViolationKind.MEMORY_LIMIT: "memory_limit",
    ViolationKind.CPU_LIMIT: "cpu_limit",
    ViolationKind.OUTPUT_LIMIT: "output_limit",
    ViolationKind.ARTIFACT_LIMIT: "artifact_limit",
    ViolationKind.TIMEOUT: "timeout",
    ViolationKind.TOOL_ERROR: "tool_error",
    ViolationKind.INTERNAL_ERROR: "internal_error",
    ViolationKind.PROTOCOL_ERROR: "protocol_error",
}


class SandboxError(ToolError):
    """Base class for sandbox-layer failures.

    Not raised directly. It exists so a caller that wants to distinguish
    "something about the sandbox went wrong" from "the tool went wrong" has a
    single type to catch, and so the code is stable if the subclasses move.
    """

    code = ToolErrorCode.SANDBOX_UNAVAILABLE


class SandboxLauncherMissing(SandboxUnavailable):
    """The guest launcher is not present, or the distro will not start.

    Refused rather than worked around. A missing launcher means the confinement
    guarantee is not there, and the honest response to a missing security
    control is to fail the call.
    """


class SandboxProtocolFailure(SandboxError):
    """The launcher spoke something this supervisor does not understand."""

    code = ToolErrorCode.SANDBOX_PROTOCOL_ERROR


class SandboxTimeout(ToolLimitExceeded):
    """The invocation exceeded its wall-clock bound and the tree was killed."""


class SandboxWorkspaceFailure(SandboxError):
    """The per-execution workspace could not be prepared or collected."""


class SandboxCallerError(SandboxError):
    """The request this module was asked to build is not dispatchable.

    Raised before any guest work happens, so a programming error upstream is
    reported as such instead of being turned into a mysterious guest failure.
    """


def exception_for(
    status: Status,
    violation: ViolationKind | None,
    message: str,
    error_code: str | None = None,
) -> ToolError:
    """Turn a guest-reported outcome into the platform's error taxonomy.

    The mapping is total: every status has a failure, and every violation kind
    that a guest can legitimately report lands on a specific exception. There is
    no path here that returns ``None`` and therefore no path that silently
    treats a failed sandbox run as a success.

    ``error_code`` is what keeps a tool's own classification intact across the
    process boundary. A tool that rejects its input raises ``ToolInputInvalid``
    inside the guest; without the code the host sees only "the tool raised" and
    reports ``execution_failed``, which merges an input rejection with a crash and
    with an output-schema rejection. The code is matched against a table of the
    platform's own exception classes, so a caller catching ``ToolOutputInvalid``
    still catches it.
    """

    detail = message or "sandboxed invocation failed"

    if status is Status.OK:
        raise ValueError("exception_for called for a successful outcome")

    if status is Status.POLICY_DENIED:
        # A crossed control is decided by the violation label, never by the code.
        # The guest reports *which control* was crossed, which is the question an
        # incident review asks; honouring a code here would let the tool's own
        # exception type override the sandbox's account of what happened to it.
        assert violation is not None
        if violation in CROSSED_CONTROL:
            return SandboxViolation(
                f"sandbox control violated ({violation.value}): {detail}"
            )
        if violation in CROSSED_BOUND:
            return ToolLimitExceeded(
                f"sandbox bound exceeded ({violation.value}): {detail}"
            )
        return SandboxViolation(f"sandbox refused the invocation: {detail}")

    if status is Status.TIMEOUT:
        return SandboxTimeout(detail)

    # Everything below is a failure the confined process classified itself. Its
    # code is more specific than the status, and using it is what keeps a rejected
    # input, a rejected output, and an oversized output distinguishable on this
    # side of the boundary — which is the entire reason the code is on the wire.
    specific = _TOOL_ERROR_TYPES.get(error_code or "")
    if specific is not None:
        return specific(detail)

    if status is Status.TOOL_ERROR:
        return ToolExecutionFailed(f"tool raised inside the sandbox: {detail}")

    if status is Status.RESOURCE_EXCEEDED:
        return ToolLimitExceeded(detail)

    return SandboxError(f"sandbox internal error: {detail}")


def classify_envelope(
    *,
    status: str,
    violation: str | None,
    message: str | None,
    error_code: str | None = None,
) -> ToolError:
    """Map the string form carried in a decoded envelope onto an exception.

    Kept separate from :func:`exception_for` so the decoding path works with
    raw JSON strings and so a malformed status is itself a classified failure
    rather than an unhandled ``ValueError``.
    """

    try:
        parsed_status = Status(status)
    except ValueError:
        return SandboxProtocolFailure(f"guest reported an unknown status {status!r}")
    parsed_violation: ViolationKind | None = None
    if violation is not None:
        try:
            parsed_violation = ViolationKind(violation)
        except ValueError:
            return SandboxProtocolFailure(
                f"guest reported an unknown violation {violation!r}"
            )
    return exception_for(
        parsed_status, parsed_violation, message or "", error_code
    )


def describe_violation(violation: ViolationKind) -> str:
    """The stable audit code for a violation label."""

    return VIOLATION_CODES[violation]


def as_tool_error(error: BaseException) -> ToolError:
    """Ensure a sandbox-layer exception is usable by the dispatcher's recording.

    Anything that is already a :class:`ToolError` passes through untouched. A
    raw ``ProtocolError`` or ``OSError`` becomes an explicit sandbox failure, so
    the failure recording path never sees an exception without a code.
    """

    if isinstance(error, ToolError):
        return error
    if isinstance(error, ProtocolError):
        return SandboxProtocolFailure(str(error))
    return SandboxUnavailable(f"sandbox unavailable: {type(error).__name__}")


def violation_code(error: BaseException) -> str:
    """The audit code to record for a sandbox failure."""

    if isinstance(error, ToolError):
        return error.code
    return ToolErrorCode.SANDBOX_UNAVAILABLE


def _unused(*_args: Any) -> None:  # pragma: no cover - keeps linters honest
    return None
