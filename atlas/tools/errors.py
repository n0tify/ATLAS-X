"""Tool failure taxonomy.

Every way a tool invocation can fail has its own exception class, because a
caller has to be able to tell "you may not do that" apart from "that tool is
broken" without inspecting message text.

Two rules hold across the whole taxonomy:

* **Authorization failures are not tool failures.** An authorization denial
  raises :class:`atlas.security.errors.AuthorizationError` and is deliberately
  *not* wrapped, subclassed, or caught here. A dispatcher that converted a
  denial into a tool error would have turned a security decision into a
  diagnostic, and callers could no longer fail closed on it.
* **Messages are for operators, not for untrusted callers.** Tool errors carry
  a stable ``code`` for programmatic handling. Anything crossing a future
  process or network boundary must use a generic message, the same way
  authorization does; no exception here is safe to render verbatim to an
  end user today.
"""

from __future__ import annotations


class ToolErrorCode:
    """Stable programmatic classifications for tool failures."""

    MALFORMED_TOOL_ID = "malformed_tool_id"
    UNKNOWN_TOOL = "unknown_tool"
    INVALID_INPUT = "invalid_input"
    INPUT_TOO_LARGE = "input_too_large"
    OUTPUT_TOO_LARGE = "output_too_large"
    INVALID_OUTPUT = "invalid_output"
    EXECUTION_FAILED = "execution_failed"
    LIMIT_EXCEEDED = "limit_exceeded"
    UNSUPPORTED = "unsupported"
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"
    SANDBOX_VIOLATION = "sandbox_violation"
    SANDBOX_PROTOCOL_ERROR = "sandbox_protocol_error"


class ToolError(Exception):
    """Base class for every tool-layer failure. Never an authorization failure."""

    code = ToolErrorCode.EXECUTION_FAILED

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class MalformedToolId(ToolError):
    """The requested tool id is not a well-formed capability name."""

    code = ToolErrorCode.MALFORMED_TOOL_ID


class UnknownTool(ToolError):
    """No tool with that id is registered. Deny, never fall back to a default."""

    code = ToolErrorCode.UNKNOWN_TOOL


class ToolDefinitionInvalid(ToolError):
    """A tool definition is missing metadata or declares something contradictory.

    Raised while registering, so a malformed tool never becomes reachable.
    """

    code = ToolErrorCode.INVALID_INPUT


class ToolInputInvalid(ToolError):
    """Input did not satisfy the tool's declared input schema."""

    code = ToolErrorCode.INVALID_INPUT


class ToolInputTooLarge(ToolError):
    """Input exceeded the declared or configured input bound before execution."""

    code = ToolErrorCode.INPUT_TOO_LARGE


class ToolOutputInvalid(ToolError):
    """The implementation returned something the declared output schema forbids."""

    code = ToolErrorCode.INVALID_OUTPUT


class ToolOutputTooLarge(ToolError):
    """Serialized output exceeded the bound. Failed, never silently truncated."""

    code = ToolErrorCode.OUTPUT_TOO_LARGE


class ToolLimitExceeded(ToolError):
    """A declared per-invocation resource bound was exceeded.

    Also raised when elapsed time passes the declared budget. That check is
    post-hoc: it detects an overlong invocation, it cannot interrupt one.
    """

    code = ToolErrorCode.LIMIT_EXCEEDED


class ToolExecutionFailed(ToolError):
    """The registered implementation raised. The cause is never converted to a result."""

    code = ToolErrorCode.EXECUTION_FAILED


class ToolUnsupported(ToolError):
    """The tool declares a capability Phase 09 does not provide.

    Raised at registration for a tool that needs sandbox confinement, host
    filesystem access, or network access, and at dispatch for a capability the
    policy prohibits. Phase 09 fails closed here rather than degrading.
    """

    code = ToolErrorCode.UNSUPPORTED


class SandboxUnavailable(ToolError):
    """The sandbox could not be established, so the tool was not run.

    Raised when the guest is not provisioned, the launcher cannot be started, or
    the supervisor cannot read the launcher's report. The invocation fails. It is
    never downgraded into an in-process call, because a tool that runs without
    the confinement its registration requires is exactly the trusted bypass
    Phase 10 removed.
    """

    code = ToolErrorCode.SANDBOX_UNAVAILABLE


class SandboxViolation(ToolError):
    """A declared sandbox control was crossed during the invocation.

    Distinct from :class:`ToolExecutionFailed` on purpose. A tool that raises is
    broken; a tool that reached for the network, the project tree, a secret, or
    the database is a containment failure, and an incident review needs to see
    those two at different severities. The specific control is named in the
    message; the recorded code is stable either way.
    """

    code = ToolErrorCode.SANDBOX_VIOLATION
