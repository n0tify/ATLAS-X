"""The privileged guest launcher: builds the confinement and enforces the limits.

This is the only component that runs as root, and it runs as root only long
enough to create things. Its responsibilities, in order:

1. Read one request from stdin and validate it strictly, including the
   ``execution_id`` against a fixed 32-character hex pattern. That id becomes a
   directory name, so it is checked before it is interpolated into any path: this
   is the one place a path-traversal bug could reach the guest filesystem, and a
   pattern is cheaper and more obviously correct than escaping.
2. Create a fresh workspace with ``input/``, ``output/``, and ``tmp/``, owned by
   the unprivileged worker uid and writable by nobody else. The workspace is
   created restrictive before the request is written into it, so there is no
   window in which the request exists in a directory another user on the guest
   can read.
3. Create a cgroup and apply the memory, process, and CPU bounds.
4. Build the ``bwrap`` argument vector and start the process in its own session,
   then move it into the cgroup. Membership is inherited, so every descendant the
   worker spawns is bounded by the same files.
5. Enforce the wall clock. On expiry it signals the process *group* — which
   covers a double-forked descendant that is no longer a child of the worker —
   escalating ``SIGTERM`` to ``SIGKILL``, and then uses ``cgroup.kill`` as a last
   resort for anything that escaped even that. This is the guarantee
   ``memory.max`` is not: ``memory.max`` reclaims and may never fire the OOM
   killer, whereas this path is unconditional.
6. Read the worker's report, capture bounded diagnostics, tear the workspace and
   the cgroup down, and write exactly one envelope to stdout.

The watchdog thread in step 5 exists because a launcher that hangs is worse than
one that fails: it would hold the supervisor's connection open until the
supervisor's own, longer backstop fires. It gives up first, and says so.

Nothing here reads a tool's stdout to decide success. The result document is a
file the worker wrote, and the streams are only ever included as bounded
diagnostics, so a tool body cannot forge a successful outcome by printing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Final

from atlas.sandbox import cgroups
from atlas.sandbox.environment import ENVIRONMENT_NAMES, build_environment
from atlas.sandbox.namespaces import build_argv, probe_merged_usr
from atlas.sandbox.policy import INPUT_SUBDIR, OUTPUT_SUBDIR, TMP_SUBDIR, build_policy
from atlas.sandbox.protocol import (
    GUEST_PYTHON,
    GUEST_WORKSPACE_ROOT,
    MAX_DIAGNOSTIC_BYTES,
    MAX_REQUEST_BYTES,
    PROTOCOL_VERSION,
    WORKER_GID,
    WORKER_UID,
    Diagnostics,
    Envelope,
    Limits,
    ProtocolError,
    Request,
    Status,
    ViolationKind,
    WorkerReport,
    decode_request,
    encode_envelope,
)

__all__ = ["main"]

#: The supervisor generates this with ``uuid4().hex``. Matching it exactly is
#: what makes the workspace path a function of a validated value rather than of
#: caller text.
EXECUTION_ID_PATTERN: Final = re.compile(r"^[0-9a-f]{32}$")

#: How long a terminated process group is given to exit before ``SIGKILL``.
#: Long enough for a clean interpreter shutdown, short enough that a caller
#: waiting on the timeout does not pay for it twice.
TERMINATION_GRACE_SECONDS: Final = 2.0

#: How long the launcher waits for the process group to disappear after
#: ``SIGKILL`` before reporting that something survived it.
REAP_SECONDS: Final = 3.0

#: The watchdog fires this long after the invocation's own deadline, so the
#: launcher cannot outlive the supervisor's backstop.
WATCHDOG_MARGIN_SECONDS: Final = 15.0

EXIT_WATCHDOG: Final = 70

#: Where the worker writes its report inside the workspace. Fixed rather than
#: derived from the request, so a request cannot point the report somewhere else.
REQUEST_NAME: Final = "request.json"
RESULT_NAME: Final = "result.json"
STDOUT_NAME: Final = "stdout.log"
STDERR_NAME: Final = "stderr.log"

#: Installed by provisioning. The confined command is started through this rather
#: than adopted after the fact, so that the process is inside its cgroup before it
#: becomes a workload; see :func:`atlas.sandbox.cgroups.exec_in_group`.
GUEST_JOINER_PATH: Final = "/opt/atlasx/bin/cgroup-join"


def _tail(path: str, limit: int = MAX_DIAGNOSTIC_BYTES) -> str:
    """The last ``limit`` bytes of a file, decoded leniently.

    A tail rather than a head because the diagnostically useful part of a failed
    run is what it said last: the traceback, the assertion, the line the tool was
    on when the cgroup stopped it. Decoding is lenient because a process killed
    mid-write leaves a partial final line, and that must not hide the rest.
    """

    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            if size > limit:
                handle.seek(size - limit)
            payload = handle.read()
    except OSError:
        return ""
    return payload.decode("utf-8", errors="replace")


def _read_bounded_stdin() -> bytes:
    """Read the request from stdin, refusing more than the protocol allows."""

    payload = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(payload) > MAX_REQUEST_BYTES:
        raise ProtocolError("the request exceeded the transfer bound")
    return payload


def _envelope(
    *,
    status: Status,
    violation: ViolationKind | None,
    output: dict[str, Any] | None,
    message: str | None,
    elapsed_ms: int,
    diagnostics: Diagnostics,
    error_code: str | None = None,
) -> Envelope:
    return Envelope(
        protocol_version=PROTOCOL_VERSION,
        status=status.value,
        violation=None if violation is None else violation.value,
        output=output,
        error_message=message,
        elapsed_ms=elapsed_ms,
        diagnostics=diagnostics,
        error_code=error_code,
    )


def _empty_diagnostics() -> Diagnostics:
    return Diagnostics(
        exit_code=None,
        signal=None,
        stdout="",
        stderr="",
        cgroup_peak_bytes=None,
        cgroup_events={},
    )


def _prepare_workspace(execution_id: str) -> str:
    """Create the per-invocation workspace tree and return its path.

    Created with mode ``0o700`` before anything is written, and left owned by
    guest-root. That looks wrong and is not: the launcher runs as root, and
    ``bwrap --unshare-user`` maps exactly one uid, ``WORKER_UID -> 0``. A
    directory owned on the guest by uid 65534 is therefore *unmapped* inside the
    namespace, and the kernel cannot match it against the worker, so a
    mode-700 directory is unreachable and the run dies in ``--chdir``. Owned by
    guest-root, the same directory is presented to the worker as its own, and
    ``0o700`` is then genuinely private: the worker cannot read it as anyone
    else, and the host user cannot either.

    The parent is created once at mode ``0o711``, so a worker can be given a
    path into its own directory without being able to enumerate its siblings.
    A pre-existing directory of the same name is a refusal rather than a reuse,
    because reusing one would let a previous run's files be visible to this run.
    """

    try:
        os.makedirs(GUEST_WORKSPACE_ROOT, mode=0o711, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(f"cannot create the workspace root: {exc}") from exc

    workspace = os.path.join(GUEST_WORKSPACE_ROOT, execution_id)
    if os.path.exists(workspace):
        raise RuntimeError(
            f"workspace {execution_id} already exists; refusing to reuse a workspace"
        )
    os.mkdir(workspace, 0o700)
    for name in (INPUT_SUBDIR, OUTPUT_SUBDIR, TMP_SUBDIR):
        os.mkdir(os.path.join(workspace, name), 0o700)
    return workspace


def _write_request(workspace: str, payload: bytes) -> str:
    """Write the request where the confined worker can read it.

    The file inherits guest-root ownership and mode ``0o600``, which the user
    namespace presents to the worker as its own. See :func:`_prepare_workspace`
    for why an explicit ``chown`` to uid 65534 would break access.
    """

    path = os.path.join(workspace, INPUT_SUBDIR, REQUEST_NAME)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return path


def _destroy_workspace(workspace: str) -> None:
    shutil.rmtree(workspace, ignore_errors=True)


def _terminate(
    process: subprocess.Popen[bytes], handle: cgroups.CgroupHandle | None
) -> tuple[int | None, int | None]:
    """Stop a process tree that overran its deadline.

    Three escalating steps, because each covers something the previous one
    misses. The process-group signal reaches ordinary children. ``SIGKILL``
    reaches ones that ignore ``SIGTERM`` and, crucially, ones that called
    ``setsid`` to leave the group — which is why this cannot be reduced to
    ``process.kill()``. ``cgroup.kill`` reaches a process that also re-parented
    itself out of the group, because the cgroup still contains it.
    """

    def signal_group(number: int) -> None:
        try:
            os.killpg(os.getpgid(process.pid), number)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    signal_group(signal.SIGTERM)
    try:
        process.wait(timeout=TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    else:
        return process.returncode, signal.SIGTERM

    signal_group(signal.SIGKILL)
    try:
        process.wait(timeout=REAP_SECONDS)
    except subprocess.TimeoutExpired:
        if handle is not None:
            handle.kill()
        try:
            process.wait(timeout=REAP_SECONDS)
        except subprocess.TimeoutExpired:
            return None, signal.SIGKILL
    return process.returncode, signal.SIGKILL


def _start_watchdog(
    handle: cgroups.CgroupHandle | None, deadline: float, cancelled: threading.Event
) -> threading.Thread | None:
    """Blow away the cgroup and exit if the launcher overruns badly.

    The cancellation event is what makes this safe to arm per invocation. A
    watchdog left running past the invocation it was armed for would fire during
    a later one and kill an unrelated cgroup, so the caller must always signal
    it, including on the success path.
    """

    if handle is None:
        return None

    def wait() -> None:
        while not cancelled.wait(timeout=0.2):
            if time.monotonic() >= deadline:
                handle.kill()
                sys.stderr.write(
                    "atlasx-launcher: watchdog expired; abandoning the invocation\n"
                )
                sys.stderr.flush()
                os._exit(EXIT_WATCHDOG)

    thread = threading.Thread(target=wait, name="atlasx-watchdog", daemon=True)
    thread.start()
    return thread


def _read_worker_report(path: str, *, self_test: bool) -> WorkerReport:
    """Read the confined process's result document.

    A tool worker writes a :class:`WorkerReport`. The conformance harness writes
    its own shape, which is wrapped into a report here so that everything
    downstream — the envelope, the supervisor, the test — sees one type. A
    harness document that cannot be parsed is an internal error, not a passing
    run with no findings: "the probe did not report" is not "the probe passed".
    """

    try:
        with open(path, "rb") as handle:
            payload = handle.read()
    except OSError as exc:
        raise ProtocolError(
            f"the confined process wrote no report; it exited before completing "
            f"({exc.strerror})"
        ) from exc
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"the result document was not JSON: {exc}") from exc

    if self_test:
        if not isinstance(document, dict):
            raise ProtocolError("the conformance document was not an object")
        return WorkerReport(
            status=Status.OK.value,
            violation=None,
            output=document,
            error_message=None,
        )
    return WorkerReport.from_json(document)


def _surviving_descendants(workspace: str) -> list[int]:
    """Which recorded descendant pids are still alive after the kill.

    Only the launcher can answer this: it is root, it is outside the process
    group it signalled, and the confined process is by then gone. A daemonizing
    grandchild that survived would appear here, and the run is reported as a
    containment failure rather than as a successful timeout.
    """

    path = os.path.join(workspace, OUTPUT_SUBDIR, "descendants.json")
    try:
        with open(path, "r", encoding="ascii") as handle:
            document = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(document, dict):
        return []
    pids = document.get("pids")
    if not isinstance(pids, list):
        return []
    alive: list[int] = []
    for value in pids:
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        try:
            os.kill(value, 0)
        except ProcessLookupError:
            continue
        except PermissionError:
            alive.append(value)
        else:
            alive.append(value)
    return sorted(alive)


def _read_limits(
    handle: cgroups.CgroupHandle, limits: Limits
) -> dict[str, str | None]:
    """Read the enforced control files back out of the leaf cgroup.

    The report is supposed to state which limits were in force, and a value read
    back from the kernel is stronger evidence than the value the launcher meant to
    write. A limit that silently failed to apply shows up here as a mismatch
    rather than as a claim in a document nobody checked.
    """

    wanted = {
        "memory.max": f"{limits.memory_mb * 1024 * 1024}",
        "pids.max": str(limits.pids_max),
    }
    read: dict[str, str | None] = {}
    for name in ("memory.max", "pids.max", "cpu.max", "memory.swap.max"):
        try:
            with open(handle.file(name), "r", encoding="ascii") as source:
                read[name] = source.read().strip()
        except OSError:
            read[name] = None
    read["expected_pids_max"] = wanted["pids.max"]
    read["expected_memory_max"] = wanted["memory.max"]
    return read


def _hit_memory_cap(
    handle: cgroups.CgroupHandle | None,
    usage: cgroups.CgroupUsage | None,
    exit_code: int | None,
) -> bool:
    """Whether the kernel's memory control stopped this invocation.

    ``memory.max`` has two honest outcomes and the counters distinguish them: the
    OOM killer fires (``oom_kill`` above zero), or the cap is reached and
    allocation is refused while the process lives (``max`` above zero with no
    kill). Either means the bound is real, which is what a caller needs to know;
    which of the two happened is a detail of the workload's allocation pattern,
    not a difference in what was enforced.

    A signal-based death alone is not enough to conclude this. ``SIGKILL`` is also
    what a process-group kill looks like, so the cgroup's own counters are
    required — reading them from outside is what makes the distinction possible
    rather than guessed.
    """

    if handle is None or usage is None:
        return False
    events = usage.events
    if int(events.get("oom_kill", 0)) > 0 or int(events.get("oom_group_kill", 0)) > 0:
        return True
    if int(events.get("max", 0)) > 0 and int(events.get("oom", 0)) > 0:
        return True
    return False


def run_invocation(
    *,
    command: list[str],
    workspace: str,
    request: Request,
    handle: cgroups.CgroupHandle | None,
    self_test: bool = False,
) -> tuple[WorkerReport | None, Diagnostics, Status | None, ViolationKind | None, str | None]:
    """Confine and run one command, then report what happened.

    Returns the worker's own report when there is one, the diagnostics observed
    from outside, and — when the command could not be started at all — a status
    and violation to report instead. The split matters: a launch failure is the
    launcher's account of events, while everything else is the confined process's.
    """

    stdout_path = os.path.join(workspace, OUTPUT_SUBDIR, STDOUT_NAME)
    stderr_path = os.path.join(workspace, OUTPUT_SUBDIR, STDERR_NAME)
    limits = request.limits
    started = time.monotonic()
    deadline = started + limits.timeout_seconds

    cancelled = threading.Event()
    watchdog = _start_watchdog(handle, deadline + WATCHDOG_MARGIN_SECONDS, cancelled)

    streams = (open(stdout_path, "wb"), open(stderr_path, "wb"))
    try:
        try:
            if handle is None:
                # No cgroup was created, so there is nothing to join. This is
                # only reachable on a guest that refused to create one, which
                # main() has already turned into a refusal to run.
                process = subprocess.Popen(  # noqa: S603 - argv assembled here
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=streams[0],
                    stderr=streams[1],
                    start_new_session=True,
                    close_fds=True,
                )
            else:
                # Started *through* the cgroup, not adopted afterwards. See
                # cgroups.exec_in_group: bwrap forks the worker while it builds
                # namespaces, and a process moved into a cgroup only bounds what
                # it forks afterwards, so a post-hoc move leaves the worker
                # outside every limit while the run reports success.
                process = cgroups.exec_in_group(
                    handle=handle,
                    command=command,
                    joiner=GUEST_JOINER_PATH,
                    stdin=subprocess.DEVNULL,
                    stdout=streams[0],
                    stderr=streams[1],
                    start_new_session=True,
                    close_fds=True,
                )
        except OSError as exc:
            return (
                None,
                _empty_diagnostics(),
                Status.INTERNAL_ERROR,
                ViolationKind.INTERNAL_ERROR,
                f"could not start the confined process: {exc.strerror}",
            )
    finally:
        for stream in streams:
            stream.close()

    # Membership is *not* re-checked here. The joiner writes its own pid, reads
    # it back, and refuses to exec if the kernel did not accept it, so the
    # guarantee is established before the workload exists. A check from here
    # would race: Popen returns as soon as the fork succeeds, which can be
    # before the joiner has written anything, so an eager check reports a
    # failure for correctly-bounded runs.

    timed_out = False
    try:
        process.wait(timeout=max(0.1, deadline - time.monotonic()))
        exit_code: int | None = process.returncode
        term_signal: int | None = None
    except subprocess.TimeoutExpired:
        timed_out = True
        exit_code, term_signal = _terminate(process, handle)

    if watchdog is not None:
        # Always disarm, including on the success path: a watchdog still armed
        # for a deadline we beat would fire during a later invocation on this
        # host and kill an unrelated cgroup.
        cancelled.set()

    survivors = _surviving_descendants(workspace) if timed_out else []
    usage = handle.usage() if handle is not None else None
    diagnostics = Diagnostics(
        exit_code=exit_code,
        signal=term_signal,
        stdout=_tail(stdout_path),
        stderr=_tail(stderr_path),
        cgroup_peak_bytes=None if usage is None else usage.peak_bytes,
        cgroup_events={} if usage is None else dict(usage.events),
        observations={
            "surviving_descendants": survivors,
            "cgroup_path": None if handle is None else handle.path,
            "cgroup_controllers": [] if handle is None else list(handle.enabled_controllers),
            "cgroup_removed": None if handle is None else handle.removed,
            # What the launcher wrote and then read back, so the limits being
            # claimed are the limits that are in force. The confined process
            # cannot check this itself: its cgroup namespace root hides the
            # hierarchy, which is the point of the namespace.
            "cgroup_limits": {} if handle is None else _read_limits(handle, limits),
        },
    )

    if survivors:
        return (
            None,
            diagnostics,
            Status.POLICY_DENIED,
            ViolationKind.PROCESS_LIMIT,
            f"descendant processes {survivors!r} outlived the kill; the invocation "
            "was not contained",
        )

    # Read before deciding the status, because a worker that was killed *after*
    # durably writing its report still has a report. The status says the run
    # failed; the report is the worker's own account of how it got there, and
    # discarding it would throw away the only statement the process got to make.
    result_path = os.path.join(workspace, OUTPUT_SUBDIR, RESULT_NAME)
    try:
        report = _read_worker_report(result_path, self_test=self_test)
    except ProtocolError:
        report = None

    if _hit_memory_cap(handle, usage, exit_code):
        # Distinct from a timeout even though both end in a kill: the cause is a
        # resource bound being enforced, not a deadline being missed, and the
        # audit record should say which happened.
        return (
            report,
            diagnostics,
            Status.RESOURCE_EXCEEDED,
            ViolationKind.MEMORY_LIMIT,
            f"the invocation was stopped at its {limits.memory_mb} MiB memory cap",
        )

    if timed_out:
        return (
            report,
            diagnostics,
            Status.TIMEOUT,
            ViolationKind.TIMEOUT,
            f"the invocation exceeded its {limits.timeout_seconds}s bound and the "
            "process tree was killed",
        )

    if report is None:
        return (
            None,
            diagnostics,
            Status.INTERNAL_ERROR,
            ViolationKind.INTERNAL_ERROR,
            "the confined process wrote no usable report",
        )

    violation = None if report.violation is None else ViolationKind(report.violation)
    status = Status(report.status)
    return report, diagnostics, status, violation, report.error_message


def _command_for(
    request: Request, result_path: str, self_test: str | None
) -> list[str]:
    """The confined command tail: a worker, or the conformance harness.

    Both read their request from inside the workspace rather than from argv, so
    neither needs a path the supervisor supplied and neither can be pointed at a
    different document by anything on the request.
    """

    request_path = os.path.join(
        request.extra_env.get("ATLASX_WORKSPACE", "/workspace"),
        INPUT_SUBDIR,
        REQUEST_NAME,
    )
    if self_test is not None:
        return [
            GUEST_PYTHON,
            "-m",
            "atlas.sandbox.guest.selftest",
            self_test,
            request_path,
            result_path,
        ]
    return [GUEST_PYTHON, "-m", "atlas.sandbox.guest.worker", request_path, result_path]


def main(argv: list[str] | None = None) -> int:
    """Read one request from stdin, run it under confinement, write one envelope."""

    parser = argparse.ArgumentParser(
        prog="atlasx-launcher",
        description="Run one ATLAS-X tool invocation inside a Linux sandbox.",
    )
    parser.add_argument(
        "--self-test",
        default=None,
        help="run a named conformance probe instead of a tool worker (test-only)",
    )
    arguments, _unknown = parser.parse_known_args(argv)

    started = time.monotonic()
    workspace: str | None = None
    handle: cgroups.CgroupHandle | None = None

    try:
        payload = _read_bounded_stdin()
        request = decode_request(payload)
        if not EXECUTION_ID_PATTERN.fullmatch(request.execution_id):
            raise ProtocolError("execution_id is not a 32-character hex value")
        workspace = _prepare_workspace(request.execution_id)
        _write_request(workspace, payload)

        try:
            handle = cgroups.create(
                execution_id=request.execution_id,
                memory_mb=request.limits.memory_mb,
                pids_max=request.limits.pids_max,
                cpu_cores=request.limits.cpu_cores,
            )
        except cgroups.CgroupUnavailable as exc:
            _destroy_workspace(workspace)
            return _emit(
                _envelope(
                    status=Status.INTERNAL_ERROR,
                    violation=ViolationKind.MEMORY_LIMIT,
                    output=None,
                    message=f"the guest cannot enforce the declared limits: {exc}",
                    elapsed_ms=_elapsed_ms(started),
                    diagnostics=_empty_diagnostics(),
                )
            )

        policy = build_policy(
            limits=request.limits,
            environment_names=ENVIRONMENT_NAMES,
            workspace_source=workspace,
        )
        environment = build_environment(
            workspace=policy.workspace,
            tool_id=request.tool_id,
            execution_id=request.execution_id,
            extra=tuple(sorted(request.extra_env.items())),
        )
        # Two paths, and conflating them is the bug this comment exists to
        # prevent. ``workspace`` is where the directory lives on the guest
        # (``/var/lib/atlasx/workspaces/<id>``), which the confined process cannot
        # see: the mount plan does not expose that parent, and hiding it is
        # deliberate. The process sees the same directory at the fixed
        # ``policy.workspace`` (``/workspace``), which is therefore the path that
        # goes on the worker's command line. The launcher reads the result back
        # from ``workspace`` afterwards, outside the namespace.
        confined_result_path = os.path.join(
            policy.workspace, OUTPUT_SUBDIR, RESULT_NAME
        )
        command = build_argv(
            policy,
            command=_command_for(request, confined_result_path, arguments.self_test),
            uid=WORKER_UID,
            gid=WORKER_GID,
            merged_usr=probe_merged_usr(),
            environment=environment,
        )

        report, diagnostics, status, violation, message = run_invocation(
            command=command,
            workspace=workspace,
            request=request,
            handle=handle,
            self_test=arguments.self_test is not None,
        )

        if report is not None:
            output = None if report.output is None else dict(report.output)
            envelope = _envelope(
                status=status or Status.OK,
                violation=violation,
                output=output,
                message=message,
                elapsed_ms=_elapsed_ms(started),
                diagnostics=diagnostics,
                error_code=report.error_code,
            )
        else:
            envelope = _envelope(
                status=status or Status.INTERNAL_ERROR,
                violation=violation,
                output=None,
                message=message,
                elapsed_ms=_elapsed_ms(started),
                diagnostics=diagnostics,
            )
        return _emit(envelope)

    except ProtocolError as exc:
        return _emit(
            _envelope(
                status=Status.INTERNAL_ERROR,
                violation=ViolationKind.PROTOCOL_ERROR,
                output=None,
                message=str(exc),
                elapsed_ms=_elapsed_ms(started),
                diagnostics=_empty_diagnostics(),
            )
        )
    except Exception as exc:  # noqa: BLE001 - the launcher must always answer
        return _emit(
            _envelope(
                status=Status.INTERNAL_ERROR,
                violation=ViolationKind.INTERNAL_ERROR,
                output=None,
                message=f"launcher failure: {type(exc).__name__}: {exc}",
                elapsed_ms=_elapsed_ms(started),
                diagnostics=_empty_diagnostics(),
            )
        )
    finally:
        if handle is not None:
            handle.kill()
            handle.remove()
        if workspace is not None:
            _destroy_workspace(workspace)


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _emit(envelope: Envelope) -> int:
    """Write the single response document and report success to the caller.

    A non-zero process status would be redundant with the envelope and would
    make the supervisor treat a well-formed refusal as a transport failure, so
    the exit status stays zero whenever an envelope was produced.
    """

    sys.stdout.buffer.write(encode_envelope(envelope))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
