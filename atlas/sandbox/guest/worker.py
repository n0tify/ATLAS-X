"""The process that runs inside the confinement and calls a tool body.

This is the only code that executes a registered implementation, and it does so
with no database connection, no network namespace route, no writable path but
the workspace, and an unprivileged uid. Its job is narrow on purpose:

1. Refuse to run at all if it is not who it was supposed to be. A worker that
   finds itself running as uid 0, or able to see a denied host path, reports a
   violation instead of proceeding, because a sandbox that was built wrong must
   not produce a successful-looking result.
2. Decode the request strictly and re-resolve the tool from the registry that
   was shipped into the guest. The ``tool_id`` in the request selects a
   definition from the same frozen list the platform uses; it is never a module
   path and never an import. A request naming a tool the guest does not have is
   refused.
3. Build the owner-scoped view from the snapshot and call the body.
4. Validate the body's output against the definition's own output schema and
   against the invocation's size bound, then hand it back.

Steps 1 and 4 are the ones that are easy to leave out. The platform already
validated input and already validates output on the far side of the boundary, but
validating twice is not redundancy for its own sake: the far side is the
component that trusts this process, so the cheap check that would catch a
compromised or mis-installed guest belongs here, where the compromise is visible.

The worker's own stdout and stderr are captured by the launcher into bounded
files. That is not tidiness: this process shares a stdout with the launcher's
report, and a tool body that printed to fd 1 could otherwise forge a result
document.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from typing import Any, Final

from atlas.sandbox.guest.view import SnapshotAccessError, SnapshotView, Violation
from atlas.sandbox.policy import READ_ONLY_PATHS
from atlas.sandbox.protocol import (
    MAX_ENVELOPE_BYTES,
    PROTOCOL_VERSION,
    ProtocolError,
    Request,
    Status,
    ViolationKind,
    WorkerReport,
    decode_request,
)

__all__ = ["main", "run_request"]

#: Paths that must not resolve inside the namespace. Duplicated from the policy
#: module deliberately: the worker checks them with its own ``os.stat`` rather
#: than trusting that the launcher built the namespace correctly, because the
#: worker is the process whose confinement the guarantee is about.
#:
#: Absence is the right question for these and only for these. ``/proc/sys`` used
#: to be in this list and it was wrong twice over: a ``--proc`` mount always
#: contains it, so every run failed closed, and it was the one path here that
#: genuinely needed guarding. Those paths now live in
#: :data:`atlas.sandbox.policy.READ_ONLY_PATHS` and are checked for write access.
DENIED_PATHS: Final[tuple[str, ...]] = (
    "/mnt",
    "/media",
    "/srv",
    "/home",
    "/root",
    "/run",
    "/var/lib/atlasx",
    "/etc/resolv.conf",
    "/etc/hosts",
)


def _check_identity() -> None:
    """Refuse to proceed unless this process is unprivileged.

    A worker running as root would turn every other control into a suggestion.
    Reporting this is more useful than carrying on, because the two most likely
    causes are a broken uid mapping in the namespace setup and a guest that was
    provisioned to run the worker as root.
    """

    if os.geteuid() == 0 or os.getegid() == 0:
        raise Violation(
            ViolationKind.PRIVILEGE_ESCALATION,
            "the sandboxed worker is running with uid or gid 0",
        )


def _check_paths(request: Request) -> None:
    """Confirm the denied paths really are not there.

    Uses ``os.path.lexists`` rather than ``exists`` so that a dangling symlink
    planted at a denied path is also treated as a finding: the point is that
    nothing at all lives there, not that nothing resolvable lives there.
    """

    for path in DENIED_PATHS:
        try:
            if os.path.lexists(path):
                raise Violation(
                    ViolationKind.FILESYSTEM_ESCAPE,
                    f"a path that must not be reachable exists inside the sandbox: {path}",
                )
        except OSError as exc:
            raise Violation(
                ViolationKind.FILESYSTEM_ESCAPE,
                f"could not confirm that {path} is absent: {exc.strerror}",
            ) from exc

    for path in request.denied_paths:
        try:
            if os.path.lexists(path):
                raise Violation(
                    ViolationKind.HOST_PATH_ACCESS,
                    f"a host path the caller named is reachable inside the sandbox: {path}",
                )
        except OSError:
            continue

    # Presence is the wrong question for these and was the wrong question here:
    # ``/proc/sys`` is always present on a ``--proc`` mount, so listing it among
    # the absent paths made every legitimate invocation fail closed while the
    # thing it was nominally guarding stayed writable. What matters is whether a
    # write would be accepted, and that is asked about rather than performed, so
    # detecting a broken namespace does not itself change host kernel state.
    for path in READ_ONLY_PATHS:
        if not os.path.lexists(path):
            continue
        if os.access(path, os.W_OK):
            raise Violation(
                ViolationKind.PRIVILEGE_ESCALATION,
                f"a path that must be read-only is writable inside the sandbox: {path}",
            )


def _resolve_definition(request: Request) -> Any:
    """Look the tool up in the guest's own copy of the frozen registry."""

    from atlas.tools.builtin import build_definitions

    for definition in build_definitions():
        if definition.tool_id != request.tool_id:
            continue
        if definition.version != request.tool_version:
            raise ProtocolError(
                f"guest has {request.tool_id} {definition.version}, the supervisor "
                f"asked for {request.tool_version}"
            )
        if definition.implementation_id != request.implementation_id:
            raise ProtocolError(
                f"guest has {definition.implementation_id!r} for "
                f"{request.tool_id!r}, the supervisor asked for "
                f"{request.implementation_id!r}"
            )
        return definition
    raise ProtocolError(f"the guest does not provide a tool named {request.tool_id!r}")


def _check_artifact_bound(workspace: str, limit: int) -> None:
    """Reject an invocation that wrote more into the workspace than allowed.

    Checked here, inside the confinement, so the number is measured against the
    files the tool actually produced rather than against a number it chose to
    report. A tool that fills the workspace is stopped at the boundary it
    controls instead of consuming the host's disk.
    """

    total = 0
    for root, _dirs, files in os.walk(workspace):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                continue
            if total > limit:
                raise Violation(
                    ViolationKind.ARTIFACT_LIMIT,
                    f"the invocation wrote more than {limit} bytes into its workspace",
                )


def run_request(request: Request) -> WorkerReport:
    """Run one tool body under ``request`` and report what happened.

    Returns a report rather than raising, because every outcome — including a
    refused identity and a malformed request — has to reach the launcher as data
    it can put on the single response channel.
    """

    try:
        if request.protocol_version != PROTOCOL_VERSION:
            raise ProtocolError("protocol version mismatch inside the guest")
        _check_identity()
        _check_paths(request)
        definition = _resolve_definition(request)
    except Violation as exc:
        return WorkerReport(
            status=Status.POLICY_DENIED.value,
            violation=exc.kind.value,
            output=None,
            error_message=str(exc),
        )
    except ProtocolError as exc:
        return WorkerReport(
            status=Status.INTERNAL_ERROR.value,
            violation=ViolationKind.PROTOCOL_ERROR.value,
            output=None,
            error_message=str(exc),
        )

    from atlas.tools.definition import ToolContext
    from atlas.tools.errors import ToolError
    from atlas.tools.schema import validate_output

    view = SnapshotView(request.snapshots, user_id=request.user_id, task_id=request.task_id)
    context = ToolContext(user_id=request.user_id, task_id=request.task_id, view=view)

    try:
        produced = definition.invoke(context, request.arguments)
        result = validate_output(definition.output_schema, produced)
    except Violation as exc:
        return WorkerReport(
            status=Status.POLICY_DENIED.value,
            violation=exc.kind.value,
            output=None,
            error_message=str(exc),
        )
    except ToolError as exc:
        return WorkerReport(
            status=Status.TOOL_ERROR.value,
            violation=ViolationKind.TOOL_ERROR.value,
            output=None,
            error_message=f"{type(exc).__name__}: {exc}",
            # The class name in the message is for a human reading a log. This is
            # the machine-readable half, and it is what lets the host raise the
            # same specific exception the tool raised rather than collapsing every
            # tool failure into one generic code.
            error_code=exc.code,
        )
    except SnapshotAccessError as exc:
        return WorkerReport(
            status=Status.TOOL_ERROR.value,
            violation=ViolationKind.TOOL_ERROR.value,
            output=None,
            error_message=f"{type(exc).__name__}: {exc}",
        )
    except BaseException as exc:  # noqa: BLE001 - a tool body may raise anything
        return WorkerReport(
            status=Status.TOOL_ERROR.value,
            violation=ViolationKind.TOOL_ERROR.value,
            output=None,
            error_message=f"{type(exc).__name__}: {exc}",
        )

    try:
        encoded = json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        return WorkerReport(
            status=Status.TOOL_ERROR.value,
            violation=ViolationKind.OUTPUT_LIMIT.value,
            output=None,
            error_message=f"tool output is not JSON-serializable: {exc}",
        )

    if len(encoded) > min(request.limits.max_output_bytes, MAX_ENVELOPE_BYTES):
        from atlas.tools.errors import ToolErrorCode

        return WorkerReport(
            status=Status.RESOURCE_EXCEEDED.value,
            violation=ViolationKind.OUTPUT_LIMIT.value,
            output=None,
            error_message=(
                f"tool output of {len(encoded)} bytes exceeds the bound "
                f"{request.limits.max_output_bytes}"
            ),
            # ``OUTPUT_TOO_LARGE`` rather than a bare resource failure, because
            # Phase 09 recorded this exact condition under that code and the audit
            # trail is supposed to survive the move into a subprocess. The
            # ``RESOURCE_EXCEEDED`` status still says a bound was hit; the code
            # says which one.
            error_code=ToolErrorCode.OUTPUT_TOO_LARGE,
        )

    return WorkerReport(
        status=Status.OK.value, violation=None, output=result, error_message=None
    )


def _write_atomic(path: str, payload: bytes) -> None:
    """Write the report so a reader never sees a half-written document."""

    temporary = f"{path}.partial"
    with open(temporary, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_report(path: str, report: WorkerReport) -> None:
    encoded = json.dumps(
        report.as_json(), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    _write_atomic(path, encoded)


def main(argv: list[str] | None = None) -> int:
    """Entry point: ``python3 -m atlas.sandbox.guest.worker REQUEST RESULT``."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 2:
        sys.stderr.write("usage: worker REQUEST_JSON RESULT_JSON\n")
        return 2
    request_path, result_path = arguments

    try:
        with open(request_path, "rb") as handle:
            payload = handle.read()
        request = decode_request(payload)
    except (OSError, ProtocolError) as exc:
        _write_report(
            result_path,
            WorkerReport(
                status=Status.INTERNAL_ERROR.value,
                violation=ViolationKind.PROTOCOL_ERROR.value,
                output=None,
                error_message=f"the guest could not read the request: {exc}",
            ),
        )
        return 0

    try:
        report = run_request(request)
        workspace = request.extra_env.get("ATLASX_WORKSPACE", "/workspace")
        _check_artifact_bound(workspace, request.limits.max_artifact_bytes)
    except Violation as exc:
        report = WorkerReport(
            status=Status.RESOURCE_EXCEEDED.value,
            violation=exc.kind.value,
            output=None,
            error_message=str(exc),
        )
    except BaseException as exc:  # noqa: BLE001
        traceback.print_exc(file=sys.stderr)
        report = WorkerReport(
            status=Status.INTERNAL_ERROR.value,
            violation=ViolationKind.INTERNAL_ERROR.value,
            output=None,
            error_message=f"{type(exc).__name__}: {exc}",
        )

    try:
        _write_report(result_path, report)
    except OSError as exc:
        sys.stderr.write(f"could not write the worker report: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
