"""The Windows side of the sandbox: one ``wsl.exe`` call per tool invocation.

The supervisor is the only component that crosses the Windows/Linux boundary. It
builds the request, starts the guest launcher, and turns what comes back into a
:class:`~atlas.sandbox.result.SandboxOutcome` or an error in the platform's
taxonomy. It holds no confinement responsibility of its own: everything about
namespaces, mounts, capabilities, cgroups, and the wall clock is decided in the
guest, and this side cannot loosen any of it.

Three things here are worth more attention than their size suggests.

**There is no in-process path.** Not behind a flag, not in a fallback branch, not
when the guest is missing. If the launcher cannot be started, the invocation
fails with :class:`~atlas.tools.errors.SandboxUnavailable`. A "run it unsandboxed
if the sandbox is unavailable" branch is a bypass with an availability trigger,
and availability is exactly the thing that lapses; the requirement was that every
tool goes through the sandbox, so the absence of the escape is structural.

**The outer timeout is a backstop, not the mechanism.** The guest enforces the
invocation's own bound and kills the tree from inside, where it can signal the
process group and the cgroup. This side's timeout exists for a launcher that
never answers at all — a wedged guest, a stuck WSL daemon. When it fires, the
whole ``wsl.exe`` tree is killed and the call is reported as a timeout, never as
a result.

**No host environment is forwarded.** The ``wsl.exe`` child is given an explicit,
minimal environment rather than inheriting this process's, so the Windows
``ATLAS_APPLICATION_SECRET_KEY`` cannot reach the guest, and
``appendWindowsPath`` cannot leak a host directory into the guest's ``PATH``.
"""

from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass
from typing import Any, Final, Mapping, Sequence

from atlas.sandbox.errors import (
    SandboxLauncherMissing,
    SandboxProtocolFailure,
    as_tool_error,
)
from atlas.sandbox.protocol import (
    GUEST_LAUNCHER,
    GUEST_PAYLOAD_DIR,
    GUEST_PYTHON,
    ProtocolError,
    Request,
    decode_envelope,
    encode_request,
)
from atlas.sandbox.result import SandboxOutcome
from atlas.sandbox.workspace import build_snapshots
from atlas.tools.context import OwnedTaskView
from atlas.tools.definition import ToolDefinition
from atlas.tools.errors import ToolError

__all__ = [
    "DEFAULT_DISTRO",
    "SandboxConfiguration",
    "SandboxSupervisor",
    "configuration_from_settings",
]

#: The dedicated WSL distribution. ATLAS-X provisioned this distribution
#: itself; the user's other WSL distributions are not used and not modified.
DEFAULT_DISTRO: Final = "Ubuntu-24.04"

#: Extra seconds the guest launcher is allowed beyond the invocation's own bound
#: before this side stops waiting. The guest is the one enforcing the real
#: limit; this only covers the gap between the guest's kill and its report
#: arriving.
LAUNCHER_GRACE_SECONDS: Final = 20

#: Absolute ceiling on one ``wsl.exe`` call, independent of the requested
#: timeout. A request for a 600-second tool still cannot hold a supervisor slot
#: for longer than this.
MAX_WALL_SECONDS: Final = 660

#: Environment for the ``wsl.exe`` child. Explicit rather than inherited: the
#: Windows parent holds the application secret, and a WSL interop layer will
#: forward ``WSLENV``-marked variables into the guest unless they are absent here.
WSL_CHILD_ENVIRONMENT: Final[Mapping[str, str]] = {
    "PATH": r"C:\Windows\System32;C:\Windows",
    "SystemRoot": r"C:\Windows",
    "WINTEMP": r"C:\Windows\Temp",
    "TMP": r"C:\Windows\Temp",
    "LANG": "C.UTF-8",
    "WSL_UTF8": "1",
}

#: Host paths the guest must not be able to reach. Carried in the request so the
#: worker can assert their absence rather than trusting the supervisor's argv.
#: These are guest-visible mount points, not Windows paths: the Windows drives
#: appear inside the guest under ``/mnt``, and the project lives on ``/mnt/c``.
DENIED_HOST_PATHS: Final[tuple[str, ...]] = (
    "/mnt/c/Users",
    "/mnt/d",
    "/mnt/wsl",
)


@dataclass(frozen=True)
class SandboxConfiguration:
    """The bounds and the guest identity, derived from validated settings."""

    distribution: str
    memory_mb: int
    pids_max: int
    cpu_cores: float
    max_output_bytes: int
    max_artifact_bytes: int
    launcher_timeout_seconds: int

    def as_json(self) -> dict[str, Any]:
        return {
            "distribution": self.distribution,
            "memory_mb": self.memory_mb,
            "pids_max": self.pids_max,
            "cpu_cores": self.cpu_cores,
            "max_output_bytes": self.max_output_bytes,
            "max_artifact_bytes": self.max_artifact_bytes,
            "launcher_timeout_seconds": self.launcher_timeout_seconds,
        }


def configuration_from_settings(settings: Any) -> SandboxConfiguration:
    """Read the sandbox bounds out of :class:`atlas.config.settings.Settings`.

    ``Any`` rather than the concrete type because the guest payload ships
    without pydantic, and this function is imported by neither. On the Windows
    side the attribute names are validated by the settings model itself.
    """

    return SandboxConfiguration(
        distribution=str(getattr(settings, "sandbox_distribution")),
        memory_mb=int(getattr(settings, "sandbox_memory_mb")),
        pids_max=int(getattr(settings, "sandbox_pids_max")),
        cpu_cores=float(getattr(settings, "sandbox_cpu_cores")),
        max_output_bytes=int(getattr(settings, "sandbox_max_output_bytes")),
        max_artifact_bytes=int(getattr(settings, "sandbox_max_artifact_bytes")),
        launcher_timeout_seconds=int(getattr(settings, "sandbox_launcher_timeout_seconds")),
    )


class SandboxSupervisor:
    """Runs one tool invocation inside the WSL guest and reports the outcome."""

    __slots__ = ("_configuration",)

    def __init__(self, configuration: SandboxConfiguration) -> None:
        if not configuration.distribution:
            raise SandboxLauncherMissing("no WSL distribution is configured")
        self._configuration = configuration

    @property
    def configuration(self) -> SandboxConfiguration:
        return self._configuration

    # -- process plumbing ------------------------------------------------

    def _argv(self, launcher_arguments: Sequence[str]) -> list[str]:
        """The ``wsl.exe`` command line for one launcher invocation.

        ``--exec`` rather than a shell string: the launcher's arguments are passed
        as separate argv entries and never concatenated into a command line, so
        nothing in them can be word-split or expanded by a shell. ``env`` sets
        ``PYTHONPATH`` for the payload directory because ``wsl.exe --exec`` does
        not run a login shell and therefore does not read a profile.
        """

        return [
            "wsl.exe",
            "--distribution",
            self._configuration.distribution,
            "--user",
            "root",
            "--exec",
            "/usr/bin/env",
            f"PYTHONPATH={GUEST_PAYLOAD_DIR}",
            "PYTHONDONTWRITEBYTECODE=1",
            GUEST_PYTHON,
            GUEST_LAUNCHER,
            *launcher_arguments,
        ]

    def _call(
        self, payload: bytes, *, launcher_arguments: Sequence[str], wall_seconds: int
    ) -> bytes:
        """Run the launcher once and return its stdout.

        ``wsl.exe`` may print a banner or a translation notice on this platform,
        so the envelope is located by scanning for the last line that parses as a
        protocol envelope rather than by assuming stdout is clean. The envelope
        itself is still validated strictly once found.
        """

        environment = dict(WSL_CHILD_ENVIRONMENT)
        try:
            completed = subprocess.run(  # noqa: S603 - argv built here, no shell
                self._argv(launcher_arguments),
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=wall_seconds,
                env=environment,
                close_fds=True,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self._abort()
            raise SandboxProtocolFailure(
                f"the guest launcher did not answer within {wall_seconds}s and was "
                "terminated; the invocation's own bound is enforced inside the guest, "
                "so this indicates the guest itself is not responding"
            ) from None
        except FileNotFoundError as exc:
            raise SandboxLauncherMissing(
                "wsl.exe is not available on this host, so no tool can be sandboxed"
            ) from exc
        except OSError as exc:
            raise SandboxLauncherMissing(
                f"the guest launcher could not be started: {exc.strerror}"
            ) from exc

        if completed.returncode != 0 and not completed.stdout.strip():
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise SandboxLauncherMissing(
                "the guest launcher produced no report"
                + (f": {detail[:400]}" if detail else "")
                + f" (exit status {completed.returncode})"
            )
        return completed.stdout

    def _abort(self) -> None:
        """Best-effort teardown of the WSL side after an outer timeout.

        Killing ``wsl.exe`` does not by itself stop a Linux process, which is why
        this is a backstop and not the mechanism. The guest watchdog is the
        primary stop for a wedged invocation, and this exists to release the
        Windows-side handles.
        """

        try:
            listing = subprocess.run(  # noqa: S603
                ["wsl.exe", "--list", "--quiet"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=20,
                close_fds=True,
                check=False,
            )
            running = listing.stdout.decode("utf-8", errors="replace")
        except (OSError, subprocess.SubprocessError):
            return
        if self._configuration.distribution not in running:
            return
        try:
            subprocess.run(  # noqa: S603
                [
                    "wsl.exe",
                    "--terminate",
                    self._configuration.distribution,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
                close_fds=True,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return

    # -- envelope extraction ---------------------------------------------

    @staticmethod
    def _extract_envelope(stdout: bytes) -> Any:
        """Find the last line of ``stdout`` that is a valid protocol envelope."""

        last_error: Exception | None = None
        for line in reversed(stdout.splitlines()):
            candidate = line.strip()
            if not candidate.startswith(b"{"):
                continue
            try:
                return decode_envelope(candidate)
            except ProtocolError as exc:
                last_error = exc
        if last_error is not None:
            raise SandboxProtocolFailure(
                f"the guest produced no usable envelope: {last_error}"
            ) from last_error
        raise SandboxProtocolFailure("the guest produced no envelope at all")

    # -- request construction --------------------------------------------

    def _request(
        self,
        *,
        definition: ToolDefinition,
        arguments: Mapping[str, Any],
        user_id: int,
        task_id: int,
        view: OwnedTaskView,
        extra_env: Mapping[str, str] | None = None,
    ) -> Request:
        """Build the request, or refuse before any guest work happens."""

        from atlas.sandbox.policy import derive_limits

        configuration = self._configuration
        limits = derive_limits(
            timeout_seconds=definition.limits.timeout_seconds,
            memory_mb=configuration.memory_mb,
            pids_max=configuration.pids_max,
            cpu_cores=configuration.cpu_cores,
            max_output_bytes=min(
                definition.limits.max_output_bytes, configuration.max_output_bytes
            ),
            max_artifact_bytes=(
                configuration.max_artifact_bytes
                if definition.limits.max_artifact_bytes is None
                else min(
                    definition.limits.max_artifact_bytes,
                    configuration.max_artifact_bytes,
                )
            ),
        )
        snapshots = build_snapshots(view=view, user_id=user_id, task_id=task_id)
        return Request(
            protocol_version=1,
            execution_id=uuid.uuid4().hex,
            tool_id=definition.tool_id,
            tool_version=definition.version,
            implementation_id=definition.implementation_id,
            user_id=user_id,
            task_id=task_id,
            arguments=arguments,
            snapshots=snapshots,
            limits=limits,
            extra_env=dict(extra_env or {}),
            denied_paths=DENIED_HOST_PATHS,
        )

    # -- public surface ---------------------------------------------------

    def execute(
        self,
        *,
        definition: ToolDefinition,
        arguments: Mapping[str, Any],
        user_id: int,
        task_id: int,
        view: OwnedTaskView,
        extra_env: Mapping[str, str] | None = None,
    ) -> SandboxOutcome:
        """Run one tool body in the guest and return what happened.

        Raises only for failures of the boundary itself — the launcher could not
        be started, or it did not answer. A *sandboxed* failure, including a
        crossed control and a timeout, is returned as an outcome and converted to
        the platform's error taxonomy by the caller, which is what puts the right
        code in the audit record.
        """

        request = self._request(
            definition=definition,
            arguments=arguments,
            user_id=user_id,
            task_id=task_id,
            view=view,
            extra_env=extra_env or {},
        )
        wall_seconds = min(
            MAX_WALL_SECONDS,
            request.limits.timeout_seconds + LAUNCHER_GRACE_SECONDS,
        )
        stdout = self._call(
            encode_request(request),
            launcher_arguments=(),
            wall_seconds=wall_seconds,
        )
        envelope = self._extract_envelope(stdout)
        return SandboxOutcome.from_envelope(
            envelope, memory_limit_bytes=request.limits.memory_mb * 1024 * 1024
        )

    def run_conformance_probe(
        self,
        *,
        group: str,
        timeout_seconds: int = 30,
        memory_mb: int = 512,
        pids_max: int = 64,
        max_artifact_bytes: int = 8 * 1024 * 1024,
    ) -> SandboxOutcome:
        """Run a named conformance probe under the same confinement.

        Test-only by construction: the dispatcher has no path here, and the
        launcher accepts only a probe name defined in
        :mod:`atlas.sandbox.guest.selftest` rather than a command.
        """

        from atlas.sandbox.policy import derive_limits

        limits = derive_limits(
            timeout_seconds=timeout_seconds,
            memory_mb=memory_mb,
            pids_max=pids_max,
            cpu_cores=1.0,
            max_output_bytes=1024 * 1024,
            max_artifact_bytes=max_artifact_bytes,
        )
        request = Request(
            protocol_version=1,
            execution_id=uuid.uuid4().hex,
            tool_id="conformance",
            tool_version="0.0.0",
            implementation_id="atlas.sandbox.guest.selftest",
            user_id=1,
            task_id=1,
            arguments={},
            snapshots=(),
            limits=limits,
            extra_env={},
            denied_paths=DENIED_HOST_PATHS,
        )
        stdout = self._call(
            encode_request(request),
            launcher_arguments=("--self-test", group),
            wall_seconds=min(MAX_WALL_SECONDS, timeout_seconds + LAUNCHER_GRACE_SECONDS),
        )
        envelope = self._extract_envelope(stdout)
        return SandboxOutcome.from_envelope(
            envelope, memory_limit_bytes=limits.memory_mb * 1024 * 1024
        )

    def health(self) -> Mapping[str, Any]:
        """Whether the guest can be reached and the payload is installed.

        Used to fail with an actionable message at startup rather than letting
        every dispatch fail one at a time. It does not weaken anything: an
        unhealthy guest still causes the invocation to fail, it just fails with a
        better message.
        """

        try:
            completed = subprocess.run(  # noqa: S603
                [
                    "wsl.exe",
                    "--distribution",
                    self._configuration.distribution,
                    "--user",
                    "root",
                    "--exec",
                    "/usr/bin/test",
                    "-f",
                    GUEST_LAUNCHER,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
                env=dict(WSL_CHILD_ENVIRONMENT),
                close_fds=True,
                check=False,
            )
        except FileNotFoundError:
            return {"available": False, "reason": "wsl.exe is not installed"}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}

        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            return {
                "available": False,
                "reason": (
                    f"the guest launcher is missing at {GUEST_LAUNCHER}; run "
                    f"`python -m atlas.sandbox.provision` ({detail[:200]})"
                ),
            }
        return {"available": True, "reason": None}


def require_success(outcome: SandboxOutcome) -> Mapping[str, Any]:
    """The output of a successful outcome, or the matching tool error."""

    if outcome.ok:
        return outcome.require_output()
    raise classify(outcome)


def classify(outcome: SandboxOutcome) -> ToolError:
    """Turn an unsuccessful outcome into the platform's error taxonomy."""

    from atlas.sandbox.errors import classify_envelope

    error = classify_envelope(
        status=outcome.status.value,
        violation=None if outcome.violation is None else outcome.violation.value,
        message=outcome.message or "",
        error_code=outcome.error_code,
    )
    return as_tool_error(error)
